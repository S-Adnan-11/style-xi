"""All fixtures in this suite are fictional and generated locally."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from examples.synthetic_demo import body, fixture, snapshots
from style_xi.normalize import CORE, aggregate, normalize_match
from style_xi.pipeline import import_cache, load_snapshots, replay
from style_xi.coverage import inspect_pages
from style_xi.storage import DataError, atomic_json, digest


class NormalizationTests(unittest.TestCase):
    def run_body(self, value, match=None):
        return normalize_match(match or fixture(), value, [{"snapshot_id": "synthetic"}])

    def test_positive_minutes_without_actions_is_valid(self):
        value = body()
        value[0]["players"][0]["statistics"] = dict.fromkeys(CORE, 0)
        good, bad = self.run_body(value)
        self.assertEqual((len(good), len(bad)), (2, 0))
        self.assertIsNone(aggregate(good)[0]["ratios"]["passesAccuracy"])

    def test_excluded_model_and_card_fields_never_flow_to_outputs(self):
        value = body()
        value[0]["players"][0]["statistics"].update(expectedGoals=999, expectedAssists=88,
                                                     cardsSecondYellow=1, cardsRed=1,
                                                     cardsYellow=1, unexpectedNumeric=1000)
        good, _ = self.run_body(value)
        self.assertEqual(set(good[0]["counts"]), set(CORE))
        self.assertNotIn("expectedGoals", str(aggregate(good)))
        self.assertNotIn("cards", str(aggregate(good)))

    def test_zero_minutes_bench_is_excluded(self):
        value = body()
        value[0]["players"][0].update(minutesPlayed=0, isSubstitute=False)
        value[0]["players"][0]["statistics"] = dict.fromkeys(CORE, 0) | {"expectedGoals": 0.9}
        good, bad = self.run_body(value)
        self.assertEqual(len(good), 1)
        self.assertEqual(bad[0]["status"], "excluded")
        self.assertEqual(bad[0]["reasons"], ["zero_minutes_zero_actions"])

    def test_zero_minutes_positive_actions_quarantined(self):
        value = body()
        value[0]["players"][0]["minutesPlayed"] = 0
        _, bad = self.run_body(value)
        self.assertIn("zero_minutes_positive_actions", bad[0]["reasons"])
        self.assertEqual(bad[0]["status"], "quarantined")

    def test_missing_minutes_and_count_are_not_zero(self):
        value = body()
        del value[0]["players"][0]["minutesPlayed"]
        del value[0]["players"][0]["statistics"]["passesTotal"]
        _, bad = self.run_body(value)
        self.assertIsNone(bad[0]["minutes"])
        self.assertIsNone(bad[0]["counts"]["passesTotal"])
        self.assertIn("missing_count:passesTotal", bad[0]["reasons"])

    def test_invalid_minutes_and_counts(self):
        for value in (-1, float("nan"), float("inf"), True, "90"):
            with self.subTest(value=value):
                data = body()
                data[0]["players"][0]["minutesPlayed"] = value
                _, bad = self.run_body(data)
                self.assertIn("invalid_minutes", bad[0]["reasons"])
        for value in (-1, True, 1.5, float("inf"), "1"):
            data = body()
            data[0]["players"][0]["statistics"]["assists"] = value
            _, bad = self.run_body(data)
            self.assertIn("invalid_count:assists", bad[0]["reasons"])

    def test_count_and_displayed_rate_consistency(self):
        data = body()
        stats = data[0]["players"][0]["statistics"]
        stats["passesAccuracy"] = "80.00 %"
        self.assertEqual(len(self.run_body(data)[0]), 2)
        stats["passesAccuracy"] = "90.00 %"
        self.assertIn("inconsistent_rate:passesAccuracy", self.run_body(data)[1][0]["reasons"])
        stats["passesFailed"] = 3
        self.assertIn("inconsistent_counts:passesTotal", self.run_body(data)[1][0]["reasons"])

    def test_ambiguous_statistics_and_duplicate_player(self):
        for stats in ([], [dict.fromkeys(CORE, 0)] * 2, None):
            data = body()
            data[0]["players"][0]["statistics"] = stats
            self.assertIn("ambiguous_or_missing_statistics", self.run_body(data)[1][0]["reasons"])
        data = body()
        data[0]["players"].append(deepcopy(data[0]["players"][0]))
        good, bad = self.run_body(data)
        self.assertEqual((len(good), len(bad)), (1, 2))
        self.assertTrue(all("ambiguous_duplicate_player" in r["reasons"] for r in bad))

    def test_singleton_statistics_and_team_attachment(self):
        data = body()
        data[0]["players"][0]["statistics"] = [data[0]["players"][0]["statistics"]]
        self.assertEqual(len(self.run_body(data)[0]), 2)
        data[0]["team"]["id"] = 999999
        self.assertEqual(len(self.run_body(data)[0]), 0)

    def test_stints_seasons_and_playoffs_stay_separate(self):
        regular, _ = self.run_body(body())
        playoffs, _ = self.run_body(body(), fixture(match=900002, stage="Final"))
        transfer = deepcopy(regular[0])
        transfer.update(team_id=900109, match_id=900003)
        season = deepcopy(regular[0])
        season.update(season=2026, match_id=900004)
        result = aggregate(regular + playoffs + [transfer, season])
        self.assertEqual(len(result), 6)

    def test_ratios_from_summed_counts_and_minutes(self):
        first, _ = self.run_body(body())
        second = deepcopy(first[0])
        second.update(match_id=900002, minutes=30)
        second["counts"].update(passesTotal=100, passesSuccessful=10, passesFailed=90)
        result = aggregate([first[0], second])[0]
        self.assertAlmostEqual(result["ratios"]["passesAccuracy"], 18 / 110)
        self.assertAlmostEqual(result["per90"]["passesTotal"], 110 * 90 / 120)


class ReplayTests(unittest.TestCase):
    def replay_inputs(self, inputs):
        with tempfile.TemporaryDirectory() as temp:
            for i, value in enumerate(inputs):
                atomic_json(Path(temp) / f"{i}.json", value)
            return replay(load_snapshots(temp))

    def test_exact_replay_duplicate_safe_and_deterministic(self):
        inputs = snapshots()
        result = self.replay_inputs(inputs + [deepcopy(inputs[1])])
        self.assertEqual(result["summary"]["accepted"], 2)
        with tempfile.TemporaryDirectory() as temp:
            for i, item in enumerate(inputs):
                atomic_json(Path(temp) / "cache" / f"{i}.json", item)
            one = import_cache(Path(temp) / "cache", Path(temp) / "one.json")
            two = import_cache(Path(temp) / "cache", Path(temp) / "two.json")
            self.assertEqual(digest(one), digest(two))

    def test_conflicting_box_and_fixture_snapshots_quarantined(self):
        for mode in ("box", "fixture"):
            inputs = snapshots()
            conflict = deepcopy(inputs[1 if mode == "box" else 0])
            if mode == "box":
                conflict["body"][0]["players"][0]["statistics"]["expectedGoals"] = 0.5
            else:
                conflict["body"]["data"][0]["round"] = "Final"
            result = self.replay_inputs(inputs + [conflict])
            self.assertEqual(result["summary"]["accepted"], 0)
            self.assertEqual(result["summary"]["match_diagnostics"], 1)

    def test_missing_and_mismatched_fixture_context(self):
        inputs = snapshots()
        self.assertIn("missing_fixture_context", str(self.replay_inputs(inputs[1:])))
        inputs[1]["scope"]["match_id"] = 900009
        self.assertIn("snapshot_scope_mismatch", str(self.replay_inputs(inputs)))

    def test_missing_or_corrupt_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(DataError):
                load_snapshots(temp)

    def test_invalid_nested_identity_and_unknown_stage_quarantine(self):
        for field, value in (("league", None), ("homeTeam", {"id": []}),
                             ("state", None), ("round", "Unclassified")):
            with self.subTest(field=field):
                inputs = snapshots()
                inputs[0]["body"]["data"][0][field] = value
                result = self.replay_inputs(inputs)
                self.assertEqual(result["summary"]["accepted"], 0)
                self.assertTrue(result["excluded_records"] or result["match_diagnostics"])

    def test_empty_input_is_explicit_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(DataError, "no_response_snapshots"):
                load_snapshots(temp)


class CoverageTests(unittest.TestCase):
    def page(self, offset=0, ids=(900001,), total=2, limit=1):
        value = snapshots()[0]
        value["parameters"].update(offset=offset, limit=limit)
        value["body"] = {"data": [fixture(match=i) for i in ids],
                         "pagination": {"offset": offset, "limit": limit, "totalCount": total}}
        return value

    def test_complete_provider_list_is_not_independent_coverage(self):
        result = inspect_pages([self.page(), self.page(1, (900002,))], {900001})[0]
        self.assertTrue(result["provider_manifest_complete"])
        self.assertFalse(result["independent_coverage_verified"])
        self.assertEqual(result["listed_unacquired_box_scores"], [900002])

    def test_partial_empty_repeated_duplicate_changed_and_inconsistent_pages(self):
        scenarios = [([self.page()], "manifest_not_fully_acquired"),
                     ([self.page(ids=())], "empty_or_incomplete_page"),
                     ([self.page(), self.page(1)], "repeated_page"),
                     ([self.page(ids=(900001, 900001), limit=2)], "duplicate_id_within_page"),
                     ([self.page(), self.page(ids=(900002,))], "changed_page_snapshot"),
                     ([self.page(), self.page(1, (900002,), total=3)], "inconsistent_totals"),
                     ([self.page(), self.page(2, (900003,), total=3)], "page_gap_or_overlap")]
        for pages, reason in scenarios:
            with self.subTest(reason=reason):
                result = inspect_pages(pages)[0]
                self.assertFalse(result["provider_manifest_complete"])
                self.assertIn(reason, result["issues"])


if __name__ == "__main__":
    unittest.main()
