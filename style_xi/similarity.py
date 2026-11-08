"""Fixed-reference weighted Euclidean comparison for declared fictional profiles."""

from collections import Counter
import json
import math

from .normalize import PROFILE_IDENTITY, mapping, positive_id
from .storage import DataError, atomic_json, canonical, digest, read_json

LEGACY_FEATURES = (
    ("passes_per_90", "passing", "Recorded passes per 90 player minutes"),
    ("dribbles_per_90", "dribbling", "Recorded dribble attempts per 90 player minutes"),
    ("tackles_per_90", "defending", "Recorded tackles per 90 player minutes"),
    ("shots_per_90", "shooting", "Provider-total shots per 90 player minutes"),
)
FEATURES = (
    LEGACY_FEATURES[0], LEGACY_FEATURES[1],
    ("duels_per_90", "duels", "Provider-recorded duel contests per 90 recorded player minutes; no cross-supplier equivalence established"),
    ("shots_per_90", "shooting", "On-target plus off-target player shots excluding blocked attempts per 90 recorded player minutes"),
)
METHOD_VERSION = 2
LABELS = {"passes_per_90": "Passes", "dribbles_per_90": "Dribbles",
          "duels_per_90": "Provider-recorded duels", "shots_per_90": "Shots excluding blocks"}
EFFICIENCY = ("passes_success_pct", "dribbles_success_pct", "duels_success_pct")
UNIT = "actions_per_90_minutes"
CONSTANT_RELATIVE_TOLERANCE = 1e-12
LIMITATIONS = [
    "Fictional example only; lower distance means closer recorded activity patterns, not player ability.",
    "Tiny artificial reference; population scaling is sensitive to outliers and the chosen reference.",
    "Features, equal family weights and exposure thresholds are demonstration choices, not football-validated policies.",
    "Incomplete samples, role, team context and opportunity remain relevant; standardization does not remove them.",
    "Real positions and cross-competition comparability remain unvalidated; no real-player recommendations are established.",
]


def method_features(method_version=METHOD_VERSION):
    if type(method_version) is not int or method_version not in (1, 2):
        raise DataError("unsupported_comparison_method_version")
    return LEGACY_FEATURES if method_version == 1 else FEATURES


def feature_contract(method_version=METHOD_VERSION):
    contract = [{"key": key, "family": family, "unit": UNIT, "definition": definition, "weight": 0.25}
                for key, family, definition in method_features(method_version)]
    if method_version == 2:
        for feature in contract:
            feature["label"] = LABELS[feature["key"]]
    return contract


def identity(value):
    if not isinstance(value, dict) or set(value) != set(PROFILE_IDENTITY):
        raise DataError("selector_requires_full_profile_identity")
    if (not isinstance(value["provider"], str) or not value["provider"]
            or not all(positive_id(value[k]) for k in ("competition_id", "team_id", "player_id"))
            or type(value["season"]) is not int or value["stage"] not in ("regular", "playoff")):
        raise DataError("invalid_profile_selector")
    return tuple(value[k] for k in PROFILE_IDENTITY)


def selector(profile):
    return {key: profile[key] for key in PROFILE_IDENTITY}


def parse_selector(text):
    """provider/competition/season/stage/club/player; names are never selectors."""
    try:
        provider, competition, season, stage, team, player = text.split("/")
        result = dict(zip(PROFILE_IDENTITY, (provider, int(competition), int(season), stage, int(team), int(player))))
        identity(result)
        return result
    except (AttributeError, ValueError):
        raise DataError("query_requires_provider_competition_season_stage_club_player") from None


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _settings(min_minutes, min_appearances):
    if not _number(min_minutes) or min_minutes <= 0 or type(min_appearances) is not int or min_appearances <= 0:
        raise DataError("invalid_exposure_settings")
    return {"min_minutes": min_minutes, "min_appearances": min_appearances}


def _cohort(cohort):
    if (not isinstance(cohort, dict) or cohort.get("schema_version") != 1 or cohort.get("fictional") is not True
            or not isinstance(cohort.get("name"), str) or not cohort["name"].strip()
            or not isinstance(cohort.get("role_group"), str) or not cohort["role_group"].strip()):
        raise DataError("declared_fictional_cohort_required")
    if set(cohort) - {"schema_version", "fictional", "name", "scope", "role_group", "role_player_ids", "reference", "candidates"}:
        raise DataError("unsupported_cohort_fields")
    scope = cohort.get("scope")
    if (not isinstance(scope, dict) or set(scope) != set(PROFILE_IDENTITY[:4])
            or not isinstance(scope.get("provider"), str) or not scope["provider"]
            or not positive_id(scope.get("competition_id")) or type(scope.get("season")) is not int
            or scope.get("stage") != "regular"):
        raise DataError("one_regular_competition_season_scope_required")
    roles = cohort.get("role_player_ids")
    if (not isinstance(roles, list) or not roles or not all(positive_id(p) for p in roles)
            or len(set(roles)) != len(roles)):
        raise DataError("explicit_unique_fictional_role_members_required")
    return {"name": cohort["name"], "fictional": True, "scope": scope,
            "role_group": cohort["role_group"], "role_player_ids": sorted(roles)}


def _index(document):
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or document.get("kind") != "accepted_match_sample_profiles"
            or document.get("metric_contract_version") != 1 or not isinstance(document.get("profiles"), list)):
        raise DataError("unsupported_comparison_profile_schema")
    result = {}
    for profile in document["profiles"]:
        try:
            key = identity(selector(profile))
        except (KeyError, TypeError):
            raise DataError("invalid_profile_identity") from None
        if key in result:
            raise DataError("duplicate_full_profile_identity")
        result[key] = profile
    return result


def _selectors(values):
    if not isinstance(values, list):
        raise DataError("explicit_identity_list_required")
    keyed = {identity(value): value for value in values}
    if len(keyed) != len(values):
        raise DataError("duplicate_declared_profile_identity")
    return [keyed[k] for k in sorted(keyed)]


def eligibility(profile, cohort, settings, method_version=METHOD_VERSION):
    """All original required features remain mandatory, including inactive ones."""
    reasons = []
    if any(profile[k] != value for k, value in cohort["scope"].items()):
        reasons.append("outside_cohort_scope")
    if profile["player_id"] not in cohort["role_player_ids"]:
        reasons.append("outside_declared_role_group")
    minutes, appearances = profile.get("accepted_minutes"), profile.get("accepted_appearances")
    minutes_valid = _number(minutes) and minutes > 0
    appearances_valid = type(appearances) is int and appearances > 0
    if not minutes_valid:
        reasons.append("invalid_or_missing_minutes")
    elif minutes < settings["min_minutes"]:
        reasons.append("below_min_minutes")
    if not appearances_valid:
        reasons.append("invalid_or_missing_appearances")
    elif appearances < settings["min_appearances"]:
        reasons.append("below_min_appearances")
    matches = profile.get("contributing_match_ids")
    if (not isinstance(matches, list) or not all(positive_id(m) for m in matches)
            or len(set(matches)) != len(matches) or len(matches) != appearances):
        reasons.append("inconsistent_exposure_metadata")
    context = profile.get("coverage", {})
    if isinstance(context, dict) and (type(context.get("accepted_player_matches", appearances)) is not int
                                      or context.get("accepted_player_matches", appearances) != appearances):
        reasons.append("inconsistent_exposure_metadata")
    metrics = profile.get("metrics", {})
    metrics = metrics if isinstance(metrics, dict) else {}
    for key, _, _ in method_features(method_version):
        metric = metrics.get(key)
        if not isinstance(metric, dict) or metric.get("value") is None:
            reasons.append("missing_feature:" + key)
            continue
        if not _number(metric["value"]) or metric.get("unit") != UNIT:
            reasons.append("invalid_feature:" + key)
        if metric.get("reason") is not None or metric.get("issues") != []:
            reasons.append("feature_marked_unavailable:" + key)
        coverage = metric.get("coverage", {})
        if not isinstance(coverage, dict) or coverage.get("inputs_complete") is not True:
            reasons.append("incomplete_feature_inputs:" + key)
            continue
        if (any(type(coverage.get(field)) is not int or coverage[field] != appearances
                for field in ("eligible_appearances", "observed_appearances"))
                or not minutes_valid or not all(_number(coverage.get(field)) and
                                               math.isclose(coverage[field], minutes, rel_tol=1e-12, abs_tol=0)
                                               for field in ("eligible_minutes", "observed_minutes"))):
            reasons.append("inconsistent_feature_coverage:" + key)
    return sorted(set(reasons))


def _population(values):
    """Scale before squaring to avoid overflow/underflow in raw variances."""
    maximum = max(values)
    if maximum == 0:
        return 0.0, 0.0, False
    scaled = [value / maximum for value in values]
    mean_scaled = math.fsum(scaled) / len(values)
    deviation = math.sqrt(math.fsum((v - mean_scaled) ** 2 for v in scaled) / len(values))
    mean, std = mean_scaled * maximum, deviation * maximum
    active = deviation > CONSTANT_RELATIVE_TOLERANCE
    if not math.isfinite(mean) or not math.isfinite(std) or (active and std == 0):
        raise DataError("unrepresentable_reference_scale")
    return mean, std, active


class ReferenceFit:
    """An in-memory fixed fit. Metadata is plain JSON; no executable serialization."""

    def __init__(self, metadata):
        self._metadata = canonical(metadata)

    @property
    def metadata(self):
        return json.loads(self._metadata)


def fit_reference(document, cohort, min_minutes=90, min_appearances=2, *, method_version=METHOD_VERSION):
    features = method_features(method_version)
    declared = _cohort(cohort)
    settings = _settings(min_minutes, min_appearances)
    index = _index(document)
    references = _selectors(cohort.get("reference"))
    players = [(p["provider"], p["player_id"]) for p in references]
    if len(set(players)) != len(players):
        raise DataError("ambiguous_reference_player_spells")
    eligible, exclusions = [], []
    for requested in references:
        profile = index.get(identity(requested))
        reasons = eligibility(profile, declared, settings, method_version) if profile is not None else ["profile_not_found"]
        if reasons:
            exclusions.append({"identity": requested, "reasons": reasons})
            if method_version == 2:
                exclusions[-1]["eligibility"] = eligibility_details(profile, declared, settings, reasons)
        else:
            eligible.append(profile)
    if len(eligible) < 3:
        raise DataError("at_least_three_eligible_reference_profiles_required")
    statistics = {}
    for key, _, _ in features:
        mean, std, active = _population([float(p["metrics"][key]["value"]) for p in eligible])
        statistics[key] = {"mean": mean, "population_std": std, "active": active}
    active = [key for key, _, _ in features if statistics[key]["active"]]
    if len(active) < 2:
        raise DataError("at_least_two_varying_reference_features_required")
    for key, _, _ in features:
        statistics[key]["weight"] = 1 / len(active) if key in active else 0.0
    reference_data = [{"identity": selector(p), "values": [p["metrics"][key]["value"] for key, _, _ in features]}
                      for p in eligible]
    metadata = {"schema_version": 1, "contract_version": method_version,
                         "method": "population_standardized_weighted_euclidean", "fictional": True,
                         "cohort": declared, "features": feature_contract(method_version), "eligibility": settings,
                         "reference": {"declared_identities": references, "eligible_identities": [selector(p) for p in eligible],
                                       "count": len(eligible), "data_sha256": digest(reference_data),
                                       "sample_contexts": [_context(p) for p in eligible],
                                       "exclusions": exclusions,
                                       "exclusion_reason_counts": dict(sorted(Counter(r for p in exclusions for r in p["reasons"]).items()))},
                         "scaling": statistics, "active_features": active,
                         "inactive_features": [key for key, _, _ in features if key not in active],
                         "constant_policy": {"relative_tolerance": CONSTANT_RELATIVE_TOLERANCE,
                                             "rule": "population_std / reference_max <= tolerance; all-zero is constant",
                                             "weight_policy": "drop globally and renormalize equal remaining family weights once"},
                         "query_may_belong_to_reference": True}
    if method_version == 2:
        metadata.update(threshold_status="provisional_demonstration_only",
                        real_player_rankings_allowed=False, real_integration_allowed=False,
                        match_hold_policy=document.get("match_hold_policy"))
    return ReferenceFit(metadata)


def eligibility_details(profile, cohort, settings, reasons):
    """Visible missing-input and exposure evidence for version 2; no imputation."""
    result = {"eligible": not reasons, "reasons": reasons,
              "thresholds": {**settings, "status": "provisional_demonstration_only"}}
    if profile is None:
        return {**result, "sample": None, "features": None}
    result["sample"] = _context(profile)
    metrics = mapping(profile.get("metrics"))
    input_reasons = eligibility(profile, cohort, settings, 2)
    result["features"] = []
    for feature in feature_contract(2):
        key = feature["key"]
        metric = mapping(metrics.get(key))
        issues = metric.get("issues")
        result["features"].append({"key": key, "label": feature["label"],
            "available": not any(r.endswith(":" + key) for r in input_reasons),
            "reason": metric.get("reason") if metric else "metric_not_present",
            "missing_fields": sorted({str(i["field"]) for i in issues
                                      if isinstance(i, dict) and i.get("reason") == "missing_input" and "field" in i})
                              if isinstance(issues, list) else [],
            "coverage": _safe(metric.get("coverage"))})
    return result


def _safe(value):
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    if type(value) in (int, float) and not _number(value):
        return None
    return value


def _context(profile):
    coverage_keys = ("scope", "full_season_profile", "collected_player_matches", "accepted_player_matches",
                     "excluded_player_matches", "excluded_records", "excluded_match_ids", "exclusion_reason_counts",
                     "provider_listed_total_all_stages", "listed_matches_in_stage", "collected_box_scores_in_stage",
                     "provider_manifest_complete", "independently_expected_matches", "independent_coverage_verified",
                     "manifest_issues", "unattributed_match_diagnostics_total")
    names = mapping(profile.get("display_names"))
    coverage = profile.get("coverage")
    if isinstance(coverage, dict):
        coverage_keys += tuple(k for k in ("held_player_matches", "held_match_ids") if k in coverage)
    return {"identity": selector(profile),
            "display_names": {k: sorted(n for n in names.get(k, []) if isinstance(n, str))
                              if isinstance(names.get(k), list) else [] for k in ("player", "team", "competition")},
            "minutes": profile.get("accepted_minutes") if _number(profile.get("accepted_minutes")) else None,
            "appearances": profile.get("accepted_appearances") if type(profile.get("accepted_appearances")) is int else None,
            "coverage": _safe({k: coverage.get(k) for k in coverage_keys}) if isinstance(coverage, dict) else None}


def _efficiency(profile):
    result = {}
    for key in EFFICIENCY:
        metric = mapping(mapping(profile.get("metrics")).get(key))
        value = metric.get("value")
        available = (_number(value) and value <= 100 and metric.get("unit") == "percent"
                     and metric.get("reason") is None and metric.get("issues") == []
                     and mapping(metric.get("coverage")).get("inputs_complete") is True)
        reason = metric.get("reason")
        reason = reason if reason in ("zero_attempts", "incomplete_or_invalid_inputs", "nonfinite_result", "no_accepted_records") else "unavailable"
        result[key] = {"value": value if available else None, "unit": "percent",
                       "reason": None if available else reason}
    return result


def explain_pair(fit, query, candidate):
    """Pure arithmetic on one fixed fit; signed deltas mean candidate minus query."""
    metadata = fit.metadata
    version = metadata["contract_version"]
    features = method_features(version)
    if eligibility(query, metadata["cohort"], metadata["eligibility"], version) or eligibility(candidate, metadata["cohort"], metadata["eligibility"], version):
        raise DataError("pair_requires_eligible_profiles")
    explanations = []
    try:
        for key, _, _ in features:
            q, c = (float(p["metrics"][key]["value"]) for p in (query, candidate))
            scale = metadata["scaling"][key]
            delta = c - q
            standardized = ((c - scale["mean"]) / scale["population_std"]
                            - (q - scale["mean"]) / scale["population_std"]) if scale["active"] else None
            contribution = scale["weight"] * standardized ** 2 if scale["active"] else 0.0
            if not all(math.isfinite(v) for v in (q, c, delta, contribution)) or (standardized is not None and not math.isfinite(standardized)):
                raise OverflowError()
            explanations.append({"key": key, "query_value": q, "candidate_value": c,
                                 "raw_delta": delta, "standardized_delta": standardized,
                                 "weight": scale["weight"], "squared_distance_contribution": contribution,
                                 "active": scale["active"]})
        squared = math.fsum(e["squared_distance_contribution"] for e in explanations)
        distance = math.sqrt(squared)
        if not math.isfinite(distance):
            raise OverflowError()
    except (OverflowError, ZeroDivisionError):
        raise DataError("nonfinite_comparison_arithmetic") from None
    active = [e for e in explanations if e["active"]]
    order = {key: i for i, (key, _, _) in enumerate(features)}
    closest = sorted(active, key=lambda e: (e["squared_distance_contribution"], order[e["key"]]))[:2]
    largest = sorted(active, key=lambda e: (-e["squared_distance_contribution"], order[e["key"]]))[:2]
    return {"candidate": _context(candidate), "distance": distance, "display_distance": round(distance, 4),
            "distance_squared": squared, "features": explanations,
            "closest_measured_gaps": [e["key"] for e in closest],
            "largest_measured_gaps": [e["key"] for e in largest],
            "inactive_feature_differences": [e["key"] for e in explanations if not e["active"] and e["raw_delta"] != 0],
            "efficiency_context_only": {"query": _efficiency(query), "candidate": _efficiency(candidate)}}


def rank_candidates(fit, document, query_identity, candidates, limit=5):
    if type(limit) is not int or limit <= 0:
        raise DataError("positive_integer_neighbour_limit_required")
    metadata, index = fit.metadata, _index(document)
    version = metadata["contract_version"]
    query = index.get(identity(query_identity))
    if query is None:
        raise DataError("query_profile_not_found")
    requested = _selectors(candidates)
    reasons = eligibility(query, metadata["cohort"], metadata["eligibility"], version)
    result = {"schema_version": 1, "kind": "fictional_activity_neighbours", "fictional": True,
              "status": "ineligible_query" if reasons else "ok", "fit": metadata, "query": _context(query),
              "query_exclusion_reasons": reasons, "requested_neighbours": limit, "returned_neighbours": 0,
              "eligible_candidates": 0, "candidate_evaluation_run": not reasons,
              "candidate_exclusions": [], "exclusion_reason_counts": {}, "neighbours": [],
              "distance_meaning": "Lower distance = closer recorded activity patterns; not player ability.",
              "limitations": LIMITATIONS.copy()}
    if version == 2:
        result["query_eligibility"] = eligibility_details(query, metadata["cohort"], metadata["eligibility"], reasons)
        result["candidate_eligibility"] = []
    if reasons:
        return result
    neighbours, exclusions = [], []
    for selected in requested:
        candidate = index.get(identity(selected))
        if (selected["provider"], selected["player_id"]) == (query["provider"], query["player_id"]):
            rejected = ["same_player"]
        else:
            rejected = eligibility(candidate, metadata["cohort"], metadata["eligibility"], version) if candidate is not None else ["profile_not_found"]
        if version == 2:
            result["candidate_eligibility"].append({"identity": selected,
                **eligibility_details(candidate, metadata["cohort"], metadata["eligibility"], rejected)})
        if rejected:
            exclusions.append({"identity": selected, "reasons": rejected})
        else:
            neighbours.append(explain_pair(fit, query, candidate))
    neighbours.sort(key=lambda n: (n["distance"], identity(n["candidate"]["identity"])))
    result.update(eligible_candidates=len(neighbours), neighbours=neighbours[:limit],
                  returned_neighbours=min(limit, len(neighbours)), candidate_exclusions=exclusions,
                  exclusion_reason_counts=dict(sorted(Counter(r for e in exclusions for r in e["reasons"]).items())))
    if not neighbours:
        result["status"] = "no_eligible_candidates"
    return result


def compare_file(input_file, cohort_file, query, output, min_minutes=90, min_appearances=2, limit=5,
                 *, method_version=METHOD_VERSION):
    document, cohort = read_json(input_file), read_json(cohort_file)
    fit = fit_reference(document, cohort, min_minutes, min_appearances, method_version=method_version)
    result = rank_candidates(fit, document, query, cohort.get("candidates"), limit)
    atomic_json(output, result)
    return result


def readable_comparison(result):
    q = result["query"]
    def coverage_text(context):
        coverage = mapping(context.get("coverage"))
        return (f"accepted/collected player matches={coverage.get('accepted_player_matches')}/{coverage.get('collected_player_matches')}; "
                f"exclusions={coverage.get('excluded_records')}; provider manifest complete={coverage.get('provider_manifest_complete')}; "
                f"independent coverage={coverage.get('independent_coverage_verified')}")
    lines = ["Fictional activity comparison. Lower distance = closer recorded activity patterns; not player ability.",
             f"Query {q['identity']}; minutes={q['minutes']}, appearances={q['appearances']}.",
             "Query coverage: " + coverage_text(q),
             f"Reference profiles={result['fit']['reference']['count']}; active={result['fit']['active_features']}; inactive={result['fit']['inactive_features']}."]
    labels = {f["key"]: f.get("label", f["key"]) for f in result["fit"]["features"]}
    if result["fit"]["contract_version"] == 2:
        lines.append(f"Method version 2; provisional exposure settings: {result['fit']['eligibility']}.")
    if result["status"] == "ineligible_query":
        lines.append("Query ineligible; no ranking: " + ", ".join(result["query_exclusion_reasons"]))
    for n in result["neighbours"]:
        p = n["candidate"]
        names = p["display_names"].get("player", [])
        lines.append(f"{' / '.join(names) or p['identity']['player_id']} {p['identity']}: distance={n['display_distance']:.4f}; minutes={p['minutes']}, appearances={p['appearances']}")
        lines.append("  Coverage: " + coverage_text(p))
        for feature in n["features"]:
            z = feature["standardized_delta"]
            lines.append(f"  {labels[feature['key']]}: q={feature['query_value']:g}, c={feature['candidate_value']:g}, delta={feature['raw_delta']:g}, z_delta={z if z is None else round(z, 4)}, weight={feature['weight']:.4f}, squared contribution={feature['squared_distance_contribution']:.6f}")
        lines.append("  Closest measured gaps: " + ", ".join(n["closest_measured_gaps"]) + "; largest: " + ", ".join(n["largest_measured_gaps"]))
        if n["inactive_feature_differences"]:
            lines.append("  Ignored constant features differ in raw values: " + ", ".join(n["inactive_feature_differences"]))
    lines.append(f"Returned {result['returned_neighbours']}/{result['requested_neighbours']} requested; candidate exclusions: {result['exclusion_reason_counts']}")
    for item in result.get("candidate_eligibility", []):
        if not item["eligible"]:
            sample = item["sample"] or {}
            missing = {f["key"]: f["missing_fields"] for f in item["features"] or [] if f["missing_fields"]}
            lines.append(f"Excluded {item['identity']}: {item['reasons']}; "
                         f"minutes={sample.get('minutes')}, appearances={sample.get('appearances')}; "
                         f"missing fields={missing}; thresholds provisional.")
    return "\n".join(lines)
