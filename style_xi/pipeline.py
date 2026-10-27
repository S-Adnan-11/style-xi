"""Replay response envelopes without network access or implicit context joins."""

from collections import Counter, defaultdict
from pathlib import Path

from .coverage import inspect_pages
from .normalize import aggregate, mapping, normalize_match, positive_id
from .storage import DataError, atomic_json, digest, read_json


def load_snapshots(directory):
    snapshots = []
    paths = sorted(Path(directory).glob("*.json"))
    if not paths:
        raise DataError("no_response_snapshots")
    for path in paths:
        item = read_json(path)
        if (not isinstance(item, dict) or not isinstance(item.get("endpoint"), str)
                or "body" not in item or not isinstance(item.get("parameters", {}), dict)):
            raise DataError("invalid_snapshot_envelope")
        if item.get("status") != 200:
            continue
        if "stored_body_sha256" in item:
            if digest(item["body"]) != item["stored_body_sha256"]:
                raise DataError("snapshot_hash_mismatch")
        snapshot_id = digest({k: item.get(k) for k in ("endpoint", "parameters", "scope", "body", "retrieved_utc")})
        snapshots.append({**item, "snapshot_id": snapshot_id, "source_file": path.name})
    return snapshots


def replay(snapshots):
    fixtures, boxes = defaultdict(dict), defaultdict(list)
    diagnostics = []
    for item in snapshots:
        endpoint, body = item["endpoint"], item["body"]
        if endpoint.endswith("/matches") and isinstance(body, dict) and isinstance(body.get("data"), list):
            for row in body["data"]:
                if isinstance(row, dict) and positive_id(row.get("id")):
                    fixtures[row["id"]][digest(row)] = row
        elif "/box-score/" in endpoint:
            try:
                mid = int(endpoint.rsplit("/", 1)[1])
                if not positive_id(mid):
                    raise ValueError()
            except ValueError:
                raise DataError("invalid_box_endpoint") from None
            boxes[mid].append(item)
    accepted, excluded = [], []
    for mid, items in sorted(boxes.items()):
        provenance = sorted([{"snapshot_id": i["snapshot_id"], "source_file": i["source_file"],
                              "body_sha256": digest(i["body"]), "retrieved_utc": i.get("retrieved_utc")}
                             for i in items], key=lambda x: (x["snapshot_id"], x["source_file"]))
        reason = None
        if len(fixtures[mid]) != 1:
            reason = "missing_fixture_context" if not fixtures[mid] else "conflicting_fixture_context"
        elif len({digest(i["body"]) for i in items}) != 1:
            reason = "conflicting_box_snapshots"
        else:
            fixture = next(iter(fixtures[mid].values()))
            for item in items:
                scope = item.get("scope", {})
                if not isinstance(scope, dict):
                    reason = "invalid_snapshot_scope"
                    break
                for key, expected in (("match_id", mid), ("league_id", mapping(fixture.get("league")).get("id")),
                                      ("competition_id", mapping(fixture.get("league")).get("id")),
                                      ("season", mapping(fixture.get("league")).get("season"))):
                    if key in scope and scope[key] != expected:
                        reason = "snapshot_scope_mismatch"
        if reason:
            diagnostics.append({"match_id": mid, "status": "quarantined", "reasons": [reason], "provenance": provenance})
            continue
        try:
            good, bad = normalize_match(fixture, items[0]["body"], provenance)
        except (TypeError, AttributeError, ValueError):
            diagnostics.append({"match_id": mid, "status": "quarantined", "reasons": ["malformed_nested_schema"], "provenance": provenance})
            continue
        accepted.extend(good)
        excluded.extend(bad)
    reasons = Counter(r for row in excluded + diagnostics for r in row["reasons"])
    return {"schema_version": 1, "scope": "observed_sample_incomplete",
            "validation": {"structural_and_arithmetic": "checked_for_accepted_records",
                           "independent_accuracy": "not_established"},
            "summary": {"accepted": len(accepted), "excluded": len(excluded),
                        "match_diagnostics": len(diagnostics), "reason_counts": dict(sorted(reasons.items()))},
            "player_matches": accepted, "excluded_records": excluded,
            "match_diagnostics": diagnostics, "sample_aggregates": aggregate(accepted),
            "coverage": inspect_pages(snapshots, set(boxes)),
            "source_snapshots": sorted({i["snapshot_id"] for i in snapshots})}


def import_cache(directory, output):
    result = replay(load_snapshots(directory))
    atomic_json(output, result)
    return result
