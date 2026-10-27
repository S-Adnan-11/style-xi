"""Sequential, quota-aware one-shot requests with durable reservation history."""

import base64
from datetime import datetime, timezone
import hashlib
import http.client
import json
import re
from pathlib import Path
from urllib.parse import quote, quote_plus, urlencode

from .storage import DataError, atomic_json, digest, exclusive, now, read_json

HOST = "soccer.highlightly.net"
MAX_REQUESTS = 50
RESERVE = 10


def request_identity(path, params):
    if path == "/matches":
        if set(params) != {"leagueId", "season", "limit", "offset"}:
            raise DataError("match_parameters_required")
        if not all(type(v) is int for v in params.values()):
            raise DataError("invalid_match_parameter")
        if params["leagueId"] <= 0 or params["season"] < 2000 or not 1 <= params["limit"] <= 100 or params["offset"] < 0:
            raise DataError("invalid_match_parameter")
    elif re.fullmatch(r"/(?:box-score|lineups)/[1-9][0-9]*", path):
        if params:
            raise DataError("box_parameters_not_allowed")
    else:
        raise DataError("endpoint_not_allowed")
    return digest([path, params])


def send(path, params, key):
    connection = http.client.HTTPSConnection(HOST, timeout=20)
    try:
        query = urlencode(sorted(params.items()))
        connection.request("GET", path + ("?" + query if query else ""),
                           headers={"x-rapidapi-key": key, "Accept": "application/json",
                                    "User-Agent": "style-xi/0.1"})
        response = connection.getresponse()
        raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise DataError("response_size_limit")
        return response.status, {k.lower(): v for k, v in response.getheaders()}, raw
    finally:
        connection.close()


def scrub(value, key):
    variants = {key, quote(key, safe=""), quote_plus(key), base64.b64encode(key.encode()).decode()}
    if isinstance(value, dict):
        return {scrub(k, key): "[REDACTED]" if re.search(r"api.?key|authorization|token|secret|password", k, re.I)
                else scrub(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, key) for v in value]
    if isinstance(value, str):
        for variant in sorted(variants, key=len, reverse=True):
            value = value.replace(variant, "[REDACTED]")
    return value


def fresh_remaining(observation, attempts, at=None):
    """Never infer a reset or treat an old balance as today's allowance."""
    at = at or datetime.now(timezone.utc)
    try:
        observed = datetime.fromisoformat(observation["observed_utc"])
        remaining = observation["remaining"]
        if type(remaining) is not int or remaining < 0:
            raise ValueError()
        age = (at - observed).total_seconds()
        if not 0 <= age <= 300 or observed.date() != at.date():
            raise ValueError()
        subsequent = sum(datetime.fromisoformat(a["reserved_utc"]) > observed for a in attempts)
        return remaining - subsequent
    except (KeyError, TypeError, ValueError):
        raise DataError("current_account_balance_unestablished") from None


class Downloader:
    def __init__(self, root, account, cap=MAX_REQUESTS, history=(), transport=send):
        if type(cap) is not int or not 1 <= cap <= MAX_REQUESTS:
            raise DataError("request_cap_must_be_1_to_50")
        self.root, self.account = Path(root), Path(account)
        self.cap, self.history, self.transport = cap, tuple(map(Path, history)), transport
        self.budget_id = digest(str(self.root.resolve()))

    def ledger(self):
        path = self.root / "requests.json"
        if path.exists():
            state = read_json(path)
            if (not isinstance(state, dict) or state.get("cap") != self.cap
                    or not isinstance(state.get("attempts"), list)
                    or len(state["attempts"]) > self.cap
                    or not all(isinstance(a, dict) for a in state["attempts"])
                    or [a.get("number") for a in state["attempts"]] != list(range(1, len(state["attempts"]) + 1))):
                raise DataError("request_ledger_corrupt_or_cap_changed")
            return state
        if (self.root / "responses").exists() and any((self.root / "responses").iterdir()):
            raise DataError("ledger_missing_with_cache")
        return {"version": 1, "cap": self.cap, "halted": None, "attempts": []}

    def cached(self, identity):
        matches = sorted((self.root / "responses").glob(identity + ".*.json"))
        if not matches:
            return None
        snapshots = [read_json(p) for p in matches]
        if any(s.get("request_id") != identity or digest(s["body"]) != s.get("stored_body_sha256")
               for s in snapshots):
            raise DataError("cache_integrity_failure")
        if any(s.get("raw_body_retained") and hashlib.sha256(s["raw_body_utf8"].encode("utf-8")).hexdigest()
               != s.get("original_body_sha256") for s in snapshots):
            raise DataError("raw_cache_integrity_failure")
        if len({s["stored_body_sha256"] for s in snapshots}) != 1:
            raise DataError("conflicting_cached_snapshots")
        return snapshots[-1]

    def plan(self, calls):
        state = self.ledger()
        return {"network_requests": 0, "budget_used": len(state["attempts"]), "budget_cap": self.cap,
                "daily_reserve": RESERVE, "account_state": str(self.account),
                "ledger": str(self.root / "requests.json"), "cache": str(self.root / "responses"),
                "calls": [{"endpoint": path, "parameters": params, "scope": scope,
                           "cached": self.cached(request_identity(path, params)) is not None}
                          for path, params, scope in calls]}

    def get(self, path, params, scope, key, *, allow_quota_bootstrap=False):
        identity = request_identity(path, params)
        if not isinstance(scope, dict) or not all(k in scope for k in ("competition_id", "season", "stage")):
            raise DataError("explicit_acquisition_scope_required")
        with exclusive(self.account.with_suffix(".lock")), exclusive(self.root / "requests.lock"):
            state = self.ledger()
            cached = self.cached(identity)
            prior = [a for a in state["attempts"] if a["request_id"] == identity]
            if cached is not None:
                if not prior:
                    raise DataError("cache_without_request_history")
                # A complete atomic snapshot is evidence after interruption between cache and ledger writes.
                if prior[-1]["outcome"] == "reserved":
                    prior[-1].update(outcome="success", snapshot_id=cached["stored_body_sha256"])
                    atomic_json(self.root / "requests.json", state)
                return cached
            if state["halted"] or any(a["outcome"] == "reserved" for a in state["attempts"]):
                raise DataError("persistent_halt_or_uncertain_interrupted_request")
            if prior:
                raise DataError("previous_attempt_not_repeated")
            if len(state["attempts"]) >= self.cap:
                raise DataError("request_budget_exhausted")
            if not isinstance(key, str) or not 8 <= len(key) <= 512 or any(not 33 <= ord(c) <= 126 for c in key):
                raise DataError("credential_unavailable")
            if scrub({"path": path, "parameters": params, "scope": scope}, key) != {"path": path, "parameters": params, "scope": scope}:
                raise DataError("unsafe_request_metadata")
            account = read_json(self.account)
            if not isinstance(account, dict) or not isinstance(account.get("attempts", []), list):
                raise DataError("account_state_corrupt")
            if account.get("halted"):
                raise DataError("shared_account_halted")
            all_attempts = list(account.get("attempts", []))
            if not (self.root / "requests.json").exists() and any(a.get("budget_id") == self.budget_id for a in all_attempts):
                raise DataError("budget_ledger_missing_with_account_history")
            for ledger_path in self.history:
                all_attempts.extend(read_json(ledger_path)["attempts"])
            bootstrap = False
            try:
                remaining_before = fresh_remaining(account.get("observation", {}), all_attempts)
            except DataError:
                if not allow_quota_bootstrap or path != "/matches" or state["attempts"] or state.get("quota_bootstrap_used"):
                    raise
                # A current malformed balance is contradictory, not an absent/stale observation.
                observation = account.get("observation", {})
                try:
                    observed = datetime.fromisoformat(observation.get("observed_utc", ""))
                    if 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 300:
                        raise DataError("contradictory_current_quota_evidence")
                except (ValueError, TypeError):
                    pass
                bootstrap = True
                remaining_before = None
            if remaining_before is not None and remaining_before <= RESERVE:
                raise DataError("daily_reserve_reached")
            attempt = {"number": len(state["attempts"]) + 1, "request_id": identity,
                       "endpoint": "https://" + HOST + path, "parameters": params,
                       "scope": scope, "reserved_utc": now(), "outcome": "reserved", "quota_bootstrap": bootstrap}
            state["attempts"].append(attempt)
            if bootstrap:
                state["quota_bootstrap_used"] = True
            # Shared reservation first: a crash can overcount, never undercount the account.
            account.setdefault("attempts", []).append({"request_id": identity, "budget_id": self.budget_id,
                                                       "reserved_utc": attempt["reserved_utc"]})
            atomic_json(self.account, account)
            atomic_json(self.root / "requests.json", state)
            failure_body = None
            try:
                status, headers, raw = self.transport(path, params, key)
                headers = {k.lower(): v for k, v in headers.items()}
                attempt.update(status=status, retrieved_utc=now(), original_body_sha256=hashlib.sha256(raw).hexdigest())
                quota = scrub({k: str(v)[:200] for k, v in headers.items()
                               if k.startswith("x-ratelimit") or k in ("date", "retry-after", "ratelimit-reset")}, key)
                attempt["quota"] = quota
                remaining = headers.get("x-ratelimit-requests-remaining")
                if remaining is not None and str(remaining).isdigit():
                    account["observation"] = {"observed_utc": attempt["retrieved_utc"], "remaining": int(remaining), "source": "response_header"}
                else:
                    account["observation"] = {}
                atomic_json(self.account, account)
                try:
                    failure_body = scrub(json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())), key)
                    digest(failure_body)
                except (ValueError, UnicodeDecodeError):
                    failure_body = {"non_json_excerpt": scrub(raw[:1024].decode("utf-8", errors="replace"), key)}
                if status != 200:
                    raise DataError("http_" + str(status))
                body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if isinstance(body, dict) and ("error" in body or "statusCode" in body):
                    raise DataError("provider_error_in_success_body")
                if isinstance(body, dict) and "plan" in body:
                    plan = body["plan"]
                    if not isinstance(plan, dict) or plan.get("tier", "").upper() not in ("BASIC", "FREE"):
                        raise DataError("unexpected_plan")
                    if "hidden" in str(plan.get("message", "")).lower() or "restricted" in str(plan.get("message", "")).lower():
                        raise DataError("plan_access_uncertain")
                    account["plan"] = scrub(plan, key)
                elif path == "/matches":
                    raise DataError("missing_listing_plan_context")
                atomic_json(self.account, account)
                safe_body = scrub(body, key)
                snapshot = {**{k: attempt[k] for k in ("request_id", "endpoint", "parameters", "scope", "retrieved_utc", "status", "original_body_sha256")},
                            "body": safe_body, "stored_body_sha256": digest(safe_body), "quota": quota,
                            "raw_body_utf8": raw.decode("utf-8") if safe_body == body else None,
                            "raw_body_retained": safe_body == body}
                destination = self.root / "responses" / (identity + "." + snapshot["stored_body_sha256"] + ".json")
                atomic_json(destination, snapshot)
                attempt.update(outcome="success", snapshot_id=snapshot["stored_body_sha256"])
                if not account.get("observation"):
                    state["halted"] = account["halted"] = "quota_evidence_missing"
                elif remaining_before is not None and int(remaining) > remaining_before:
                    state["halted"] = account["halted"] = "contradictory_quota_increase"
                atomic_json(self.account, account)
                atomic_json(self.root / "requests.json", state)
                return snapshot
            except Exception as error:
                code = str(error) if isinstance(error, DataError) else "transport_schema_or_storage_failure"
                attempt["outcome"] = "failed"
                state["halted"] = code
                account["halted"] = code
                atomic_json(self.root / "failures" / f"{identity}.{attempt['number']}.json",
                            {"request_id": identity, "status": attempt.get("status"), "reason": code,
                             "quota": attempt.get("quota", {}), "body": failure_body,
                             "original_body_sha256": attempt.get("original_body_sha256")})
                atomic_json(self.account, account)
                atomic_json(self.root / "requests.json", state)
                raise DataError(code) from None
