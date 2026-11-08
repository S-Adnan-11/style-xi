"""Hold-first, offline exposure sensitivity study; never compute player rankings."""

from collections import Counter, defaultdict

from .coverage_audit import _audit_inputs
from .normalize import PROFILE_IDENTITY, mapping, valid_count, valid_minutes
from .storage import DataError, digest

MINUTE_GRID = (90, 180, 270, 360, 450)
APPEARANCE_GRID = (1, 2, 3, 4, 5)
POSITIONS = ("Defender", "Forward", "Midfielder", "Goalkeeper")
ROLE_BUCKETS = (*POSITIONS, "mixed", "missing", "other_source_label")
FEATURE_FIELDS = ("passesTotal", "passesSuccessful", "passesFailed", "dribblesTotal",
                  "dribblesSuccessful", "dribblesFailed", "duelsTotal", "duelsWon", "duelsLost",
                  "shotsTotal", "shotsOnTarget", "shotsOffTarget")


def _thresholds(values, *, appearances=False):
    if not isinstance(values, (list, tuple)) or not values:
        raise DataError("invalid_study_threshold_grid")
    if any((type(v) is not int if appearances else not valid_minutes(v)) or v <= 0 for v in values):
        raise DataError("invalid_study_threshold_grid")
    if len(set(values)) != len(values):
        raise DataError("duplicate_study_threshold")
    return sorted(values)


def position_observation(labels):
    """Missing on any appearance takes precedence; preserve observed mixtures too."""
    known = sorted({label for label in labels if label is not None})
    missing = sum(label is None for label in labels)
    status = "missing" if missing else "mixed" if len(known) > 1 else "stable"
    bucket = status if status != "stable" else known[0] if known[0] in POSITIONS else "other_source_label"
    return {"status": status, "bucket": bucket, "labels": known, "missing_appearances": missing,
            "multiple_known_labels": len(known) > 1, "goalkeeper_observed": "Goalkeeper" in known}


def _counts(samples):
    return {state: sum(s["position"]["status"] == state for s in samples) for state in ("stable", "mixed", "missing")}


def _summary(samples, minute_grid, appearance_grid):
    by_role = {role: [s for s in samples if s["position"]["bucket"] == role] for role in ROLE_BUCKETS}
    combinations = Counter(" + ".join(s["position"]["labels"]) or "no_label" for s in samples)
    total_minutes = sum(s["minutes"] for s in samples)
    total_appearances = sum(s["appearances"] for s in samples)
    thresholds = []
    for minutes in minute_grid:
        for appearances in appearance_grid:
            passed = [s for s in samples if s["minutes"] >= minutes and s["appearances"] >= appearances]
            role_rows = []
            for role, population in by_role.items():
                n = sum(s["minutes"] >= minutes and s["appearances"] >= appearances for s in population)
                role_rows.append({"source_position_bucket": role, "denominator": len(population), "meeting_thresholds": n,
                                  "fraction": n / len(population) if population else None})
            thresholds.append({"min_minutes": minutes, "min_appearances": appearances,
                "denominator": len(samples), "meeting_thresholds": len(passed),
                "fraction": len(passed) / len(samples) if samples else None,
                "below_minutes_only": sum(s["minutes"] < minutes and s["appearances"] >= appearances for s in samples),
                "below_appearances_only": sum(s["minutes"] >= minutes and s["appearances"] < appearances for s in samples),
                "below_both": sum(s["minutes"] < minutes and s["appearances"] < appearances for s in samples),
                "retained_recorded_minutes": sum(s["minutes"] for s in passed),
                "retained_appearances": sum(s["appearances"] for s in passed),
                "position_status_counts": _counts(passed),
                "stable_outfield_complete_inputs": sum(s["position"]["status"] == "stable"
                    and s["position"]["bucket"] in POSITIONS[:3] and s["feature_inputs_complete"] for s in passed),
                "goalkeeper_observed": sum(s["position"]["goalkeeper_observed"] for s in passed),
                "by_source_position": role_rows})
    return {"unheld_player_team_samples": len(samples), "recorded_minutes": total_minutes,
            "appearances": total_appearances, "position_status_counts": _counts(samples),
            "position_bucket_counts": {role: len(rows) for role, rows in by_role.items()},
            "observed_label_combinations": dict(sorted(combinations.items())),
            "missing_with_multiple_known_labels": sum(s["position"]["status"] == "missing"
                                                      and s["position"]["multiple_known_labels"] for s in samples),
            "incomplete_feature_input_samples": sum(not s["feature_inputs_complete"] for s in samples),
            "goalkeeper_observed_samples": sum(s["position"]["goalkeeper_observed"] for s in samples),
            "thresholds": thresholds}


def study_eligibility(snapshots, *, match_holds, minute_grid=MINUTE_GRID, appearance_grid=APPEARANCE_GRID):
    """Count coverage of alternative research screens, without real-player eligibility clearance."""
    minutes = _thresholds(minute_grid)
    appearances = _thresholds(appearance_grid, appearances=True)
    holds, imported, groups, samples, roles, seen = _audit_inputs(snapshots, match_holds)
    scopes = defaultdict(list)
    for key, matches in sorted(samples.items()):
        rows = list(matches.values())
        scopes[key[1:4]].append({"minutes": sum(r["minutes"] for r in rows), "appearances": len(rows),
            "position": position_observation([roles.get((r["match_id"], r["team_id"], r["player_id"])) for r in rows]),
            "feature_inputs_complete": all(valid_count(mapping(r.get("counts")).get(f)) for r in rows for f in FEATURE_FIELDS)})
    names = {f["league"]["id"]: f["league"].get("name", str(f["league"]["id"]))
             for s in snapshots if s["endpoint"].endswith("/matches") for f in s["body"]["data"]}
    held_rows = [r for r in imported["player_matches"] if (r["provider"], r["match_id"]) in holds]
    held_keys = {tuple(r[k] for k in PROFILE_IDENTITY) for r in held_rows}
    league_groups = [{"competition_id": scope[0], "league": names[scope[0]], "season": scope[1], "stage": scope[2],
                      **_summary(scopes[scope], minutes, appearances)} for scope in sorted(groups)]
    combined = []
    for season, stage in sorted({(scope[1], scope[2]) for scope in groups}):
        selected = [s for scope, rows in scopes.items() if scope[1:] == (season, stage) for s in rows]
        combined.append({"season": season, "stage": stage, **_summary(selected, minutes, appearances)})
    return {"schema_version": 1, "kind": "private_eligibility_coverage_study", "study_version": 1,
            "provider_requests": 0, "rankings_computed": False, "real_player_rankings_allowed": False,
            "real_integration_allowed": False,
            "input_snapshot_sha256": digest(sorted((s["snapshot_id"], s["source_file"]) for s in snapshots)),
            "hold_registry_sha256": digest(match_holds), "cached_matches": len(seen),
            "held_matches": [{"provider": p, "match_id": mid} for p, mid in sorted(holds)],
            "held_accepted_player_matches": len(held_rows), "held_recorded_minutes": sum(r["minutes"] for r in held_rows),
            "held_only_player_team_samples": len(held_keys - set(samples)),
            "import_summary": imported["summary"],
            "sample_unit": "provider/competition/season/stage/team/player; counts are samples, not unique people",
            "position_rule": "Observed accepted unheld labels only: missing if any label missing, else mixed if multiple, else stable. Stability is observed metadata, not a tactical role.",
            "threshold_grid": {"minutes": minutes, "appearances": appearances, "status": "all_provisional_sensitivity_settings",
                               "baseline": {"min_minutes": 90, "min_appearances": 2, "status": "provisional_demonstration_only"}},
            "leagues": league_groups, "stage_totals": combined,
            "policy_proposal": {"status": "research_proposal_only_not_validated_or_enabled",
                "hold_first": True, "merge_clubs_or_stages": False,
                "mixed_positions": "Retain in a separate observed-mixture bucket; do not assign a majority or tactical role. Exclude from an initial single-label outfield comparison screen.",
                "missing_positions": "Keep exposure visible but exclude from a single-label screen until labels are reviewed; never infer labels from activity.",
                "goalkeepers": "Any observed goalkeeper label, including mixed labels, requires a separate keeper review and feature/cohort contract. Exclude from the outfield screen; do not run a keeper ranking.",
                "threshold_choice": "Keep 90/2 provisional. Use 180/3 only as a candidate research screen, with 270/3 and 360/4 sensitivity and 450/5 sparsity checks. No real threshold is validated by retention counts.",
                "minute_rule": "Retain recorded integer minutes; no correction, nominal clipping or team-minute invariant. Require independent clock/exposure validation and repeat-sample sensitivity before rate eligibility.",
                "activation": "No real-player eligibility, rankings or integration is enabled by this study."}}


def check_minute_cases(snapshots, cases, *, match_holds):
    """Recheck retained case identities and minutes. Prior clock reviews are not elapsed-time truth."""
    holds, _, _, _, _, _ = _audit_inputs(snapshots, match_holds)
    boxes = {int(s["endpoint"].rsplit("/", 1)[1]): s for s in snapshots if "/box-score/" in s["endpoint"]}
    results = []
    for case in cases:
        snapshot = boxes.get(case["match_id"])
        matches = [(team, p) for team in snapshot["body"] for p in team["players"] if p.get("id") == case["player_id"]] if snapshot else []
        row = matches[0][1] if len(matches) == 1 else None
        pinned = mapping(case.get("cache_provenance"))
        body_agrees = snapshot is not None and pinned.get("stored_body_sha256") == digest(snapshot["body"])
        pointer = case.get("source_field")
        pointed, parent = None, None
        try:
            pointed = snapshot
            for part in pointer.strip("/").split("/"):
                parent = pointed
                pointed = pointed[int(part)] if isinstance(pointed, list) else pointed[part]
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            pointed = None
        results.append({"match_id": case["match_id"], "player_id": case["player_id"], "player_name": case.get("player_name"),
            "held": ("highlightly", case["match_id"]) in holds,
            "unique_player_identity_found": row is not None, "pinned_body_matches": body_agrees,
            "recorded_minutes": row.get("minutesPlayed") if row else None, "prior_recorded_minutes": case["provider_minutes"],
            "recorded_value_unchanged": row is not None and row.get("minutesPlayed") == case["provider_minutes"],
            "source_pointer_value_agrees": pointed == case["provider_minutes"], "source_field": pointer,
            "source_pointer_identity_agrees": isinstance(parent, dict) and parent.get("id") == case["player_id"],
            "source_snapshot_id": snapshot["snapshot_id"] if snapshot else None,
            "independent_source_url": case.get("source"), "prior_review_date": case.get("evidence_date"),
            "retained_review_finding": case.get("verdict"), "independent_elapsed_minutes_verified": False})
    return {"cases_checked": len(results), "cases": results,
            "all_retained_provider_values_reproduced": all(c["unique_player_identity_found"] and c["pinned_body_matches"]
                and c["recorded_value_unchanged"] and c["source_pointer_value_agrees"]
                and c["source_pointer_identity_agrees"] for c in results),
            "representative_accuracy_estimate": False, "automatic_minute_corrections": False,
            "limit": "Retained review findings and displayed event clocks are not independently verified elapsed exposure; provider explanations are a separate evidence class."}
