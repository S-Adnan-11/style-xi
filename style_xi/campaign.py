"""Manual, fixed-scope season collection using the existing one-shot downloader."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time

from .acquire import Downloader, daily_usage, fresh_remaining
from .coverage import inspect_pages
from .normalize import normalize_match, stage_for
from .pipeline import load_snapshots, replay
from .profiles import build_profiles
from .storage import DataError, atomic_json, digest, exclusive, now, read_json

COMPLETED = ("Finished", "Finished after extra time", "Finished after penalties")
FIELDS = ("passesTotal", "dribblesTotal", "tacklesTotal", "shotsTotal")
EXCLUDED_STAGES = ("Final", "Semi-finals", "Relegation round - Quarter-finals")


def classification(fixture):
    stage = stage_for(fixture)
    if fixture.get("round") in EXCLUDED_STAGES:
        return "excluded_stage"
    if stage != "regular":
        return "unresolved_stage"
    state = fixture.get("state", {}).get("description")
    if state in COMPLETED:
        return "target"
    if state in ("Not started", "Postponed", "Cancelled", "Canceled", "Abandoned",
                 "In progress", "First half", "Second half", "Halftime", "Suspended"):
        return "unfinished"
    return "unresolved_completion"


def inventory(snapshots, competitions, season):
    groups = inspect_pages(snapshots)
    fixtures, result = {}, []
    allowed = {c["id"] for c in competitions}
    for s in snapshots:
        if not s["endpoint"].endswith("/matches"):
            continue
        if s["parameters"].get("leagueId") not in allowed or s["parameters"].get("season") != season:
            raise DataError("inventory_outside_campaign")
        for f in s["body"]["data"]:
            if f["id"] in fixtures and digest(fixtures[f["id"]]) != digest(f):
                raise DataError("changed_fixture_requires_reconciliation")
            fixtures[f["id"]] = f
    for competition in competitions:
        group = next((g for g in groups if g["competition_id"] == competition["id"] and g["season"] == season), None)
        if group is None:
            result.append({"competition_id": competition["id"], "name": competition["name"],
                           "provider_manifest_complete": False, "listed_unique_matches": 0,
                           "provider_listed_total": None, "next_page": {"offset": 0, "limit": 100},
                           "issues": [], "classifications": {}, "duplicate_records": 0})
            continue
        fatal = set(group["issues"]) - {"page_gap_or_overlap", "manifest_not_fully_acquired"}
        if fatal:
            raise DataError("inventory_requires_reconciliation:" + ",".join(sorted(fatal)))
        cursor, gap = 0, None
        for page in group["pages"]:
            if page["offset"] < cursor:
                raise DataError("overlapping_inventory_pages")
            if page["offset"] > cursor and gap is None:
                gap = {"offset": cursor, "limit": min(100, page["offset"] - cursor)}
            cursor = page["offset"] + len(page["match_ids"])
        if gap is None and cursor < group["provider_listed_total"]:
            gap = {"offset": cursor, "limit": min(100, group["provider_listed_total"] - cursor)}
        own = [f for f in fixtures.values() if f["league"]["id"] == competition["id"]]
        result.append({**group, "name": competition["name"], "next_page": gap,
                       "classifications": dict(Counter(classification(f) for f in own)),
                       "duplicate_records": 0})
    return result, fixtures


def next_call(groups, fixtures, usable, attempted, last_league=None):
    """Fill inventory gaps first, then rotate leagues and favour underseen clubs/months."""
    order = list(range(len(groups)))
    if last_league in [g["competition_id"] for g in groups]:
        start = next(i for i, g in enumerate(groups) if g["competition_id"] == last_league) + 1
        order = order[start:] + order[:start]
    for i in order:
        g = groups[i]
        if g["next_page"]:
            return "/matches", {"leagueId": g["competition_id"], "season": next(iter(fixtures.values()))["league"]["season"] if fixtures else None,
                                **g["next_page"]}, {"competition_id": g["competition_id"], "stage": "all_provider_stages"}
    seen = usable | attempted
    clubs, months = Counter(), Counter()
    for mid in seen:
        if mid in fixtures:
            f = fixtures[mid]
            clubs.update(f[k]["id"] for k in ("homeTeam", "awayTeam"))
            months[(f["league"]["id"], f["date"][:7])] += 1
    for i in order:
        g = groups[i]
        candidates = [f for f in fixtures.values() if f["league"]["id"] == g["competition_id"]
                      and classification(f) == "target" and f["id"] not in seen]
        if candidates:
            f = min(candidates, key=lambda f: (max(clubs[f[k]["id"]] for k in ("homeTeam", "awayTeam")),
                    months[(f["league"]["id"], f["date"][:7])], f["date"], f["id"]))
            return "/box-score/" + str(f["id"]), {}, {"competition_id": g["competition_id"],
                    "season": f["league"]["season"], "stage": "regular", "match_id": f["id"]}
    return None


class Campaign:
    def __init__(self, manifest_path, *, transport=None, sleeper=time.sleep):
        self.path = Path(manifest_path)
        self.manifest = m = read_json(self.path)
        if (m.get("version") != 1 or type(m.get("season")) is not int
                or m.get("cap") != 1800 or m.get("daily_cap") != 90 or m.get("reserve") != 10
                or m.get("regular_stage_rule") != "Regular Season - [1-9][0-9]*"
                or m.get("completed_states") != list(COMPLETED)
                or not isinstance(m.get("competitions"), list) or len(m["competitions"]) != 5
                or len({c["id"] for c in m["competitions"]}) != 5
                or not 1 <= m.get("interval_seconds", 0) <= 60):
            raise DataError("invalid_campaign_manifest")
        self.root, self.account = Path(m["state"]), Path(m["account"])
        self.identity = digest(m)
        policy = {"manifest_sha256": self.identity, "cap": 1800, "daily_cap": 90, "reserve": 10}
        kwargs = {"transport": transport} if transport else {}
        self.client = Downloader(self.root, self.account, 1800, m["history"], campaign=policy, **kwargs)
        self.sleeper = sleeper

    def initialize(self):
        """Called once by a reviewed local setup; never silently replace existing scope."""
        with exclusive(self.account.with_suffix(".run.lock")), exclusive(self.account.with_suffix(".lock")):
            account = read_json(self.account)
            policy = dict(self.client.campaign, budget_id=self.client.budget_id)
            if account.get("campaign") not in (None, policy):
                raise DataError("existing_campaign_must_not_be_replaced")
            if not account.get("campaign") and (self.root / "requests.json").exists():
                raise DataError("campaign_account_anchor_missing")
            account["campaign"] = policy
            atomic_json(self.account, account)
            atomic_json(self.root / "requests.json", self.client.ledger())
            if not (self.root / "checkpoint.json").exists():
                atomic_json(self.root / "checkpoint.json", {"manifest_sha256": self.identity, "halted": None})

    def snapshots(self):
        result = []
        for pinned in self.manifest["baseline_files"]:
            path = Path(pinned["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != pinned["sha256"]:
                raise DataError("baseline_evidence_changed")
            if pinned.get("snapshot"):
                from .pipeline import prepare_snapshot
                result.append(prepare_snapshot(read_json(path), str(path)))
        directory = self.root / "responses"
        for s in load_snapshots(directory) if directory.exists() and any(directory.glob("*.json")) else []:
            self.client.cached(s["request_id"])
            result.append(s)
        return result

    def inspect(self):
        account, ledger = read_json(self.account), self.client.ledger()
        if account.get("campaign") != dict(self.client.campaign, budget_id=self.client.budget_id):
            raise DataError("shared_campaign_scope_missing_or_changed")
        checkpoint = read_json(self.root / "checkpoint.json")
        if checkpoint.get("manifest_sha256") != self.identity:
            raise DataError("campaign_checkpoint_changed")
        shared = {(a["request_id"], a["reserved_utc"]) for a in account.get("attempts", [])
                  if a.get("budget_id") == self.client.budget_id}
        local = {(a["request_id"], a["reserved_utc"]) for a in ledger["attempts"]}
        if shared != local:
            raise DataError("uncertain_campaign_reservation_requires_review")
        gate = read_json(self.manifest["validation_gate"]) if self.manifest.get("validation_gate") else {"allow_box_scores": True}
        if type(gate.get("allow_box_scores")) is not bool:
            raise DataError("invalid_field_validation_gate")
        snapshots = self.snapshots()
        recorded = {a["request_id"]: a for a in ledger["attempts"]}
        campaign_files = {p.name for p in (self.root / "responses").glob("*.json")}
        for a in ledger["attempts"]:
            if a["outcome"] == "success":
                cached = self.client.cached(a["request_id"])
                if cached is None:
                    raise DataError("completed_response_missing_requires_review")
                if (any(cached.get(k) != a.get(k) for k in ("endpoint", "parameters", "scope"))
                        or cached["stored_body_sha256"] != a.get("snapshot_id")):
                    raise DataError("response_ledger_identity_mismatch")
        for s in snapshots:
            if s.get("request_id") and s.get("source_file") in campaign_files and s["request_id"] not in recorded:
                raise DataError("cache_without_campaign_history")
        groups, fixtures = inventory(snapshots, self.manifest["competitions"], self.manifest["season"])
        imported = replay(snapshots)
        usable = {r["match_id"] for r in imported["player_matches"]}
        quarantined = {r["match_id"] for r in imported["excluded_records"] if r["status"] == "quarantined"}
        quarantined.update(r["match_id"] for r in imported["match_diagnostics"])
        usable -= quarantined
        box_attempts = [a for a in ledger["attempts"] if "/box-score/" in a["endpoint"]]
        attempted = {int(a["endpoint"].rsplit("/", 1)[1]) for a in box_attempts}
        failures = {int(a["endpoint"].rsplit("/", 1)[1]) for a in box_attempts
                    if a["outcome"] == "failed" and a.get("status") in (404, 410)}
        manual_review = {int(a["endpoint"].rsplit("/", 1)[1]) for a in box_attempts
                         if a["outcome"] in ("failed", "reserved")} - failures
        for g in groups:
            lid = g["competition_id"]
            own = [f for f in fixtures.values() if f["league"]["id"] == lid]
            targets = {f["id"] for f in own if classification(f) == "target"}
            accepted = [r for r in imported["player_matches"] if r["match_id"] in targets]
            excluded = [r for r in imported["excluded_records"] if r["match_id"] in targets]
            g.update(target_inventory=len(targets), usable_boxes=len(targets & usable),
                     pending=len(targets - usable - failures - quarantined - manual_review),
                     unavailable=len(targets & failures), ambiguous_boxes=len(targets & quarantined),
                     manual_review=len(targets & manual_review),
                     accepted_positive_minute_records=len(accepted),
                     excluded_positive_minute_records=sum((r.get("minutes") or 0) > 0 for r in excluded),
                     ordinary_zero_minute_exclusions=sum(r["reasons"] == ["zero_minutes_zero_actions"] for r in excluded),
                     other_exclusions=sum(r["reasons"] != ["zero_minutes_zero_actions"] for r in excluded),
                     field_completeness={k: sum(r["counts"].get(k) is not None for r in accepted) for k in FIELDS},
                     teams=sorted({f[k].get("name") or str(f[k]["id"]) for f in own if classification(f) == "target" for k in ("homeTeam", "awayTeam")}),
                     rounds=dict(Counter(f["round"] for f in own if classification(f) == "target")))
        attempts = list(account.get("attempts", []))
        for path in self.manifest["history"]:
            attempts.extend(read_json(path)["attempts"])
        attempts = list({(a["request_id"], a["reserved_utc"]): a for a in attempts}.values())
        try:
            remaining = fresh_remaining(account.get("observation", {}), attempts)
        except DataError:
            remaining = None
        status = {"updated_utc": now(), "network_requests": 0, "campaign_attempts": len(ledger["attempts"]),
                  "campaign_cap": 1800, "daily_usage": daily_usage(account, attempts), "daily_cap": 90,
                  "reserve": 10, "quota_last_observed": account.get("observation", {}),
                  "quota_evidence_fresh": remaining is not None,
                  "current_evidenced_allowance": max(0, min(1800 - len(ledger["attempts"]),
                        90 - daily_usage(account, attempts), remaining - 10)) if remaining is not None else None,
                  "halted": checkpoint.get("halted") or ledger.get("halted") or account.get("halted"),
                  "uncertain_attempts": sum(a["outcome"] == "reserved" for a in ledger["attempts"]),
                  "failures": sum(a["outcome"] == "failed" for a in ledger["attempts"]),
                  "leagues": groups, "summary_all_cached_stages": imported["summary"],
                  "field_validation_gate": gate,
                  "real_comparison_readiness": "blocked_pending_independent_fields_minutes_roles_and_exposure"}
        return status, imported, fixtures, usable, attempted, snapshots

    def status(self):
        """Read-only, no credentials, no transport and no checkpoint mutations."""
        return self.inspect()[0]

    def run(self, key):
        with exclusive(self.account.with_suffix(".run.lock")), exclusive(self.root / "campaign.lock"):
            self.client.run_day = datetime.now(timezone.utc).date().isoformat()
            started = now()
            before = len(self.client.ledger()["attempts"])
            stop, fatal = "no_pending_target_requests", False
            try:
                # Recover only reservations backed by a fully written, verified response.
                for a in self.client.ledger()["attempts"]:
                    if a["outcome"] == "reserved":
                        path = a["endpoint"].replace("https://soccer.highlightly.net", "")
                        if self.client.cached(a["request_id"]) is None:
                            raise DataError("uncertain_interrupted_request_requires_review")
                        quota = self.client.cached(a["request_id"]).get("quota", {})
                        if (quota.get("x-ratelimit-requests-limit") != "100"
                                or not str(quota.get("x-ratelimit-requests-remaining", "")).isdigit()):
                            raise DataError("recovered_response_quota_requires_review")
                        self.client.get(path, a["parameters"], a["scope"], None)
                bootstrap_available = True
                while True:
                    status, imported, fixtures, usable, attempted, snapshots = self.inspect()
                    if status["halted"]:
                        raise DataError("persistent_campaign_halt:" + str(status["halted"]))
                    if status["uncertain_attempts"]:
                        raise DataError("uncertain_interrupted_request_requires_review")
                    if any(g["ambiguous_boxes"] for g in status["leagues"]):
                        raise DataError("required_field_or_identity_validation_failure")
                    ledger = self.client.ledger()
                    last = ledger["attempts"][-1]["scope"]["competition_id"] if ledger["attempts"] else None
                    call = next_call(status["leagues"], fixtures, usable, attempted, last)
                    if call is None:
                        break
                    path, params, scope = call
                    if path.startswith("/box-score/") and not status["field_validation_gate"]["allow_box_scores"]:
                        raise DataError("field_validation_pause_before_box_collection")
                    scope["season"] = self.manifest["season"]
                    if path == "/matches":
                        params["season"] = self.manifest["season"]
                    if datetime.now(timezone.utc).date().isoformat() != self.client.run_day:
                        raise DataError("utc_day_boundary")
                    if len(ledger["attempts"]) >= 1800:
                        raise DataError("request_budget_exhausted")
                    if status["daily_usage"] >= 90:
                        raise DataError("daily_account_budget_exhausted")
                    self.sleeper(self.manifest["interval_seconds"])
                    response = self.client.get(path, params, scope, key, allow_quota_bootstrap=bootstrap_available)
                    bootstrap_available = False
                    if path.startswith("/box-score/"):
                        good, bad = normalize_match(fixtures[scope["match_id"]], response["body"], [])
                        if not good or any(r["status"] == "quarantined" for r in bad):
                            raise DataError("required_field_or_identity_validation_failure")
                    atomic_json(self.root / "checkpoint.json", {"manifest_sha256": self.identity,
                                "halted": None, "last_request_id": response["request_id"], "updated_utc": now()})
            except KeyboardInterrupt:
                stop = "user_interruption"
            except DataError as error:
                stop = str(error)
                fatal = stop not in ("utc_day_boundary", "request_budget_exhausted", "daily_account_budget_exhausted",
                                     "daily_reserve_reached", "current_account_balance_unestablished",
                                     "field_validation_pause_before_box_collection")
            except Exception:
                stop, fatal = "unexpected_storage_or_schema_failure_requires_review", True
            if fatal:
                atomic_json(self.root / "checkpoint.json", {"manifest_sha256": self.identity,
                            "halted": stop, "updated_utc": now()})
            # Replay cached data even on a stop. Never hide a failed final verification.
            try:
                status, imported, fixtures, usable, attempted, snapshots = self.inspect()
                atomic_json(self.root / "import.json", imported)
                atomic_json(self.root / "profiles.json", build_profiles(imported))
                atomic_json(self.root / "inventory.json", {"fixtures": [fixtures[k] for k in sorted(fixtures)],
                            "classification": {str(k): classification(f) for k, f in fixtures.items()},
                            "leagues": status["leagues"]})
            except Exception:
                status = {"campaign_attempts": len(self.client.ledger()["attempts"]),
                          "final_verification": "failed_requires_review"}
                fatal = True
                atomic_json(self.root / "checkpoint.json", {"manifest_sha256": self.identity,
                            "halted": "final_verification_failed:" + stop, "updated_utc": now()})
            summary = {**status, "started_utc": started, "finished_utc": now(), "stop_reason": stop,
                       "new_attempts": len(self.client.ledger()["attempts"]) - before,
                       "workflow_halted": fatal, "scheduled_collector": False}
            atomic_json(self.root / "batches" / (started.replace(":", "-") + ".json"), summary)
            atomic_json(self.root / "status.json", summary)
            return summary
