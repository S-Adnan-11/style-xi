"""Validated, write-free loading of the app's bundled fictional catalogs."""

import math

from .fictional import fictional_discovery_example, harbour_discovery_example
from .similarity import EFFICIENCY, FEATURES, fit_reference, identity, rank_candidates, selector
from .storage import DataError

DEFAULT_DATASET = "lantern"
BUNDLED_DATASETS = {"lantern": "Lantern demo", "harbour": "Harbour demo"}


def _bundled_payload(dataset_id):
    if dataset_id == "lantern":
        document, cohort = fictional_discovery_example()
        default = {"provider": "highlightly", "competition_id": 900301, "season": 2025,
                   "stage": "regular", "team_id": 900101, "player_id": 901201}
        for profile in document["profiles"]:
            if profile["player_id"] == 901207:
                profile["fictional_missingness_note"] = (
                    "This is an artificial downstream missingness test: one dribble count was removed after raw validation. "
                    "The raw validator still rejects missing core fields; this tests unavailable-value handling.")
    else:
        document, cohort = harbour_discovery_example()
        default = {"provider": "highlightly", "competition_id": 810301, "season": 2031,
                   "stage": "regular", "team_id": 810111, "player_id": 812401}
    return {"document": document, "cohort": cohort, "default_reference": default}


def _require(condition, message):
    if not condition:
        raise DataError(message)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _validate_payload(payload):
    """Check presentation inputs as well as the engine's profile/cohort contract."""
    _require(isinstance(payload, dict) and set(payload) == {"document", "cohort", "default_reference"},
             "expected document, cohort and default_reference")
    document, cohort = payload["document"], payload["cohort"]
    fit = fit_reference(document, cohort, min_minutes=90, min_appearances=2, method_version=2)
    profiles = {}
    for profile in document["profiles"]:
        key = identity(selector(profile))
        profiles[key] = profile
        names = profile.get("display_names")
        _require(isinstance(names, dict) and all(
            isinstance(names.get(field), list) and names[field]
            and all(isinstance(name, str) and name.strip() for name in names[field])
            for field in ("player", "team", "competition")), "profile display_names must contain nonempty label lists")
        _require(_finite(profile.get("accepted_minutes"))
                 and type(profile.get("accepted_appearances")) is int and profile["accepted_appearances"] >= 0,
                 "profile exposure must be nonnegative minutes and integer appearances")
        labels = profile.get("observed_positions")
        _require(isinstance(labels, list) and all(isinstance(label, str) and label.strip() for label in labels)
                 and type(profile.get("observed_position_missing")) is bool,
                 "profile observed positions must be labels with an explicit missing flag")
        coverage = profile.get("coverage")
        _require(isinstance(coverage, dict) and all(type(coverage.get(field)) is int and coverage[field] >= 0
                 for field in ("accepted_player_matches", "collected_player_matches", "excluded_records")),
                 "profile coverage must contain nonnegative match counts")
        metrics = profile.get("metrics")
        _require(isinstance(metrics, dict), "profile metrics must be an object")
        for field in [key for key, _, _ in FEATURES] + list(EFFICIENCY):
            metric = metrics.get(field)
            _require(isinstance(metric, dict) and "value" in metric
                     and (metric["value"] is None or _finite(metric["value"])),
                     f"profile metric {field} must contain a finite nonnegative value or null")
        note = profile.get("fictional_missingness_note", "")
        _require(isinstance(note, str), "fictional missingness note must be text")
    candidates = cohort.get("candidates")
    _require(isinstance(candidates, list) and len(candidates) == len(profiles)
             and {identity(value) for value in candidates} == set(profiles),
             "candidates must list every profile identity exactly once")
    default = payload["default_reference"]
    _require(identity(default) in profiles, "default reference must identify a bundled profile")
    result = rank_candidates(fit, document, default, candidates, limit=max(1, len(candidates)))
    _require(result["status"] != "ineligible_query", "default reference must be eligible")
    document["fictional_example"]["default_reference"] = default
    return document, cohort, fit


def load_bundled_dataset(dataset_id=DEFAULT_DATASET):
    """Accept only bundled IDs; no paths, uploads, credentials or live inputs."""
    if not isinstance(dataset_id, str) or dataset_id not in BUNDLED_DATASETS:
        raise DataError("Choose a bundled fictional dataset: " + ", ".join(BUNDLED_DATASETS))
    try:
        return _validate_payload(_bundled_payload(dataset_id))
    except (DataError, KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
        detail = str(error) if isinstance(error, DataError) else "invalid dataset structure"
        raise DataError(f"Malformed bundled fictional dataset '{dataset_id}': {detail}") from None
