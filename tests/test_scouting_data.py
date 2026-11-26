"""Bundled catalogs exercise loading without the original demo's identities."""

from copy import deepcopy
import math
import unittest
from unittest.mock import patch

from style_xi.fictional import fictional_discovery_example
from style_xi.scouting_data import BUNDLED_DATASETS, load_bundled_dataset
from style_xi.similarity import FEATURES, fit_reference, identity, rank_candidates, selector
from style_xi.storage import DataError, digest
from style_xi.ui import discovery_candidates, shortlist_markdown


class ScoutingDataTests(unittest.TestCase):
    def test_default_retains_the_original_catalog_cohort_and_distances(self):
        document, cohort, fit = load_bundled_dataset()
        original, original_cohort = fictional_discovery_example()
        original_fit = fit_reference(original, original_cohort)
        self.assertEqual(cohort, original_cohort)
        self.assertEqual(fit.metadata, original_fit.metadata)
        query = document["fictional_example"]["default_reference"]
        self.assertEqual(rank_candidates(fit, document, query, cohort["candidates"]),
                         rank_candidates(original_fit, original, query, original_cohort["candidates"]))

    def test_second_catalog_has_independent_identities_labels_rates_and_reference(self):
        first, _, old_fit = load_bundled_dataset()
        document, cohort, fit = load_bundled_dataset("harbour")
        for field in ("player_id", "team_id", "competition_id", "season"):
            self.assertTrue({p[field] for p in first["profiles"]}.isdisjoint(p[field] for p in document["profiles"]))
        for field in ("player", "team", "competition"):
            self.assertTrue({name for p in first["profiles"] for name in p["display_names"][field]}.isdisjoint(
                name for p in document["profiles"] for name in p["display_names"][field]))
        self.assertTrue({label for p in first["profiles"] for label in p["observed_positions"]}.isdisjoint(
            label for p in document["profiles"] for label in p["observed_positions"]))
        self.assertEqual(fit.metadata["reference"]["count"], 4)
        self.assertEqual(fit.metadata["scaling"]["passes_per_90"]["mean"], 30)
        self.assertAlmostEqual(fit.metadata["scaling"]["passes_per_90"]["population_std"], math.sqrt(94.5))
        self.assertNotEqual(fit.metadata["reference"]["data_sha256"], old_fit.metadata["reference"]["data_sha256"])
        self.assertNotEqual(fit.metadata["scaling"], old_fit.metadata["scaling"])
        profiles = {identity(selector(p)): p for p in document["profiles"]}
        query = document["fictional_example"]["default_reference"]
        before = digest(fit.metadata)
        for reference in (query, cohort["reference"][1]):
            result = rank_candidates(fit, document, reference, cohort["candidates"], limit=20)
            for pair in result["neighbours"]:
                candidate = profiles[identity(pair["candidate"]["identity"])]
                expected = sum(0.25 * ((candidate["metrics"][key]["value"]
                    - profiles[identity(reference)]["metrics"][key]["value"])
                    / fit.metadata["scaling"][key]["population_std"]) ** 2 for key, _, _ in FEATURES)
                self.assertAlmostEqual(pair["distance_squared"], expected)
        self.assertEqual(digest(fit.metadata), before)
        self.assertFalse(fit.metadata["real_player_rankings_allowed"])
        self.assertFalse(fit.metadata["real_integration_allowed"])

    def test_each_catalog_filters_before_limit_and_exports_its_own_comparisons(self):
        cases = [("lantern", 900301, "Forward", "Mossbridge", 901210),
                 ("harbour", 810301, "Striker", "Glassport", 812479)]
        for dataset, league, position, club, far_player in cases:
            with self.subTest(dataset=dataset):
                document, cohort, fit = load_bundled_dataset(dataset)
                profiles = {identity(selector(p)): p for p in document["profiles"]}
                query = document["fictional_example"]["default_reference"]
                whole = rank_candidates(fit, document, query, cohort["candidates"], limit=5)
                self.assertNotIn(far_player, [p["candidate"]["identity"]["player_id"] for p in whole["neighbours"]])
                candidates = discovery_candidates(profiles, cohort["candidates"], league=league,
                                                   position=position, search="  " + club.upper() + "  ")
                filtered = rank_candidates(fit, document, query, candidates, limit=5)
                self.assertIn(far_player, [p["candidate"]["identity"]["player_id"] for p in filtered["neighbours"]])
                saved = [identity(p["candidate"]["identity"]) for p in filtered["neighbours"]]
                notes = {key: "Keep this fictional sample." for key in saved}
                text = shortlist_markdown(profiles[identity(query)], profiles, saved, notes, filtered)
                self.assertIn(f"fixed fictional scaling reference of {fit.metadata['reference']['count']} samples", text)
                self.assertEqual(text.count("> Keep this fictional sample"), len(saved))
                for pair in filtered["neighbours"]:
                    self.assertIn(f"Distance squared: {pair['distance_squared']}\n", text)
                    for feature in pair["features"]:
                        self.assertIn(f"| {feature['query_value']} | {feature['candidate_value']} | {feature['raw_delta']} | "
                                      f"{feature['standardized_delta']} | {feature['weight']} | {feature['squared_distance_contribution']} |", text)

    def test_runtime_selection_accepts_only_bundled_ids(self):
        for value in (None, True, [], {}, "", "unknown", "data/example.json", "https://example.test/data"):
            with self.subTest(value=value), self.assertRaisesRegex(DataError, "Choose a bundled fictional dataset"):
                load_bundled_dataset(value)

    def test_bundles_need_no_files_credentials_or_transport_and_load_fresh_values(self):
        with patch("style_xi.pipeline.load_snapshots", side_effect=AssertionError("file input forbidden")), \
             patch("style_xi.storage.read_json", side_effect=AssertionError("file input forbidden")), \
             patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
             patch.dict("os.environ", {}, clear=True):
            for dataset in BUNDLED_DATASETS:
                document, cohort, fit = load_bundled_dataset(dataset)
                document["profiles"].clear()
                cohort["reference"].clear()
                fresh, fresh_cohort, fresh_fit = load_bundled_dataset(dataset)
                self.assertTrue(fresh["profiles"])
                self.assertTrue(fresh_cohort["reference"])
                self.assertEqual(fit.metadata, fresh_fit.metadata)

    def test_malformed_bundles_raise_clear_data_errors(self):
        document, cohort, _ = load_bundled_dataset("harbour")
        valid = {"document": document, "cohort": cohort,
                 "default_reference": document["fictional_example"]["default_reference"]}
        cases = []
        def broken(label, change):
            payload = deepcopy(valid)
            change(payload)
            cases.append((label, payload))
        cases.extend([("empty payload", {}), ("non-object", None)])
        broken("schema", lambda p: p["document"].update(schema_version=42))
        broken("not fictional", lambda p: p["cohort"].update(fictional=False))
        broken("missing identity", lambda p: p["document"]["profiles"][0].pop("team_id"))
        broken("duplicate identity", lambda p: p["document"]["profiles"].append(deepcopy(p["document"]["profiles"][0])))
        broken("display labels", lambda p: p["document"]["profiles"][0]["display_names"].update(team=[]))
        broken("positions", lambda p: p["document"]["profiles"][0].update(observed_positions="Striker"))
        broken("position missing flag", lambda p: p["document"]["profiles"][0].update(observed_position_missing=1))
        broken("coverage", lambda p: p["document"]["profiles"][0].update(coverage=None))
        broken("metric", lambda p: p["document"]["profiles"][-1]["metrics"].pop("shots_per_90"))
        broken("nonfinite metric", lambda p: p["document"]["profiles"][-1]["metrics"]["shots_per_90"].update(value=float("nan")))
        broken("missing candidate", lambda p: p["cohort"]["candidates"].pop())
        broken("unknown reference", lambda p: p["default_reference"].update(player_id=999999))
        broken("ineligible reference", lambda p: p["document"]["profiles"][0].update(accepted_minutes=1))
        broken("invalid reference cohort", lambda p: p["cohort"].update(reference=p["cohort"]["reference"][:2]))
        for label, payload in cases:
            with self.subTest(case=label), patch("style_xi.scouting_data._bundled_payload", return_value=payload), \
                 self.assertRaisesRegex(DataError, "Malformed bundled fictional dataset 'harbour': .+"):
                load_bundled_dataset("harbour")


if __name__ == "__main__":
    unittest.main()
