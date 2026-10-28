"""Hand-calculated fictional profiles and offline import-to-profile checks."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from examples.synthetic_demo import profile_snapshots
from style_xi.pipeline import load_snapshots, replay
from style_xi.profiles import build_profiles, metric_contract, readable_summary
from style_xi.storage import DataError, atomic_json, digest


def imported_example():
    with tempfile.TemporaryDirectory() as temp:
        for index, item in enumerate(profile_snapshots()):
            atomic_json(Path(temp) / f"synthetic-{index}.json", item)
        return replay(load_snapshots(temp))


def find(document, player=900201, team=900101, stage="regular"):
    return next(p for p in document["profiles"] if
                (p["player_id"], p["team_id"], p["stage"]) == (player, team, stage))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.imported = imported_example()

    def test_hand_calculated_totals_rates_and_success(self):
        result = build_profiles(self.imported)
        profile = find(result)
        self.assertEqual((profile["accepted_minutes"], profile["accepted_appearances"]), (120, 2))
        metrics = profile["metrics"]
        self.assertEqual(metrics["passes_total"]["value"], 100)
        self.assertEqual(metrics["passes_per_90"]["value"], 75)
        self.assertEqual(metrics["passes_success_pct"]["value"], 82)
        # Per-match means would give 70 per 90 and 70%, both wrong here.
        self.assertEqual(metrics["key_passes_total"]["value"], 2)
        self.assertEqual(metrics["key_passes_per_90"]["value"], 1.5)
        bram = find(result, player=900202)["metrics"]
        self.assertEqual(bram["dribbles_per_90"]["value"], 15)
        self.assertEqual(bram["dribbles_success_pct"]["value"], 50)
        self.assertEqual(metrics["passes_total"]["coverage"]["observed_appearances"], 2)

    def test_genuine_zero_and_zero_attempts_remain_distinct(self):
        metrics = find(build_profiles(self.imported))["metrics"]
        self.assertEqual(metrics["dribbles_total"]["value"], 0)
        self.assertEqual(metrics["dribbles_per_90"]["value"], 0)
        missing = metrics["dribbles_success_pct"]
        self.assertIsNone(missing["value"])
        self.assertEqual(missing["reason"], "zero_attempts")
        self.assertTrue(missing["coverage"]["inputs_complete"])

    def test_scoped_shots_and_recorded_cameo_minutes_retain_values(self):
        # A blocked-only effort has no player shot count; never infer team blocks.
        for row in self.imported["player_matches"]:
            if row["player_id"] == 900201:
                row["counts"].update(shotsTotal=0, shotsOnTarget=0, shotsOffTarget=0)
                row["minutes"] = 8
        result = build_profiles(self.imported)
        profile = find(result)
        self.assertEqual(profile["accepted_minutes"], 16)
        self.assertEqual(profile["metrics"]["shots_per_90"]["value"], 0)
        self.assertEqual(profile["metrics"]["passes_per_90"]["value"], 100 * 90 / 16)
        self.assertEqual(result["source_field_semantics_version"], 1)
        scope = result["metric_contract"]["shots_per_90"]["source_semantics"]
        self.assertIn("excluding blocked", scope["scope"])
        self.assertIn("separate measure", scope["limitations"])
        self.assertEqual(result["metric_contract"]["tackles_per_90"]["source_semantics"]["status"],
                         "operational_definition_unpublished")
        self.assertEqual(result["validation"]["independent_accuracy"], "not_established")

    def test_importer_missing_record_excluded_with_visible_sample_boundary(self):
        result = build_profiles(self.imported)
        cora = find(result, player=900203)
        self.assertEqual(self.imported["summary"]["accepted"], 7)
        self.assertEqual(self.imported["summary"]["excluded"], 2)
        self.assertEqual(cora["accepted_minutes"], 60)
        self.assertEqual(cora["metrics"]["tackles_per_90"]["value"], 7.5)
        self.assertEqual(cora["metrics"]["interceptions_per_90"]["value"], 6)
        self.assertEqual(cora["coverage"]["collected_player_matches"], 2)
        self.assertEqual(cora["coverage"]["accepted_player_matches"], 1)
        self.assertEqual(cora["coverage"]["excluded_player_matches"], 1)
        self.assertEqual(cora["coverage"]["exclusion_reason_counts"], {"missing_count:interceptionsTotal": 1})
        self.assertFalse(any(p["player_id"] == 900204 for p in result["profiles"]))

    def test_missing_inputs_at_calculation_boundary_never_publish_partial_totals(self):
        for value in (None, "invalid", -1, True, float("nan"), float("inf")):
            with self.subTest(value=value):
                document = deepcopy(self.imported)
                row = next(r for r in document["player_matches"] if r["player_id"] == 900201 and r["match_id"] == 900001)
                row["counts"]["passesTotal"] = value
                profile = find(build_profiles(document))
                for key in ("passes_total", "passes_per_90", "passes_success_pct"):
                    metric = profile["metrics"][key]
                    self.assertIsNone(metric["value"])
                    self.assertEqual(metric["reason"], "incomplete_or_invalid_inputs")
                    self.assertEqual(metric["coverage"]["observed_appearances"], 1)
                    self.assertEqual(metric["coverage"]["eligible_appearances"], 2)
                    self.assertEqual(metric["coverage"]["observed_minutes"], 90)
                self.assertEqual(profile["accepted_minutes"], 120)
                self.assertEqual(profile["metrics"]["dribbles_total"]["value"], 0)

    def test_absent_field_and_incompatible_pair(self):
        row = next(r for r in self.imported["player_matches"] if r["player_id"] == 900201 and r["match_id"] == 900001)
        del row["counts"]["passesKey"]
        row["counts"]["passesSuccessful"] = 99
        metrics = find(build_profiles(self.imported))["metrics"]
        self.assertIsNone(metrics["key_passes_total"]["value"])
        self.assertEqual(metrics["key_passes_total"]["issues"][0]["reason"], "missing_input")
        self.assertIsNone(metrics["passes_success_pct"]["value"])
        self.assertEqual(metrics["passes_success_pct"]["issues"][0]["reason"], "inconsistent_counts")

    def test_missing_and_zero_minutes_produce_missing_per90(self):
        for value, reason in ((None, "incomplete_or_invalid_inputs"), (0, "zero_minutes")):
            document = deepcopy(self.imported)
            for row in document["player_matches"]:
                if row["player_id"] == 900201 and row["team_id"] == 900101 and row["stage"] == "regular":
                    row["minutes"] = value
            metrics = find(build_profiles(document))["metrics"]
            self.assertIsNone(metrics["passes_per_90"]["value"])
            self.assertEqual(metrics["passes_per_90"]["reason"], reason)

    def test_extra_time_transfer_stage_season_and_competition_boundaries(self):
        result = build_profiles(self.imported)
        self.assertEqual(len(result["profiles"]), 5)
        self.assertEqual(find(result, team=900103)["metrics"]["passes_total"]["value"], 5)
        playoff = find(result, stage="playoff")
        self.assertEqual(playoff["accepted_minutes"], 120)
        self.assertEqual(playoff["metrics"]["passes_per_90"]["value"], 90)
        row = deepcopy(self.imported["player_matches"][0])
        row.update(season=2026)
        self.imported["player_matches"].append(row)
        row = deepcopy(row)
        row.update(competition_id=900302)
        self.imported["player_matches"].append(row)
        self.assertEqual(len(build_profiles(self.imported)["profiles"]), 7)

    def test_names_are_display_only_and_missing_names_remain_unknown(self):
        first = find(build_profiles(self.imported))
        self.assertEqual(first["display_names"]["player"], ["Aster Vale"])
        for row in self.imported["player_matches"]:
            row["player_name"] = "Same Fictional Name"
            row.pop("team_name", None)
        result = build_profiles(self.imported)
        self.assertEqual(len(result["profiles"]), 5)
        self.assertEqual(find(result)["display_names"]["team"], [])

    def test_unknown_manifest_and_provider_listing_completion_stay_distinct(self):
        partial = find(build_profiles(self.imported))["coverage"]
        self.assertFalse(partial["provider_manifest_complete"])
        self.assertFalse(partial["independent_coverage_verified"])
        self.assertEqual(partial["collected_box_scores_in_stage"], 3)
        self.imported["coverage"][0]["provider_manifest_complete"] = True
        listing = find(build_profiles(self.imported))["coverage"]
        self.assertTrue(listing["provider_manifest_complete"])
        self.assertFalse(listing["independent_coverage_verified"])
        self.assertFalse(listing["full_season_profile"])
        self.imported.pop("coverage")
        unknown = find(build_profiles(self.imported))["coverage"]
        self.assertIsNone(unknown["provider_manifest_complete"])
        self.assertIsNone(unknown["collected_box_scores_in_stage"])

    def test_duplicate_replay_safe_and_conflicts_fail_explicitly(self):
        result = build_profiles(self.imported)
        self.imported["player_matches"].append(deepcopy(self.imported["player_matches"][0]))
        self.assertEqual(digest(result), digest(build_profiles(self.imported)))
        self.imported["player_matches"][-1]["counts"]["tacklesTotal"] += 1
        with self.assertRaisesRegex(DataError, "conflicting_profile_player_match_records"):
            build_profiles(self.imported)

    def test_output_deterministic_and_excluded_fields_never_enter_contract(self):
        result = build_profiles(self.imported)
        self.imported["player_matches"].reverse()
        self.imported["excluded_records"].reverse()
        self.assertEqual(digest(result), digest(build_profiles(self.imported)))
        for row in self.imported["player_matches"]:
            row["counts"].update(expectedGoals=99, cardsSecondYellow=1, matchRating=9.9, arbitraryNumeric=123)
        self.assertEqual(digest(result), digest(build_profiles(self.imported)))
        self.assertEqual(len(metric_contract()), 17)
        self.assertNotIn("expectedGoals", json.dumps(result))
        self.assertNotIn("cards", json.dumps(result))

    def test_round_only_presentation_and_serialize_nonfinite_results_as_null(self):
        row = next(r for r in self.imported["player_matches"] if r["player_id"] == 900201 and r["match_id"] == 900001)
        row["counts"]["passesKey"] = 3
        row["minutes"] = 31
        result = build_profiles(self.imported)
        self.assertAlmostEqual(find(result)["metrics"]["key_passes_per_90"]["value"], 3.71900826446281)
        self.assertIn("per90=3.72", readable_summary(result))
        row["counts"]["passesKey"] = 10 ** 400
        result = build_profiles(self.imported)
        metric = find(result)["metrics"]["key_passes_per_90"]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["reason"], "nonfinite_result")
        json.dumps(result, allow_nan=False)

    def test_duplicate_missing_and_invalid_states_do_not_depend_on_input_order(self):
        row = self.imported["player_matches"][0]
        duplicate = deepcopy(row)
        row["counts"]["passesKey"] = None
        duplicate["counts"]["passesKey"] = -1
        self.imported["player_matches"].append(duplicate)
        for reverse in (False, True):
            if reverse:
                self.imported["player_matches"].reverse()
            with self.assertRaisesRegex(DataError, "conflicting_profile_player_match_records"):
                build_profiles(self.imported)

    def test_input_schema_and_empty_results(self):
        with self.assertRaisesRegex(DataError, "unsupported_profile_input_schema"):
            build_profiles({"schema_version": 2, "player_matches": []})
        document = deepcopy(self.imported)
        document["player_matches"][0]["status"] = "excluded"
        with self.assertRaisesRegex(DataError, "requires_accepted_records"):
            build_profiles(document)
        self.assertEqual(build_profiles({"schema_version": 1, "player_matches": []})["profiles"], [])

    def test_standalone_public_demo_cli_without_credentials_or_network(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("style_xi", "examples"):
                shutil.copytree(project / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
            guard = ("import os,socket,http.client,sys,runpy; os.environ.pop('HIGHLIGHTLY_API_KEY',None); "
                     "deny=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden')); "
                     "socket.socket=deny; socket.create_connection=deny; http.client.HTTPSConnection=deny; "
                     "sys.argv=sys.argv[1:]; ")
            commands = [(guard + "runpy.run_path('examples/synthetic_demo.py',run_name='__main__')", "examples/synthetic_demo.py"),
                        (guard + "runpy.run_module('style_xi',run_name='__main__')", "style_xi", "import-cache", "--input", "data/synthetic", "--output", "outputs/sample.json"),
                        (guard + "runpy.run_module('style_xi',run_name='__main__')", "style_xi", "profiles", "--input", "outputs/sample.json", "--output", "outputs/profiles.json")]
            for command in commands:
                result = subprocess.run([sys.executable, "-c", *command], cwd=root, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads((root / "outputs/profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(document["summary"]["profiles"], 5)
            self.assertEqual(find(document)["metrics"]["passes_per_90"]["value"], 75)


if __name__ == "__main__":
    unittest.main()
