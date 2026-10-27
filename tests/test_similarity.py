"""Independent numerical expectations and fictional end-to-end comparison only."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from examples.similarity_demo import make_example
from style_xi.similarity import (FEATURES, UNIT, explain_pair, feature_contract,
                                 fit_reference, parse_selector, rank_candidates, selector)
from style_xi.storage import DataError, digest


def numerical_fixture():
    """Independent three-point fixture, not the public demonstration's vectors."""
    profiles = []
    for pid, vector in zip((910201, 910202, 910203), ((0, 0, 0, 0), (1, 2, 3, 4), (2, 4, 6, 8))):
        metrics = {key: {"value": value, "unit": UNIT, "reason": None, "issues": [],
                         "coverage": {"eligible_appearances": 2, "observed_appearances": 2,
                                      "eligible_minutes": 180, "observed_minutes": 180, "inputs_complete": True}}
                   for (key, _, _), value in zip(FEATURES, vector)}
        profiles.append({"provider": "highlightly", "competition_id": 910301, "season": 2025,
                         "stage": "regular", "team_id": 910101, "player_id": pid,
                         "accepted_minutes": 180, "accepted_appearances": 2,
                         "contributing_match_ids": [910001, 910002], "metrics": metrics,
                         "display_names": {"player": [f"Fictional {pid}"], "team": [], "competition": []}})
    document = {"schema_version": 1, "kind": "accepted_match_sample_profiles", "metric_contract_version": 1,
                "profiles": profiles}
    cohort = {"schema_version": 1, "fictional": True, "name": "Independent numerical fixture",
              "role_group": "Declared fictional midfield examples",
              "scope": {k: profiles[0][k] for k in ("provider", "competition_id", "season", "stage")},
              "role_player_ids": [p["player_id"] for p in profiles],
              "reference": [selector(p) for p in profiles], "candidates": [selector(p) for p in profiles]}
    return document, cohort


class NumericalComparisonTests(unittest.TestCase):
    def setUp(self):
        self.document, self.cohort = numerical_fixture()

    def fit(self):
        return fit_reference(self.document, self.cohort)

    def rank(self, fit=None, candidates=None, query=None, limit=5):
        return rank_candidates(fit or self.fit(), self.document, query or self.cohort["reference"][0],
                               self.cohort["candidates"] if candidates is None else candidates, limit)

    def test_literal_population_scales_and_weighted_distance(self):
        fit = self.fit()
        expected = ((1, 0.816496580927726), (2, 1.632993161855452),
                    (3, 2.449489742783178), (4, 3.265986323710904))
        for (key, _, _), (mean, std) in zip(FEATURES, expected):
            actual = fit.metadata["scaling"][key]
            self.assertAlmostEqual(actual["mean"], mean)
            self.assertAlmostEqual(actual["population_std"], std)
            self.assertEqual(actual["weight"], 0.25)
        result = self.rank(fit)
        self.assertEqual([n["candidate"]["identity"]["player_id"] for n in result["neighbours"]], [910202, 910203])
        self.assertAlmostEqual(result["neighbours"][0]["distance"], 1.224744871391589)
        self.assertAlmostEqual(result["neighbours"][1]["distance"], 2.449489742783178)
        contributions = result["neighbours"][0]["features"]
        for item in contributions:
            self.assertAlmostEqual(item["squared_distance_contribution"], 0.375)
        self.assertAlmostEqual(sum(c["squared_distance_contribution"] for c in contributions), 1.5)
        self.assertAlmostEqual(result["neighbours"][0]["distance"] ** 2, 1.5)
        self.assertIsNone(fit.metadata["reference"]["sample_contexts"][0]["coverage"])
        copied = fit.metadata
        copied["scaling"]["passes_per_90"]["mean"] = 999
        self.assertEqual(fit.metadata["scaling"]["passes_per_90"]["mean"], 1)

    def test_fixed_fit_symmetry_identical_vectors_and_genuine_zero_profile(self):
        fit = self.fit()
        a, b, _ = self.document["profiles"]
        self.assertAlmostEqual(explain_pair(fit, a, b)["distance"], explain_pair(fit, b, a)["distance"])
        twin = deepcopy(a)
        twin["player_id"] = 910204
        self.cohort["role_player_ids"].append(910204)
        self.document["profiles"].append(twin)
        fit = self.fit()
        self.assertEqual(explain_pair(fit, a, twin)["distance"], 0)
        self.assertEqual(self.rank(fit, [selector(twin)])["returned_neighbours"], 1)

    def test_consistent_unit_change_does_not_change_standardized_distance(self):
        baseline = self.rank()["neighbours"]
        for profile in self.document["profiles"]:
            profile["metrics"]["passes_per_90"]["value"] *= 1000
        rescaled = self.rank()["neighbours"]
        for first, second in zip(baseline, rescaled):
            self.assertAlmostEqual(first["distance"], second["distance"], places=12)
            for f, s in zip(first["features"], second["features"]):
                self.assertAlmostEqual(f["squared_distance_contribution"], s["squared_distance_contribution"], places=12)

    def test_canonical_reference_order_fixed_scaling_and_candidate_filtering(self):
        fit = self.fit()
        query = self.cohort["reference"][0]
        result = self.rank(fit, query=query)
        self.cohort["reference"].reverse()
        self.cohort["candidates"].reverse()
        self.document["profiles"].reverse()
        reordered = self.fit()
        self.assertEqual(digest(fit.metadata), digest(reordered.metadata))
        self.assertEqual(digest(result), digest(self.rank(reordered, query=query)))
        subset = self.rank(fit, [self.cohort["reference"][1]], query=query)
        self.assertEqual(subset["fit"], result["fit"])
        self.assertEqual(subset["neighbours"][0]["distance"], result["neighbours"][0]["distance"])
        another = self.rank(fit, query=self.cohort["reference"][1])
        self.assertEqual(another["fit"], result["fit"])

    def test_global_constant_drop_renormalization_and_raw_difference_visibility(self):
        for p in self.document["profiles"]:
            p["metrics"]["tackles_per_90"]["value"] = 3
        fit = self.fit()
        self.assertEqual(fit.metadata["inactive_features"], ["tackles_per_90"])
        self.assertEqual(fit.metadata["scaling"]["tackles_per_90"]["weight"], 0)
        self.assertAlmostEqual(fit.metadata["scaling"]["passes_per_90"]["weight"], 1 / 3)
        candidate = deepcopy(self.document["profiles"][1])
        candidate["metrics"]["tackles_per_90"]["value"] = 103
        pair = explain_pair(fit, self.document["profiles"][0], candidate)
        self.assertEqual(pair["inactive_feature_differences"], ["tackles_per_90"])
        inactive = pair["features"][2]
        self.assertEqual(inactive["raw_delta"], 100)
        self.assertIsNone(inactive["standardized_delta"])
        self.assertEqual(inactive["squared_distance_contribution"], 0)
        del self.document["profiles"][1]["metrics"]["tackles_per_90"]
        missing = self.rank(fit)
        self.assertIn("missing_feature:tackles_per_90", missing["exclusion_reason_counts"])

    def test_effectively_constant_policy_and_minimum_varying_feature_guard(self):
        for index, p in enumerate(self.document["profiles"]):
            p["metrics"]["tackles_per_90"]["value"] = 1 + index * 1e-14
        self.assertIn("tackles_per_90", self.fit().metadata["inactive_features"])
        for p in self.document["profiles"]:
            for key in ("passes_per_90", "dribbles_per_90"):
                p["metrics"][key]["value"] = 0
        with self.assertRaisesRegex(DataError, "two_varying"):
            self.fit()

    def test_reference_guard_and_ambiguous_spells(self):
        small = deepcopy(self.cohort)
        small["reference"] = small["reference"][:2]
        with self.assertRaisesRegex(DataError, "three_eligible"):
            fit_reference(self.document, small)
        alternate = deepcopy(self.document["profiles"][0])
        alternate["team_id"] = 910102
        self.document["profiles"].append(alternate)
        self.cohort["reference"].append(selector(alternate))
        with self.assertRaisesRegex(DataError, "ambiguous_reference_player_spells"):
            self.fit()

    def test_fictional_scope_declaration_and_reference_exclusion_reporting(self):
        for field, value in (("fictional", False), ("role_player_ids", [910201, 910201])):
            cohort = deepcopy(self.cohort)
            cohort[field] = value
            with self.assertRaises(DataError):
                fit_reference(self.document, cohort)
        cohort = deepcopy(self.cohort)
        cohort["scope"]["stage"] = "playoff"
        with self.assertRaisesRegex(DataError, "one_regular"):
            fit_reference(self.document, cohort)
        extra = deepcopy(self.document["profiles"][0])
        extra["player_id"] = 910204
        extra["metrics"]["passes_per_90"]["value"] = None
        self.document["profiles"].append(extra)
        self.cohort["reference"].append(selector(extra))
        self.cohort["role_player_ids"].append(910204)
        reference = self.fit().metadata["reference"]
        self.assertEqual(reference["count"], 3)
        self.assertEqual(reference["exclusion_reason_counts"], {"missing_feature:passes_per_90": 1})

    def test_query_requires_full_unique_identity_and_empty_or_short_lists(self):
        with self.assertRaises(DataError):
            parse_selector("Fictional Name")
        with self.assertRaises(DataError):
            rank_candidates(self.fit(), self.document, {"player_id": 910201}, [])
        self.assertEqual(self.rank(candidates=[])["status"], "no_eligible_candidates")
        self.assertEqual(self.rank(candidates=[self.cohort["candidates"][0]])["returned_neighbours"], 0)
        short = self.rank(limit=10)
        self.assertEqual((short["returned_neighbours"], short["eligible_candidates"]), (2, 2))
        self.document["profiles"].append(deepcopy(self.document["profiles"][0]))
        with self.assertRaisesRegex(DataError, "duplicate_full_profile_identity"):
            self.fit()

    def test_invalid_feature_missing_exposure_and_ineligible_query_no_ranking(self):
        fit = self.fit()
        for value in (None, -1, True, float("nan"), float("inf"), "1"):
            document = deepcopy(self.document)
            document["profiles"][0]["metrics"]["passes_per_90"]["value"] = value
            result = rank_candidates(fit, document, self.cohort["reference"][0], self.cohort["candidates"])
            self.assertEqual(result["status"], "ineligible_query")
            self.assertEqual(result["neighbours"], [])
            self.assertFalse(result["candidate_evaluation_run"])
            json.dumps(result, allow_nan=False)
        for field, value in (("accepted_minutes", None), ("accepted_minutes", float("nan")),
                             ("accepted_minutes", 0), ("accepted_minutes", 30),
                             ("accepted_appearances", None), ("accepted_appearances", 1),
                             ("contributing_match_ids", [910001])):
            document = deepcopy(self.document)
            document["profiles"][0][field] = value
            result = rank_candidates(fit, document, self.cohort["reference"][0], [])
            self.assertEqual(result["status"], "ineligible_query")
            json.dumps(result, allow_nan=False)

    def test_scope_role_same_player_and_feature_coverage(self):
        fit = self.fit()
        for field, value, reason in (("competition_id", 910302, "outside_cohort_scope"),
                                     ("stage", "playoff", "outside_cohort_scope"),
                                     ("player_id", 910204, "outside_declared_role_group")):
            document = deepcopy(self.document)
            document["profiles"][1][field] = value
            candidates = [selector(document["profiles"][1])]
            result = rank_candidates(fit, document, self.cohort["reference"][0], candidates)
            self.assertIn(reason, result["exclusion_reason_counts"])
        self.document["profiles"][1]["metrics"]["passes_per_90"]["coverage"]["observed_appearances"] = 1
        result = self.rank(fit)
        self.assertIn("inconsistent_feature_coverage:passes_per_90", result["exclusion_reason_counts"])

    def test_no_numeric_autoselection_and_efficiency_does_not_change_order(self):
        fit = self.fit()
        result = self.rank(fit)
        for p in self.document["profiles"]:
            p["metrics"].update(goalsScored={"value": 100}, cardsRed={"value": 99}, expectedGoals={"value": 999}, matchRating={"value": 10})
            p["metrics"]["passes_success_pct"] = {"value": 12 if p["player_id"] == 910202 else 99,
                                                    "reason": None, "unit": "percent", "issues": [],
                                                    "coverage": {"inputs_complete": True}}
        changed = self.rank(fit)
        self.assertEqual([n["distance"] for n in changed["neighbours"]], [n["distance"] for n in result["neighbours"]])
        self.assertEqual(fit.metadata, self.fit().metadata)
        self.assertEqual(len(feature_contract()), 4)
        self.assertEqual({f["weight"] for f in feature_contract()}, {0.25})
        self.assertNotIn("expectedGoals", json.dumps(changed))
        self.assertNotIn("cardsRed", json.dumps(changed))
        self.assertEqual(changed["neighbours"][0]["efficiency_context_only"]["candidate"]["passes_success_pct"]["value"], 12)
        self.document["profiles"][1]["metrics"]["passes_success_pct"]["coverage"]["inputs_complete"] = False
        unavailable = self.rank(fit)["neighbours"][0]["efficiency_context_only"]["candidate"]["passes_success_pct"]
        self.assertIsNone(unavailable["value"])
        self.cohort["features"] = ["goalsScored"]
        with self.assertRaisesRegex(DataError, "unsupported_cohort_fields"):
            self.fit()

    def test_malformed_settings_and_nonfinite_arithmetic_fail_clearly(self):
        for minutes, appearances in ((0, 2), (-1, 2), (float("nan"), 2), (90, 0), (90, True)):
            with self.assertRaisesRegex(DataError, "invalid_exposure_settings"):
                fit_reference(self.document, self.cohort, minutes, appearances)
        with self.assertRaisesRegex(DataError, "positive_integer_neighbour_limit"):
            self.rank(limit=0)
        fit = self.fit()
        self.document["profiles"][1]["metrics"]["passes_per_90"]["value"] = 1e308
        with self.assertRaisesRegex(DataError, "nonfinite_comparison_arithmetic"):
            self.rank(fit)


class FictionalPipelineTests(unittest.TestCase):
    def test_pipeline_neighbours_ties_exclusions_and_fixed_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            document, cohort = make_example(Path(temp) / "data", Path(temp) / "outputs")
            query = parse_selector("highlightly/900301/2025/regular/900101/901201")
            fit = fit_reference(document, cohort)
            result = rank_candidates(fit, document, query, cohort["candidates"])
            self.assertEqual([n["candidate"]["identity"]["player_id"] for n in result["neighbours"]],
                             [901202, 901203, 901206, 901204, 901205])
            self.assertEqual(result["neighbours"][0]["distance"], result["neighbours"][1]["distance"])
            self.assertEqual(result["exclusion_reason_counts"]["same_player"], 3)
            self.assertEqual(result["exclusion_reason_counts"]["missing_feature:dribbles_per_90"], 1)
            self.assertEqual(result["exclusion_reason_counts"]["below_min_minutes"], 1)
            self.assertEqual(result["exclusion_reason_counts"]["below_min_appearances"], 1)
            self.assertEqual(result["exclusion_reason_counts"]["outside_declared_role_group"], 1)
            self.assertEqual(fit.metadata["reference"]["count"], 5)
            different_query = parse_selector("highlightly/900301/2025/regular/900101/901206")
            other = rank_candidates(fit, document, different_query, cohort["candidates"])
            self.assertEqual(result["fit"], other["fit"])
            reverse_pair = next(n for n in other["neighbours"] if n["candidate"]["identity"]["player_id"] == 901201)
            self.assertEqual(reverse_pair["distance"], result["neighbours"][2]["distance"])
            json.dumps(result, allow_nan=False)
            # The reusable generator is resumable even after its cohort file exists.
            again, _ = make_example(Path(temp) / "data", Path(temp) / "outputs")
            self.assertEqual(digest(document), digest(again))

    def test_standalone_documented_cli_without_network_credentials_or_helpers(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("style_xi", "examples"):
                shutil.copytree(project / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
            guard = ("import os,socket,http.client,sys,runpy; os.environ.pop('HIGHLIGHTLY_API_KEY',None); "
                     "deny=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden')); "
                     "socket.socket=deny; socket.create_connection=deny; http.client.HTTPSConnection=deny; "
                     "sys.argv=sys.argv[1:]; ")
            demo = subprocess.run([sys.executable, "-c", guard + "runpy.run_path('examples/similarity_demo.py',run_name='__main__')",
                                   "examples/similarity_demo.py"], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(demo.returncode, 0, demo.stderr)
            command = [sys.executable, "-c", guard + "runpy.run_module('style_xi',run_name='__main__')", "style_xi", "compare",
                       "--input", "outputs/fictional-profiles.json", "--cohort", "data/similarity/cohort.json",
                       "--query", "highlightly/900301/2025/regular/900101/901201", "--output", "outputs/neighbours.json",
                       "--min-minutes", "90", "--min-appearances", "2", "--limit", "5"]
            first = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("Fictional activity comparison", first.stdout)
            before = (root / "outputs/neighbours.json").read_bytes()
            second = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(before, (root / "outputs/neighbours.json").read_bytes())
            bad = command.copy()
            bad[bad.index("--query") + 1] = "Lumen Ash"
            failure = subprocess.run(bad, cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(failure.returncode, 2)
            self.assertIn("query_requires", failure.stdout)


if __name__ == "__main__":
    unittest.main()
