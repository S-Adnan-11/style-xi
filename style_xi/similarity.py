"""Fixed-reference weighted Euclidean comparison for declared fictional profiles."""

from collections import Counter
import json
import math

from .normalize import PROFILE_IDENTITY, mapping, positive_id
from .storage import DataError, atomic_json, canonical, digest, read_json

FEATURES = (
    ("passes_per_90", "passing", "Recorded passes per 90 player minutes"),
    ("dribbles_per_90", "dribbling", "Recorded dribble attempts per 90 player minutes"),
    ("tackles_per_90", "defending", "Recorded tackles per 90 player minutes"),
    ("shots_per_90", "shooting", "Provider-total shots per 90 player minutes"),
)
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


def feature_contract():
    return [{"key": key, "family": family, "unit": UNIT, "definition": definition, "weight": 0.25}
            for key, family, definition in FEATURES]


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


def eligibility(profile, cohort, settings):
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
    for key, _, _ in FEATURES:
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


def fit_reference(document, cohort, min_minutes=90, min_appearances=2):
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
        reasons = eligibility(profile, declared, settings) if profile is not None else ["profile_not_found"]
        if reasons:
            exclusions.append({"identity": requested, "reasons": reasons})
        else:
            eligible.append(profile)
    if len(eligible) < 3:
        raise DataError("at_least_three_eligible_reference_profiles_required")
    statistics = {}
    for key, _, _ in FEATURES:
        mean, std, active = _population([float(p["metrics"][key]["value"]) for p in eligible])
        statistics[key] = {"mean": mean, "population_std": std, "active": active}
    active = [key for key, _, _ in FEATURES if statistics[key]["active"]]
    if len(active) < 2:
        raise DataError("at_least_two_varying_reference_features_required")
    for key, _, _ in FEATURES:
        statistics[key]["weight"] = 1 / len(active) if key in active else 0.0
    reference_data = [{"identity": selector(p), "values": [p["metrics"][key]["value"] for key, _, _ in FEATURES]}
                      for p in eligible]
    return ReferenceFit({"schema_version": 1, "contract_version": 1,
                         "method": "population_standardized_weighted_euclidean", "fictional": True,
                         "cohort": declared, "features": feature_contract(), "eligibility": settings,
                         "reference": {"declared_identities": references, "eligible_identities": [selector(p) for p in eligible],
                                       "count": len(eligible), "data_sha256": digest(reference_data),
                                       "sample_contexts": [_context(p) for p in eligible],
                                       "exclusions": exclusions,
                                       "exclusion_reason_counts": dict(sorted(Counter(r for p in exclusions for r in p["reasons"]).items()))},
                         "scaling": statistics, "active_features": active,
                         "inactive_features": [key for key, _, _ in FEATURES if key not in active],
                         "constant_policy": {"relative_tolerance": CONSTANT_RELATIVE_TOLERANCE,
                                             "rule": "population_std / reference_max <= tolerance; all-zero is constant",
                                             "weight_policy": "drop globally and renormalize equal remaining family weights once"},
                         "query_may_belong_to_reference": True})


def _context(profile):
    def safe(value):
        if isinstance(value, dict):
            return {k: safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [safe(v) for v in value]
        if type(value) in (int, float) and not _number(value):
            return None
        return value
    coverage_keys = ("scope", "full_season_profile", "collected_player_matches", "accepted_player_matches",
                     "excluded_player_matches", "excluded_records", "excluded_match_ids", "exclusion_reason_counts",
                     "provider_listed_total_all_stages", "listed_matches_in_stage", "collected_box_scores_in_stage",
                     "provider_manifest_complete", "independently_expected_matches", "independent_coverage_verified",
                     "manifest_issues", "unattributed_match_diagnostics_total")
    names = mapping(profile.get("display_names"))
    coverage = profile.get("coverage")
    return {"identity": selector(profile),
            "display_names": {k: sorted(n for n in names.get(k, []) if isinstance(n, str))
                              if isinstance(names.get(k), list) else [] for k in ("player", "team", "competition")},
            "minutes": profile.get("accepted_minutes") if _number(profile.get("accepted_minutes")) else None,
            "appearances": profile.get("accepted_appearances") if type(profile.get("accepted_appearances")) is int else None,
            "coverage": safe({k: coverage.get(k) for k in coverage_keys}) if isinstance(coverage, dict) else None}


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
    if eligibility(query, metadata["cohort"], metadata["eligibility"]) or eligibility(candidate, metadata["cohort"], metadata["eligibility"]):
        raise DataError("pair_requires_eligible_profiles")
    explanations = []
    try:
        for key, _, _ in FEATURES:
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
    order = {key: i for i, (key, _, _) in enumerate(FEATURES)}
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
    query = index.get(identity(query_identity))
    if query is None:
        raise DataError("query_profile_not_found")
    requested = _selectors(candidates)
    reasons = eligibility(query, metadata["cohort"], metadata["eligibility"])
    result = {"schema_version": 1, "kind": "fictional_activity_neighbours", "fictional": True,
              "status": "ineligible_query" if reasons else "ok", "fit": metadata, "query": _context(query),
              "query_exclusion_reasons": reasons, "requested_neighbours": limit, "returned_neighbours": 0,
              "eligible_candidates": 0, "candidate_evaluation_run": not reasons,
              "candidate_exclusions": [], "exclusion_reason_counts": {}, "neighbours": [],
              "distance_meaning": "Lower distance = closer recorded activity patterns; not player ability.",
              "limitations": LIMITATIONS.copy()}
    if reasons:
        return result
    neighbours, exclusions = [], []
    for selected in requested:
        candidate = index.get(identity(selected))
        if (selected["provider"], selected["player_id"]) == (query["provider"], query["player_id"]):
            rejected = ["same_player"]
        else:
            rejected = eligibility(candidate, metadata["cohort"], metadata["eligibility"]) if candidate is not None else ["profile_not_found"]
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


def compare_file(input_file, cohort_file, query, output, min_minutes=90, min_appearances=2, limit=5):
    document, cohort = read_json(input_file), read_json(cohort_file)
    fit = fit_reference(document, cohort, min_minutes, min_appearances)
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
    if result["status"] == "ineligible_query":
        lines.append("Query ineligible; no ranking: " + ", ".join(result["query_exclusion_reasons"]))
    for n in result["neighbours"]:
        p = n["candidate"]
        names = p["display_names"].get("player", [])
        lines.append(f"{' / '.join(names) or p['identity']['player_id']} {p['identity']}: distance={n['display_distance']:.4f}; minutes={p['minutes']}, appearances={p['appearances']}")
        lines.append("  Coverage: " + coverage_text(p))
        for feature in n["features"]:
            z = feature["standardized_delta"]
            lines.append(f"  {feature['key']}: q={feature['query_value']:g}, c={feature['candidate_value']:g}, delta={feature['raw_delta']:g}, z_delta={z if z is None else round(z, 4)}, weight={feature['weight']:.4f}, squared contribution={feature['squared_distance_contribution']:.6f}")
        lines.append("  Closest measured gaps: " + ", ".join(n["closest_measured_gaps"]) + "; largest: " + ", ".join(n["largest_measured_gaps"]))
        if n["inactive_feature_differences"]:
            lines.append("  Ignored constant features differ in raw values: " + ", ".join(n["inactive_feature_differences"]))
    lines.append(f"Returned {result['returned_neighbours']}/{result['requested_neighbours']} requested; candidate exclusions: {result['exclusion_reason_counts']}")
    return "\n".join(lines)
