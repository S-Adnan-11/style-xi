"""Offline, fictional-only window stability using the existing v2 profile rates."""

from datetime import date
from statistics import mean

from .holds import held_matches
from .normalize import PROFILE_IDENTITY, positive_id
from .profiles import build_profiles
from .similarity import eligibility, feature_contract, identity, selector
from .storage import DataError, digest


def _date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except (TypeError, ValueError):
        pass
    raise DataError("stability_requires_iso_calendar_date")


def _calendar(entries, holds):
    if not isinstance(entries, list):
        raise DataError("stability_requires_explicit_match_calendar")
    result = {}
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("provider"), str)
                or not entry["provider"] or not positive_id(entry.get("match_id"))):
            raise DataError("invalid_stability_calendar_identity")
        key = (entry["provider"], entry["match_id"])
        if key in holds:
            continue  # Held matches need no usable date and cannot affect the split.
        if key in result:
            raise DataError("duplicate_stability_match_date")
        result[key] = _date(entry.get("date"))
    return result


def _window(profile, features, screen):
    if profile is None:
        return {"recorded_minutes": 0, "appearances": 0, "match_ids": [],
                "qualifies": False, "reasons": ["below_min_appearances", "below_min_minutes"],
                "features": {f["key"]: {"value": None, "unit": f["unit"],
                                        "reason": "no_accepted_records", "issues": [],
                                        "coverage": {"eligible_appearances": 0, "observed_appearances": 0,
                                                     "eligible_minutes": 0, "observed_minutes": 0,
                                                     "inputs_complete": True}} for f in features}}
    # Reuse the comparison's exposure/coverage/input checks. Each sample already
    # has its own full identity; this does not infer roles or declare a real cohort.
    scope = {k: profile[k] for k in PROFILE_IDENTITY[:4]}
    reasons = eligibility(profile, {"scope": scope, "role_player_ids": [profile["player_id"]]},
                          screen, method_version=2)
    return {"recorded_minutes": profile["accepted_minutes"],
            "appearances": profile["accepted_appearances"],
            "match_ids": profile["contributing_match_ids"],
            "qualifies": not reasons, "reasons": reasons,
            "features": {f["key"]: profile["metrics"][f["key"]] for f in features}}


def _changes(values):
    if not values:
        return {"samples": 0, "min": None, "mean": None, "median": None, "max": None}
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (ordered[middle] if len(ordered) % 2 else
              ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) / 2)
    return {"samples": len(values), "min": ordered[0], "mean": mean(values),
            "median": median, "max": ordered[-1]}


def check_stability(document, *, match_dates, cutoff, fictional=False, match_holds=None):
    """Compare earlier (< cutoff) and later (>= cutoff) accepted match samples.

    Dates are explicit YYYY-MM-DD calendar dates keyed by provider and match ID.
    Each full player-team identity stays within its competition, season and stage.
    Both windows must independently pass 180 recorded minutes, three appearances
    and the existing v2 complete-feature checks before any changes are reported.
    The fictional declaration is required before building any player profiles.
    """
    if fictional is not True:
        raise DataError("declared_fictional_stability_input_required")
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or not isinstance(document.get("player_matches"), list)):
        raise DataError("unsupported_stability_input_schema")
    boundary = _date(cutoff)
    holds = held_matches(match_holds)
    calendar = _calendar(match_dates, holds)
    rows = {"earlier": [], "later": []}
    samples, held_rows, unheld_samples = {}, set(), set()
    for row in document["player_matches"]:
        if not isinstance(row, dict) or row.get("status") != "accepted":
            raise DataError("stability_requires_accepted_records")
        try:
            requested = selector(row)
            key = identity(requested)
        except (KeyError, TypeError):
            raise DataError("invalid_stability_record_identity") from None
        if not positive_id(row.get("match_id")):
            raise DataError("invalid_stability_record_identity")
        samples[key] = requested
        match = (row["provider"], row["match_id"])
        if match in holds:
            held_rows.add((*key, row["match_id"]))
            continue  # Holds precede date lookup, exposure and every rate denominator.
        if match not in calendar:
            raise DataError("missing_stability_match_date")
        window = "earlier" if calendar[match] < boundary else "later"
        rows[window].append(row)
        unheld_samples.add(key)

    features = [{k: v for k, v in f.items() if k != "weight"} for f in feature_contract(2)]
    screen = {"min_minutes": 180, "min_appearances": 3}
    profiles = {}
    for window, accepted in rows.items():
        # Only accepted, unheld rows have dates in this study. Unaccepted evidence
        # remains in the source import and cannot be assigned to either window.
        built = build_profiles({**document, "player_matches": accepted, "excluded_records": []})
        profiles[window] = {identity(selector(p)): p for p in built["profiles"]}
    results = []
    for key, requested in sorted(samples.items()):
        windows = {w: _window(profiles[w].get(key), features, screen) for w in rows}
        failed = [w for w in windows if not windows[w]["qualifies"]]
        results.append({"identity": requested, "windows": windows,
                        "qualifies": not failed, "failed_windows": failed,
                        "absolute_changes": {f["key"]: abs(windows["later"]["features"][f["key"]]["value"] -
                                                            windows["earlier"]["features"][f["key"]]["value"])
                                             if not failed else None for f in features}})
    qualified = [s for s in results if s["qualifies"]]
    return {"schema_version": 1, "kind": "fictional_window_stability", "method_version": 2,
            "fictional": True, "provider_requests": 0, "rankings_computed": False,
            "real_player_rankings_allowed": False, "real_integration_allowed": False,
            "sample_unit": "/".join(PROFILE_IDENTITY),
            "split": {"cutoff": cutoff, "earlier": "date < cutoff", "later": "date >= cutoff",
                      "date_format": "YYYY-MM-DD"},
            "screen": {**screen, "applied_independently_to_each_window": True,
                       "status": "candidate_research_screen_only_not_validated"},
            "features": features,
            "match_hold_policy": {"registry_sha256": digest(match_holds),
                                  "applied_before_split": True, "applied_before_aggregation": True,
                                  "held_matches": [{"provider": p, "match_id": mid} for p, mid in sorted(holds)],
                                  "excluded_accepted_player_matches": len(held_rows),
                                  "held_only_samples_retained": True},
            "summary": {"samples": len(results), "qualifying_samples": len(qualified),
                        "ineligible_samples": len(results) - len(qualified),
                        "held_only_samples": len(set(samples) - unheld_samples),
                        "failed_window_counts": {w: sum(w in s["failed_windows"] for s in results) for w in rows},
                        "feature_changes": {f["key"]: _changes([s["absolute_changes"][f["key"]] for s in qualified])
                                            for f in features}},
            "samples": results,
            "limitations": ["Fictional fixtures only; the declaration is not automatic real-data detection.",
                            "Absolute changes describe recorded activity in incomplete samples; no stability pass/fail tolerance is validated.",
                            "The 180-minute/three-appearance candidate screen does not establish reliability, role validity or accurate elapsed exposure.",
                            "This check does not enable real-player analysis, rankings or integration."]}


def readable_stability(document):
    """Render the sample count, window failures and unstandardized rate changes."""
    summary = document["summary"]
    lines = ["Fictional v2 window stability; candidate research screen: 180 recorded minutes and 3 appearances per window.",
             f"Cutoff {document['split']['cutoff']}: earlier < cutoff; later >= cutoff.",
             f"Qualifying samples: {summary['qualifying_samples']}/{summary['samples']}. "
             f"Ineligible: {summary['ineligible_samples']}."]
    for sample in document["samples"]:
        lines.append(" / ".join(str(sample["identity"][k]) for k in PROFILE_IDENTITY))
        for name in ("earlier", "later"):
            window = sample["windows"][name]
            status = "qualifies" if window["qualifies"] else "fails: " + ", ".join(window["reasons"])
            lines.append(f"  {name}: {window['recorded_minutes']} minutes, {window['appearances']} appearances; {status}")
        for feature in document["features"]:
            key = feature["key"]
            def rendered(value):
                return "unavailable" if value is None else f"{value:.6g}"
            earlier, later = (sample["windows"][w]["features"][key]["value"] for w in ("earlier", "later"))
            lines.append(f"  {feature['label']}/90: {rendered(earlier)} -> {rendered(later)}; "
                         f"absolute change={rendered(sample['absolute_changes'][key])}")
    lines.append("Feature absolute changes (actions per 90 recorded minutes; qualifying samples only):")
    for feature in document["features"]:
        stats = summary["feature_changes"][feature["key"]]
        values = ", ".join(f"{k}={stats[k]:.6g}" for k in ("min", "mean", "median", "max")) if stats["samples"] else "unavailable"
        lines.append(f"  {feature['label']}: n={stats['samples']}; {values}")
    lines.append("Real-player analysis remains gated; no fit, ranking or integration is enabled.")
    return "\n".join(lines)
