"""Focused fictional tests for hold-first v2 window stability."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.stability_demo import CUTOFF, fictional_inputs, main
from style_xi.stability import check_stability, readable_stability
from style_xi.storage import DataError, digest


class StabilityTests(unittest.TestCase):
    def setUp(self):
        self.imported, self.calendar, self.holds = fictional_inputs()

    def check(self, **kwargs):
        return check_stability(self.imported, match_dates=self.calendar, cutoff=CUTOFF,
                               fictional=True, **kwargs)

    def test_90_and_108_passes_over_180_minutes_give_45_54_and_change_9(self):
        result = self.check()
        self.assertEqual(result["summary"]["qualifying_samples"], 1)
        sample = result["samples"][0]
        for name, expected in (("earlier", 45), ("later", 54)):
            window = sample["windows"][name]
            self.assertEqual((window["recorded_minutes"], window["appearances"]), (180, 3))
            self.assertEqual(window["features"]["passes_per_90"]["value"], expected)
        self.assertEqual(sample["absolute_changes"], {"passes_per_90": 9, "dribbles_per_90": 3,
                                                      "duels_per_90": 3, "shots_per_90": 3})
        self.assertEqual(result["summary"]["feature_changes"]["passes_per_90"],
                         {"samples": 1, "min": 9, "mean": 9, "median": 9, "max": 9})
        self.assertEqual([f["key"] for f in result["features"]],
                         ["passes_per_90", "dribbles_per_90", "duels_per_90", "shots_per_90"])

    def test_holding_one_earlier_match_fails_only_earlier_window(self):
        result = self.check(match_holds=self.holds)
        sample = result["samples"][0]
        self.assertFalse(sample["qualifies"])
        self.assertEqual(sample["failed_windows"], ["earlier"])
        earlier = sample["windows"]["earlier"]
        self.assertEqual((earlier["recorded_minutes"], earlier["appearances"]), (120, 2))
        self.assertEqual(earlier["match_ids"], [940002, 940003])
        self.assertEqual(earlier["reasons"], ["below_min_appearances", "below_min_minutes"])
        self.assertTrue(sample["windows"]["later"]["qualifies"])
        self.assertEqual(result["summary"]["failed_window_counts"], {"earlier": 1, "later": 0})
        self.assertEqual(result["summary"]["qualifying_samples"], 0)
        self.assertTrue(all(value is None for value in sample["absolute_changes"].values()))
        self.assertEqual(result["summary"]["feature_changes"]["passes_per_90"],
                         {"samples": 0, "min": None, "mean": None, "median": None, "max": None})
        self.assertIn("earlier: 120 minutes, 2 appearances; fails", readable_stability(result))

    def test_holds_precede_date_lookup_counts_and_denominators_for_both_teams(self):
        for row in list(self.imported["player_matches"]):
            opponent = deepcopy(row)
            opponent.update(team_id=900102, player_id=940102)
            self.imported["player_matches"].append(opponent)
        for row in self.imported["player_matches"]:
            if row["match_id"] == 940001:
                row["counts"].update(passesTotal=900, passesSuccessful=900, passesFailed=0)
        # The held match deliberately has no date; it cannot enter a window.
        self.calendar = [c for c in self.calendar if c["match_id"] != 940001]
        result = self.check(match_holds=self.holds)
        self.assertEqual(result["match_hold_policy"]["excluded_accepted_player_matches"], 2)
        self.assertTrue(result["match_hold_policy"]["applied_before_split"])
        for sample in result["samples"]:
            passes = sample["windows"]["earlier"]["features"]["passes_per_90"]
            self.assertEqual(passes["value"], 45)
            self.assertEqual(passes["coverage"]["eligible_minutes"], 120)
            self.assertEqual(passes["coverage"]["observed_appearances"], 2)

    def test_cutoff_is_explicit_and_inclusive_in_later_window(self):
        sample = self.check()["samples"][0]
        self.assertEqual(sample["windows"]["earlier"]["match_ids"], [940001, 940002, 940003])
        self.assertEqual(sample["windows"]["later"]["match_ids"], [940004, 940005, 940006])
        shifted = check_stability(self.imported, match_dates=self.calendar, cutoff="2025-07-02", fictional=True)
        self.assertEqual(shifted["samples"][0]["failed_windows"], ["later"])
        self.assertEqual(shifted["samples"][0]["windows"]["later"]["appearances"], 2)

    def test_each_window_must_independently_meet_both_thresholds(self):
        for deficient, kept in (("earlier", (940001, 940002, 940004, 940005, 940006)),
                                ("later", (940001, 940002, 940003, 940004, 940005))):
            for failure in ("minutes", "appearances"):
                with self.subTest(window=deficient, failure=failure):
                    document = deepcopy(self.imported)
                    if failure == "minutes":
                        affected = {940001, 940002, 940003} if deficient == "earlier" else {940004, 940005, 940006}
                        for row in document["player_matches"]:
                            if row["match_id"] in affected:
                                row["minutes"] = 59  # Three appearances, but only 177 minutes.
                    else:
                        document["player_matches"] = [r for r in document["player_matches"] if r["match_id"] in kept]
                        for row in document["player_matches"]:
                            row["minutes"] = 90  # Two appearances still supply 180 minutes.
                    sample = check_stability(document, match_dates=self.calendar, cutoff=CUTOFF, fictional=True)["samples"][0]
                    self.assertEqual(sample["failed_windows"], [deficient])
                    self.assertEqual(sample["windows"][deficient]["reasons"], ["below_min_" + failure])

    def test_player_team_league_season_stage_and_provider_never_supply_each_others_exposure(self):
        for field, alternate in (("provider", "fictional-other"), ("competition_id", 900302),
                                 ("season", 2026), ("stage", "playoff"),
                                 ("team_id", 900103), ("player_id", 940102)):
            with self.subTest(field=field):
                document = deepcopy(self.imported)
                for row in document["player_matches"]:
                    if row["match_id"] >= 940004:
                        row[field] = alternate
                calendar = deepcopy(self.calendar)
                if field == "provider":
                    for entry in calendar:
                        if entry["match_id"] >= 940004:
                            entry["provider"] = alternate
                result = check_stability(document, match_dates=calendar, cutoff=CUTOFF, fictional=True)
                self.assertEqual(result["summary"]["samples"], 2)
                self.assertEqual(result["summary"]["qualifying_samples"], 0)
                self.assertEqual(sorted(s["failed_windows"] for s in result["samples"]), [["earlier"], ["later"]])

    def test_complete_v2_inputs_are_required_in_each_window_without_imputation(self):
        for match_id, deficient in ((940001, "earlier"), (940004, "later")):
            with self.subTest(window=deficient):
                document = deepcopy(self.imported)
                row = next(r for r in document["player_matches"] if r["match_id"] == match_id)
                # Labelled post-import boundary case, not raw-validator acceptance.
                del row["counts"]["duelsTotal"]
                result = check_stability(document, match_dates=self.calendar, cutoff=CUTOFF, fictional=True)
                sample = result["samples"][0]
                self.assertEqual(sample["failed_windows"], [deficient])
                self.assertIn("missing_feature:duels_per_90", sample["windows"][deficient]["reasons"])
                metric = sample["windows"][deficient]["features"]["duels_per_90"]
                self.assertIsNone(metric["value"])
                self.assertEqual(metric["coverage"]["observed_appearances"], 2)
                self.assertTrue(all(v is None for v in sample["absolute_changes"].values()))

    def test_summary_reports_distribution_across_qualifying_samples_only(self):
        for row in list(self.imported["player_matches"]):
            stable = deepcopy(row)
            stable["player_id"] = 940102
            stable["counts"].update(passesTotal=30, passesSuccessful=30, passesFailed=0)
            self.imported["player_matches"].append(stable)
        short = deepcopy(self.imported["player_matches"][0])
        short["player_id"] = 940103
        self.imported["player_matches"].append(short)
        result = self.check()
        self.assertEqual((result["summary"]["samples"], result["summary"]["qualifying_samples"]), (3, 2))
        self.assertEqual(result["summary"]["feature_changes"]["passes_per_90"],
                         {"samples": 2, "min": 0, "mean": 4.5, "median": 4.5, "max": 9})

    def test_all_held_and_empty_inputs_report_zero_qualifying_samples(self):
        for entry in self.calendar:
            self.holds["cases"][str(entry["match_id"])] = {
                "match_id": entry["match_id"], "hold_scope": "match", "analytical_use_allowed": False}
        self.calendar = []
        result = self.check(match_holds=self.holds)
        self.assertEqual(result["summary"]["held_only_samples"], 1)
        self.assertEqual(result["samples"][0]["failed_windows"], ["earlier", "later"])
        self.assertEqual(result["summary"]["qualifying_samples"], 0)
        self.imported["player_matches"] = []
        result = self.check()
        self.assertEqual(result["summary"]["samples"], 0)
        self.assertIn("Qualifying samples: 0/0", readable_stability(result))
        self.assertTrue(all(s["mean"] is None for s in result["summary"]["feature_changes"].values()))

    def test_dates_and_calendar_fail_closed_instead_of_guessing_order(self):
        for invalid in (None, "2025-02-30", "20250701", "2025-07-01T00:00:00Z", True):
            with self.subTest(cutoff=invalid), self.assertRaisesRegex(DataError, "iso_calendar_date"):
                check_stability(self.imported, match_dates=self.calendar, cutoff=invalid, fictional=True)
        self.calendar[0]["date"] = "unknown"
        with self.assertRaisesRegex(DataError, "iso_calendar_date"):
            self.check()
        # Holds also precede validation of the held match's unusable date.
        self.assertEqual(self.check(match_holds=self.holds)["summary"]["qualifying_samples"], 0)
        self.calendar.pop(0)
        with self.assertRaisesRegex(DataError, "missing_stability_match_date"):
            self.check()
        self.calendar.append(deepcopy(self.calendar[0]))
        with self.assertRaisesRegex(DataError, "duplicate_stability_match_date"):
            self.check()

    def test_provider_scoped_holds_and_invalid_registries(self):
        self.holds["cases"]["940001"]["provider"] = "fictional-other"
        self.assertEqual(self.check(match_holds=self.holds)["summary"]["qualifying_samples"], 1)
        with self.assertRaisesRegex(DataError, "invalid_match_analytical_holds_registry"):
            self.check(match_holds={})

    def test_duplicates_do_not_add_exposure_and_conflicts_are_rejected(self):
        expected = self.check()
        self.imported["player_matches"].append(deepcopy(self.imported["player_matches"][0]))
        self.assertEqual(self.check(), expected)
        self.imported["player_matches"][-1]["minutes"] = 120
        with self.assertRaisesRegex(DataError, "conflicting_profile_player_match_records"):
            self.check()

    def test_rate_is_ratio_of_sums_instead_of_average_match_rates(self):
        for row in self.imported["player_matches"]:
            if row["match_id"] <= 940003:
                minutes, passes = {940001: (30, 10), 940002: (60, 30), 940003: (90, 50)}[row["match_id"]]
                row["minutes"] = minutes
                row["counts"].update(passesTotal=passes, passesSuccessful=passes, passesFailed=0)
        sample = self.check()["samples"][0]
        self.assertEqual(sample["windows"]["earlier"]["features"]["passes_per_90"]["value"], 45)
        self.assertEqual(sample["absolute_changes"]["passes_per_90"], 9)

    def test_order_independence_no_mutation_no_transport_fit_or_ranking(self):
        before = digest([self.imported, self.calendar, self.holds])
        with patch("style_xi.acquire.send", side_effect=AssertionError("no provider transport")), \
             patch("socket.getaddrinfo", side_effect=AssertionError("no DNS")), \
             patch("socket.socket", side_effect=AssertionError("no sockets")), \
             patch("style_xi.similarity.fit_reference", side_effect=AssertionError("no fit")), \
             patch("style_xi.similarity.rank_candidates", side_effect=AssertionError("no ranking")):
            expected = self.check(match_holds=self.holds)
            self.assertEqual(digest([self.imported, self.calendar, self.holds]), before)
            self.imported["player_matches"].reverse()
            self.calendar.reverse()
            self.assertEqual(self.check(match_holds=self.holds), expected)
        self.assertEqual(expected["provider_requests"], 0)
        self.assertFalse(expected["rankings_computed"])
        self.assertFalse(expected["real_player_rankings_allowed"])
        self.assertFalse(expected["real_integration_allowed"])
        self.assertEqual(json.loads(json.dumps(expected, allow_nan=False)), expected)

    def test_fictional_declaration_is_required_before_building_any_profiles(self):
        for declaration in (False, None, 1, "true"):
            with self.subTest(declaration=declaration), \
                 patch("style_xi.stability.build_profiles", side_effect=AssertionError("no real profiles")), \
                 self.assertRaisesRegex(DataError, "declared_fictional_stability_input_required"):
                check_stability(self.imported, match_dates=self.calendar, cutoff=CUTOFF, fictional=declaration)
        with self.assertRaisesRegex(DataError, "declared_fictional_stability_input_required"):
            check_stability(self.imported, match_dates=self.calendar, cutoff=CUTOFF)

    def test_runnable_example_writes_both_fictional_reports(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--output", temp]), 0)
            reports = [json.loads((Path(temp) / name).read_text(encoding="utf-8")) for name in
                       ("fictional-stability.json", "fictional-stability-held.json")]
        self.assertEqual([r["summary"]["qualifying_samples"] for r in reports], [1, 0])
        self.assertIn("Passes/90: 45 -> 54; absolute change=9", output.getvalue())
        self.assertIn("earlier: 120 minutes, 2 appearances; fails", output.getvalue())


if __name__ == "__main__":
    unittest.main()
