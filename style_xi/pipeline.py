"""Replay response envelopes without network access or implicit context joins."""

from collections import Counter, defaultdict
from pathlib import Path

from .coverage import inspect_pages
from .normalize import aggregate, mapping, normalize_match, positive_id
from .storage import DataError, atomic_json, digest, read_json


def prepare_snapshot(item, source_file):
    if (not isinstance(item, dict) or not isinstance(item.get("endpoint"), str)
            or "body" not in item or not isinstance(item.get("parameters", {}), dict)):
        raise DataError("invalid_snapshot_envelope")
    if item.get("status") != 200:
        return None
    if "stored_body_sha256" in item and digest(item["body"]) != item["stored_body_sha256"]:
        raise DataError("snapshot_hash_mismatch")
    snapshot_id = digest({k: item.get(k) for k in ("endpoint", "parameters", "scope", "body", "retrieved_utc")})
    return {**item, "snapshot_id": snapshot_id, "source_file": source_file}


def load_snapshots(directory):
    paths = sorted(Path(directory).glob("*.json"))
    if not paths:
        raise DataError("no_response_snapshots")
    return [snapshot for path in paths if (snapshot := prepare_snapshot(read_json(path), path.name)) is not None]


def replay_envelopes(envelopes):
    """Use the same importer for an in-memory, explicitly supplied source."""
    return replay([snapshot for i, item in enumerate(envelopes)
                   if (snapshot := prepare_snapshot(item, f"fictional-{i}.json")) is not None])


def replay(snapshots):
    fixtures, boxes = defaultdict(dict), defaultdict(list)
    fixture_sources = defaultdict(list)
    diagnostics = []
    for item in snapshots:
        endpoint, body = item["endpoint"], item["body"]
        if endpoint.endswith("/matches") and isinstance(body, dict) and isinstance(body.get("data"), list):
            for index, row in enumerate(body["data"]):
                if isinstance(row, dict) and positive_id(row.get("id")):
                    fixtures[row["id"]][digest(row)] = row
                    fixture_sources[row["id"]].append({"snapshot_id": item["snapshot_id"],
                                                       "source_file": item["source_file"],
                                                       "pointer": f"/data/{index}",
                                                       "fixture_sha256": digest(row)})
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
        for row in good + bad:
            row["fixture_provenance"] = sorted(fixture_sources[mid], key=lambda p: (p["snapshot_id"], p["source_file"], p["pointer"]))
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
