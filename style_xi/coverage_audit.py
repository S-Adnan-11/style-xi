"""Offline availability/exposure audit. Never fit, rank, or infer tactical roles."""

from collections import Counter, defaultdict
from statistics import median

from .holds import held_matches
from .normalize import PROFILE_IDENTITY, mapping, stage_for, valid_count, valid_minutes
from .pipeline import replay
from .storage import DataError, digest

AUDIT_FIELDS = ("passesTotal", "passesSuccessful", "passesFailed", "dribblesTotal",
                "dribblesSuccessful", "dribblesFailed", "duelsTotal", "duelsWon", "duelsLost",
                "shotsTotal", "shotsOnTarget", "shotsOffTarget", "tacklesTotal")


def _field_counts(rows):
    result = {}
    for field in AUDIT_FIELDS:
        values = [mapping(row.get("statistics")).get(field) for row in rows]
        missing = sum(value is None for value in values)
        valid = sum(valid_count(value) for value in values)
        result[field] = {"rows": len(rows), "valid": valid, "missing": missing,
                         "invalid": len(rows) - valid - missing, "complete": bool(rows) and valid == len(rows)}
    return result


def _distribution(values):
    return {"count": len(values), "min": min(values) if values else None,
            "median": median(values) if values else None, "max": max(values) if values else None}


def _audit_inputs(snapshots, match_holds):
    """Shared cache replay and hold-first exposure inputs; no profiles or rankings."""
    holds = held_matches(match_holds)
    imported = replay(snapshots)
    fixtures = {}
    for snapshot in snapshots:
        if snapshot["endpoint"].endswith("/matches"):
            for fixture in snapshot["body"]["data"]:
                if fixture["id"] in fixtures and fixtures[fixture["id"]] != fixture:
                    raise DataError("audit_conflicting_fixture_context")
                fixtures[fixture["id"]] = fixture
    groups, seen, source_roles = defaultdict(list), {}, {}
    for snapshot in snapshots:
        if "/box-score/" not in snapshot["endpoint"]:
            continue
        mid = int(snapshot["endpoint"].rsplit("/", 1)[1])
        fingerprint = digest(snapshot["body"])
        if mid in seen:
            if seen[mid] != fingerprint:
                raise DataError("audit_conflicting_box_snapshots")
            continue
        seen[mid] = fingerprint
        if mid not in fixtures:
            raise DataError("audit_missing_fixture_context")
        fixture = fixtures[mid]
        scope = (fixture["league"]["id"], fixture["league"]["season"], stage_for(fixture))
        for team in snapshot["body"]:
            for player in team["players"]:
                stats = player.get("statistics")
                if isinstance(stats, list):
                    stats = stats[0] if len(stats) == 1 else None
                row = {**player, "statistics": stats, "match_id": mid,
                       "held": ("highlightly", mid) in holds}
                groups[scope].append(row)
                role = player.get("position")
                source_roles[(mid, team["team"]["id"], player.get("id"))] = (
                    role.strip() if isinstance(role, str) and role.strip() else None)
    samples = defaultdict(dict)
    for row in imported["player_matches"]:
        if (row["provider"], row["match_id"]) not in holds:
            key = tuple(row[k] for k in PROFILE_IDENTITY)
            samples[key][row["match_id"]] = row
    return holds, imported, groups, samples, source_roles, seen


def audit_coverage(snapshots, *, match_holds=None, min_minutes=90, min_appearances=2):
    """Report source availability and unheld exposure distributions, without profiles."""
    if (not valid_minutes(min_minutes) or min_minutes <= 0
            or type(min_appearances) is not int or min_appearances <= 0):
        raise DataError("invalid_audit_exposure_settings")
    holds, imported, groups, samples, source_roles, seen = _audit_inputs(snapshots, match_holds)
    results = []
    for scope, rows in sorted(groups.items()):
        positive = [r for r in rows if valid_minutes(r.get("minutesPlayed")) and r["minutesPlayed"] > 0]
        unheld = [r for r in positive if not r["held"]]
        selected = [rows for key, rows in samples.items() if key[1:4] == scope]
        minutes = [sum(r["minutes"] for r in matches.values()) for matches in selected]
        appearances = [len(matches) for matches in selected]
        role_sets = [{source_roles.get((r["match_id"], r["team_id"], r["player_id"]))
                      for r in matches.values()} for matches in selected]
        roles = Counter(r["position"].strip() for r in positive
                        if isinstance(r.get("position"), str) and r["position"].strip())
        results.append({"competition_id": scope[0], "season": scope[1], "stage": scope[2],
            "cached_matches": len({r["match_id"] for r in rows}), "source_rows": len(rows),
            "positive_minute_rows": len(positive), "held_source_rows": sum(r["held"] for r in rows),
            "field_availability_all_source_rows": _field_counts(rows),
            "field_availability_positive_minute_rows": _field_counts(positive),
            "field_availability_unheld_positive_minute_rows": _field_counts(unheld),
            "recorded_minutes": {"valid_nonnegative_rows": sum(valid_minutes(r.get("minutesPlayed")) for r in rows),
                "integer_rows": sum(type(r.get("minutesPlayed")) is int and r["minutesPlayed"] >= 0 for r in rows),
                "zero_minute_rows": sum(valid_minutes(r.get("minutesPlayed")) and r["minutesPlayed"] == 0 for r in rows),
                "positive_distribution": _distribution([r["minutesPlayed"] for r in positive]),
                "positive_under_10": sum(r["minutesPlayed"] < 10 for r in positive)},
            "unheld_accepted_sample_exposure": {"player_team_samples": len(selected),
                "minutes": _distribution(minutes), "appearances": _distribution(appearances),
                "appearance_histogram": dict(sorted(Counter(appearances).items())),
                "accepted_player_matches": sum(appearances), "accepted_minutes": sum(minutes),
                "below_provisional_minutes": sum(v < min_minutes for v in minutes),
                "below_provisional_appearances": sum(v < min_appearances for v in appearances),
                "meeting_both_provisional_thresholds": sum(m >= min_minutes and a >= min_appearances
                                                          for m, a in zip(minutes, appearances))},
            "role_coverage": {"source_position_field": "position", "positive_source_role_counts": dict(sorted(roles.items())),
                "positive_source_rows_without_role": len(positive) - sum(roles.values()),
                "unheld_samples_with_role_every_appearance": sum(None not in roles for roles in role_sets),
                "unheld_samples_with_multiple_observed_labels": sum(len(roles - {None}) > 1 for roles in role_sets),
                "tactical_role_cohort_verified": False, "goalkeeper_policy_reviewed": False}})
    return {"schema_version": 1, "kind": "cache_availability_exposure_audit", "provider_requests": 0,
            "input_snapshot_sha256": digest(sorted((s["snapshot_id"], s["source_file"]) for s in snapshots)),
            "hold_registry_sha256": digest(match_holds) if match_holds is not None else None,
            "rankings_computed": False, "real_player_rankings_allowed": False, "real_integration_allowed": False,
            "provisional_thresholds": {"min_minutes": min_minutes, "min_appearances": min_appearances,
                                       "status": "provisional_demonstration_only_not_real_eligibility"},
            "held_matches": [{"provider": p, "match_id": mid} for p, mid in sorted(holds)],
            "cached_matches": len(seen), "source_rows": sum(len(rows) for rows in groups.values()),
            "import_diagnostics": imported["summary"], "groups": results,
            "limitations": ["Availability does not establish accuracy or independently complete lineups/season coverage.",
                "Recorded minutes use mixed conventions; cameo/clock effects and sufficient exposure remain unreviewed.",
                "Source position labels are coverage observations; no tactical roles or goalkeeper eligibility inferred.",
                "Held matches are excluded before counting accepted exposure; no real profiles, fit or rankings produced."]}
