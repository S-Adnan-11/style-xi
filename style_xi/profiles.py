"""Explainable profiles of accepted recorded matches, with strict field coverage."""

from collections import Counter, defaultdict
import math

from .normalize import (CORE, PROFILE_IDENTITY, aggregate, display_name, mapping,
                        positive_id, valid_count, valid_minutes)
from .storage import DataError, atomic_json, digest, read_json

# Stable keys and source inputs. No generic numeric-field discovery is used.
FAMILIES = (
    ("passes", "passesTotal", "passesSuccessful", "passesFailed"),
    ("key_passes", "passesKey", None, None),
    ("dribbles", "dribblesTotal", "dribblesSuccessful", "dribblesFailed"),
    ("duels", "duelsTotal", "duelsWon", "duelsLost"),
    ("tackles", "tacklesTotal", None, None),
    ("interceptions", "interceptionsTotal", None, None),
    ("shots", "shotsTotal", "shotsOnTarget", "shotsOffTarget"),
)


def source_field_semantics():
    """Version 1 source scope; provider statements do not establish accuracy."""
    return {
        "shotsTotal": {"status": "provider_confirmed_scope",
                       "scope": "Player on-target plus off-target shots, excluding blocked attempts.",
                       "limitations": "No player blocked counter; woodwork is described as off target. Team Shots accuracy includes blocks in its denominator and is a separate measure."},
        "passesTotal": {"status": "provider_confirmed_identity_definition_unpublished",
                        "scope": "passesSuccessful + passesFailed",
                        "limitations": "Pass event inclusion, including restarts, is unpublished; cross-supplier equivalence is unestablished."},
        "tacklesTotal": {"status": "operational_definition_unpublished",
                         "scope": "Provider-recorded tackle count, with no won/lost split.",
                         "limitations": "Neither attempted nor successful tackles is established; real similarity use requires method review."},
        "duelsTotal": {"status": "provider_confirmed_counting_model",
                       "scope": "One contest recorded against both players with exactly one winner.",
                       "limitations": "Team sums require complete player rows; other suppliers' duel models may differ."},
        "minutesPlayed": {"status": "provider_confirmed_mixed_convention_edges_unresolved",
                          "scope": "Nonnegative integer recorded minutes, retained unchanged as the per-90 denominator.",
                          "limitations": "Full-match starters receive 90 (120 with extra time); final substitutes may receive second-half added time. This is not uniform elapsed exposure. Short cameos may be materially affected; no correction or eligibility threshold is established. Clock edge cases remain unresolved."},
    }


def metric_contract():
    """Return a fresh, ordered contract for the 17 supported metrics."""
    specs = {}
    for name, total, success, failure in FAMILIES:
        fields = [total, success, failure] if success else [total]
        relation = [total, success, failure] if success else None
        for suffix, kind, unit in (("total", "count", "count"), ("per_90", "per90", "actions_per_90_minutes")):
            specs[f"{name}_{suffix}"] = {"kind": kind, "unit": unit, "count_field": total,
                                        "required_fields": fields + (["minutes"] if kind == "per90" else []),
                                        "relation": relation}
        if name in ("passes", "dribbles", "duels"):
            specs[f"{name}_success_pct"] = {"kind": "success_pct", "unit": "percent",
                                            "success_field": success, "attempt_field": total,
                                            "required_fields": fields, "relation": relation}
    semantics = source_field_semantics()
    for spec in specs.values():
        field = spec.get("count_field", spec.get("attempt_field"))
        if field in semantics:
            spec["source_semantics"] = dict(semantics[field])
    return specs


def _identity(row):
    key = tuple(row.get(k) for k in PROFILE_IDENTITY)
    if (not isinstance(key[0], str) or not key[0]
            or not all(positive_id(row.get(k)) for k in ("competition_id", "team_id", "player_id"))
            or type(row.get("season")) is not int or row.get("stage") not in ("regular", "playoff")
            or not positive_id(row.get("match_id"))):
        raise DataError("invalid_profile_record_identity")
    return key


def _fingerprint(row):
    counts = mapping(row.get("counts"))
    def state(value, validator):
        return value if validator(value) else None if value is None else "invalid_input"
    return digest({"minutes": state(row.get("minutes"), valid_minutes),
                   "counts": {k: state(counts.get(k), valid_count) for k in CORE}})


def calculate_metric(rows, totals, spec):
    """Evaluate one contract entry. Partial totals never become published metrics."""
    issues, observed = [], []
    for row in rows:
        counts = mapping(row.get("counts"))
        row_issues = []
        for field in spec["required_fields"]:
            value = row.get("minutes") if field == "minutes" else counts.get(field)
            valid = valid_minutes(value) if field == "minutes" else valid_count(value)
            if not valid:
                row_issues.append({"match_id": row["match_id"], "field": field,
                                   "reason": "missing_input" if value is None else "invalid_input"})
        relation = spec["relation"]
        if relation and all(valid_count(counts.get(k)) for k in relation):
            total, success, failure = (counts[k] for k in relation)
            if success + failure != total:
                row_issues.append({"match_id": row["match_id"], "field": relation[0], "reason": "inconsistent_counts"})
        issues.extend(row_issues)
        if not row_issues:
            observed.append(row)
    observed_minutes = (sum(r["minutes"] for r in observed)
                        if all(valid_minutes(r.get("minutes")) for r in observed) else None)
    if observed_minutes is not None and not valid_minutes(observed_minutes):
        observed_minutes = None
    result = {"value": None, "unit": spec["unit"], "reason": None,
              "coverage": {"eligible_appearances": len(rows), "observed_appearances": len(observed),
                           "eligible_minutes": totals["minutes"], "observed_minutes": observed_minutes,
                           "inputs_complete": not issues},
              "issues": sorted(issues, key=lambda i: (i["match_id"], i["field"], i["reason"]))}
    if issues:
        result["reason"] = "incomplete_or_invalid_inputs"
        return result
    if not rows:
        result["reason"] = "no_accepted_records"
        return result
    try:
        if spec["kind"] == "count":
            value = totals["counts"][spec["count_field"]]
        elif spec["kind"] == "per90":
            if totals["minutes"] is None:
                result["reason"] = "nonfinite_result"
                return result
            if totals["minutes"] == 0:
                result["reason"] = "zero_minutes"
                return result
            value = 90 * totals["counts"][spec["count_field"]] / totals["minutes"]
        else:
            attempts = totals["counts"][spec["attempt_field"]]
            if attempts == 0:
                result["reason"] = "zero_attempts"
                return result
            value = 100 * totals["counts"][spec["success_field"]] / attempts
        if type(value) is float and not math.isfinite(value):
            raise OverflowError()
        result["value"] = value
    except (OverflowError, ZeroDivisionError):
        result["reason"] = "nonfinite_result"
    return result


def _coverage(document, key, rows, excluded):
    provider, competition, season, stage, _, _ = key
    accepted_ids = {r["match_id"] for r in rows}
    excluded_ids = {r["match_id"] for r in excluded if positive_id(r.get("match_id"))}
    groups = [g for g in document.get("coverage", []) if provider == "highlightly"
              and g.get("competition_id") == competition and g.get("season") == season]
    if len(groups) > 1:
        raise DataError("ambiguous_profile_manifest_context")
    manifest = groups[0] if groups else {}
    known = bool(groups)
    stages = [m for m in manifest.get("matches", []) if m.get("stage") == stage]
    return {"scope": "accepted_recorded_matches", "full_season_profile": False,
            "collected_player_matches": len(accepted_ids | excluded_ids),
            "accepted_player_matches": len(accepted_ids), "excluded_player_matches": len(excluded_ids),
            "excluded_records": len(excluded), "excluded_match_ids": sorted(excluded_ids),
            "exclusion_reason_counts": dict(sorted(Counter(reason for r in excluded for reason in r.get("reasons", [])).items())),
            "provider_listed_total_all_stages": manifest.get("provider_listed_total"),
            "listed_matches_in_stage": len(stages) if known else None,
            "collected_box_scores_in_stage": sum(m.get("box_score_acquired") is True for m in stages) if known else None,
            "provider_manifest_complete": manifest.get("provider_manifest_complete"),
            "independently_expected_matches": manifest.get("independently_expected_matches"),
            "independent_coverage_verified": manifest.get("independent_coverage_verified"),
            "manifest_issues": sorted(manifest.get("issues", [])) if known else ["manifest_unavailable"],
            "unattributed_match_diagnostics_total": len(document.get("match_diagnostics", []))}


def build_profiles(document):
    """Build a standalone versioned profile document from an import result.

    The importer's acceptance policy remains authoritative. Defensively missing or
    invalid metric fields at this boundary produce unavailable metrics, never zeros.
    """
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or not isinstance(document.get("player_matches"), list)):
        raise DataError("unsupported_profile_input_schema")
    groups, originals, exclusions = defaultdict(dict), defaultdict(list), defaultdict(list)
    for row in document["player_matches"]:
        if not isinstance(row, dict) or row.get("status") != "accepted":
            raise DataError("profile_input_requires_accepted_records")
        key = _identity(row)
        mid = row["match_id"]
        prior = groups[key].get(mid)
        if prior is not None and _fingerprint(prior) != _fingerprint(row):
            raise DataError("conflicting_profile_player_match_records")
        groups[key][mid] = row
        originals[key].append(row)
    for row in document.get("excluded_records", []):
        try:
            key = _identity(row)
        except (DataError, AttributeError):
            continue  # Unattributable exclusions remain in the import result.
        exclusions[key].append(row)
    profiles = []
    contract = metric_contract()
    for key in sorted(groups):
        rows = [groups[key][mid] for mid in sorted(groups[key])]
        totals = aggregate(rows)[0]
        names = {}
        for entity in ("player", "team", "competition"):
            names[entity] = sorted({value for row in originals[key] + exclusions[key]
                                    if (value := display_name(row.get(entity + "_name"))) is not None})
        profiles.append({**dict(zip(PROFILE_IDENTITY, key)), "display_names": names,
                         "scope": "accepted_recorded_matches_incomplete_sample",
                         "accepted_minutes": totals["minutes"], "accepted_appearances": len(rows),
                         "contributing_match_ids": totals["contributing_matches"],
                         "source_snapshot_ids": sorted({p["snapshot_id"] for r in originals[key] for p in r.get("provenance", [])}),
                         "coverage": _coverage(document, key, rows, exclusions[key]),
                         "metrics": {name: calculate_metric(rows, totals, spec) for name, spec in contract.items()}})
    return {"schema_version": 1, "kind": "accepted_match_sample_profiles", "metric_contract_version": 1,
            "scope": "accepted_recorded_matches_incomplete_sample",
            "validation": {"independent_accuracy": "not_established", "full_season_coverage": "not_established"},
            "source_field_semantics_version": 1, "source_field_semantics": source_field_semantics(),
            "metric_contract": contract,
            "summary": {"profiles": len(profiles), "accepted_records": sum(len(g) for g in groups.values()),
                        "excluded_records_in_input": len(document.get("excluded_records", [])),
                        "unattributed_match_diagnostics": len(document.get("match_diagnostics", []))},
            "profiles": profiles}


def profile_file(input_file, output_file):
    result = build_profiles(read_json(input_file))
    atomic_json(output_file, result)
    return result


def readable_summary(document):
    """Round presentation only; structured values retain calculation precision."""
    lines = ["Profiles of accepted recorded matches; incomplete samples.",
             "Per90 = actions per 90 minutes; success = percent. Brackets show valid/eligible accepted rows."]
    for profile in document["profiles"]:
        names = profile["display_names"]
        player = " / ".join(names["player"]) or str(profile["player_id"])
        team = " / ".join(names["team"]) or str(profile["team_id"])
        competition = " / ".join(names["competition"]) or str(profile["competition_id"])
        lines.append(f"{player} | {team} | {competition} / {profile['season']} / {profile['stage']}")
        c = profile["coverage"]
        lines.append(f"  minutes={profile['accepted_minutes']}, accepted appearances={profile['accepted_appearances']}; "
                     f"{c['accepted_player_matches']}/{c['collected_player_matches']} collected player matches accepted, "
                     f"{c['excluded_records']} exclusions; provider manifest complete={c['provider_manifest_complete']}, "
                     f"independent coverage={c['independent_coverage_verified']}")
        def rendered(metric):
            value = metric["value"]
            value = (str(value) if type(value) is int else f"{value:.2f}") if value is not None else f"unavailable ({metric['reason']})"
            cov = metric["coverage"]
            return f"{value} [{cov['observed_appearances']}/{cov['eligible_appearances']}]"
        for family, *_ in FAMILIES:
            metrics = profile["metrics"]
            text = f"  {family}: total={rendered(metrics[family + '_total'])}; per90={rendered(metrics[family + '_per_90'])}"
            if family + "_success_pct" in metrics:
                text += "; success=" + rendered(metrics[family + "_success_pct"])
            lines.append(text)
    return "\n".join(lines)
