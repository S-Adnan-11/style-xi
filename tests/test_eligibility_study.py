"""Fictional hold-first threshold, source-label and recorded-minute evidence tests."""

from copy import deepcopy
from contextlib import redirect_stdout
import csv
import hashlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from style_xi.eligibility_study import check_minute_cases, study_eligibility
from style_xi.fictional import fixture, player
from style_xi.pipeline import prepare_snapshot
from style_xi.storage import DataError, atomic_json, digest
from style_xi.study_report import render_study, threshold_csv


def inputs():
    fixtures = [fixture(match=930001 + i, stage="Final" if i == 3 else f"Regular Season - {i + 1}") for i in range(4)]
    envelopes = [{"endpoint": "https://soccer.highlightly.net/matches", "status": 200,
        "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
        "body": {"data": fixtures, "pagination": {"totalCount": 4, "offset": 0, "limit": 10}}}]
    labels = {930101: ["Defender"] * 3, 930102: ["Midfielder", "Forward", "Midfielder"],
              930103: ["Defender", "Midfielder", "Forward"], 930201: ["Forward", "Forward", None],
              930202: ["Goalkeeper"] * 3, 930204: ["Goalkeeper", "Forward", "Midfielder"]}
    for index, match in enumerate(fixtures):
        sides = []
        for side, ids in (("homeTeam", (930101, 930102, 930103)), ("awayTeam", (930201, 930202, 930204))):
            rows = []
            for pid in ids:
                if index == 3 and pid not in (930101, 930202):
                    continue
                row = player(pid=pid, minutes=120 if index == 3 else 90)
                row["position"] = labels[pid][index if index < 3 else 0]
                rows.append(row)
            if index == 1 and side == "awayTeam":
                row = player(pid=930203, minutes=90)
                row["position"] = "Forward"
                rows.append(row)
            sides.append({"team": match[side], "players": rows})
        envelopes.append({"endpoint": f"https://soccer.highlightly.net/box-score/{match['id']}",
                          "status": 200, "parameters": {}, "body": sides})
    snapshots = [prepare_snapshot(item, f"fictional-{i}.json") for i, item in enumerate(envelopes)]
    holds = {"version": 1, "cases": {"930002": {"match_id": 930002, "hold_scope": "match", "analytical_use_allowed": False}}}
    return snapshots, holds


class EligibilityStudyTests(unittest.TestCase):
    def setUp(self):
        self.snapshots, self.holds = inputs()

    def study(self, **kwargs):
        return study_eligibility(self.snapshots, match_holds=self.holds, **kwargs)

    def test_hold_precedes_labels_exposure_and_sample_denominators(self):
        source_hash, hold_hash = digest(self.snapshots), digest(self.holds)
        result = self.study()
        regular = next(s for s in result["stage_totals"] if s["stage"] == "regular")
        self.assertEqual((result["held_accepted_player_matches"], result["held_recorded_minutes"]), (7, 630))
        self.assertEqual(result["held_only_player_team_samples"], 1)
        self.assertEqual((regular["unheld_player_team_samples"], regular["recorded_minutes"], regular["appearances"]), (6, 1080, 12))
        self.assertEqual(regular["position_status_counts"], {"stable": 3, "mixed": 2, "missing": 1})
        self.assertEqual(regular["position_bucket_counts"]["Midfielder"], 1)  # Held Forward label cannot make this sample mixed.
        self.assertEqual(regular["goalkeeper_observed_samples"], 2)  # Includes a mixed keeper/outfield observation.
        self.assertEqual((digest(self.snapshots), digest(self.holds)), (source_hash, hold_hash))

    def test_threshold_counts_are_monotone_and_role_denominators_partition_samples(self):
        regular = next(s for s in self.study()["stage_totals"] if s["stage"] == "regular")
        for t in regular["thresholds"]:
            self.assertEqual(sum(r["denominator"] for r in t["by_source_position"]), 6)
            self.assertEqual(sum(r["meeting_thresholds"] for r in t["by_source_position"]), t["meeting_thresholds"])
            self.assertEqual(t["meeting_thresholds"] + t["below_minutes_only"] + t["below_appearances_only"] + t["below_both"], 6)
            for stricter in regular["thresholds"]:
                if stricter["min_minutes"] >= t["min_minutes"] and stricter["min_appearances"] >= t["min_appearances"]:
                    self.assertLessEqual(stricter["meeting_thresholds"], t["meeting_thresholds"])
        threshold = next(t for t in regular["thresholds"] if (t["min_minutes"], t["min_appearances"]) == (180, 2))
        self.assertEqual(threshold["meeting_thresholds"], 6)
        self.assertEqual(threshold["stable_outfield_complete_inputs"], 2)

    def test_playoff_minutes_and_appearances_cannot_satisfy_regular_threshold(self):
        study = self.study(minute_grid=(90, 270), appearance_grid=(1, 3))
        regular = next(s for s in study["stage_totals"] if s["stage"] == "regular")
        playoff = next(s for s in study["stage_totals"] if s["stage"] == "playoff")
        self.assertEqual(regular["thresholds"][-1]["meeting_thresholds"], 0)
        self.assertEqual((playoff["unheld_player_team_samples"], playoff["recorded_minutes"], playoff["appearances"]), (2, 240, 2))
        self.assertEqual(playoff["thresholds"][0]["meeting_thresholds"], 2)

    def test_missing_precedence_preserves_partial_mixtures_and_unknown_labels(self):
        row = self.snapshots[1]["body"][0]["players"][0]
        row["position"] = None
        self.snapshots[3]["body"][0]["players"][1]["position"] = "Unreviewed source label"
        regular = next(s for s in self.study()["stage_totals"] if s["stage"] == "regular")
        self.assertEqual(regular["position_status_counts"], {"stable": 1, "mixed": 3, "missing": 2})
        self.snapshots[1]["body"][0]["players"][1]["position"] = "Unreviewed source label"
        regular = next(s for s in self.study()["stage_totals"] if s["stage"] == "regular")
        self.assertEqual(regular["position_bucket_counts"]["other_source_label"], 1)

    def test_all_held_population_has_explicit_empty_denominators(self):
        for mid in (930001, 930003, 930004):
            self.holds["cases"][str(mid)] = {"match_id": mid, "hold_scope": "match", "analytical_use_allowed": False}
        result = self.study()
        for stage in result["stage_totals"]:
            self.assertEqual(stage["unheld_player_team_samples"], 0)
            self.assertTrue(all(t["fraction"] is None for t in stage["thresholds"]))
        self.assertIn("unavailable", render_study(result))

    def test_missing_and_known_mixture_are_both_counted_without_majority_assignment(self):
        self.holds["cases"] = {}
        self.snapshots[1]["body"][0]["players"][2]["position"] = None
        regular = next(s for s in self.study()["stage_totals"] if s["stage"] == "regular")
        self.assertEqual(regular["missing_with_multiple_known_labels"], 1)
        self.assertEqual(regular["position_status_counts"]["missing"], 2)
        self.assertEqual(regular["position_bucket_counts"]["missing"], 2)

    def test_no_profiles_fits_rankings_transport_and_deterministic_outputs(self):
        with patch("style_xi.profiles.build_profiles", side_effect=AssertionError("no profiles")), \
             patch("style_xi.similarity.fit_reference", side_effect=AssertionError("no fits")), \
             patch("style_xi.similarity.rank_candidates", side_effect=AssertionError("no rankings")), \
             patch("style_xi.acquire.send", side_effect=AssertionError("no provider transport")):
            before = self.study()
            self.snapshots.reverse()
            after = self.study()
        self.assertEqual(before, after)
        self.assertFalse(before["real_player_rankings_allowed"])
        self.assertEqual(before["provider_requests"], 0)
        rows = list(csv.DictReader(io.StringIO(threshold_csv(before))))
        self.assertEqual(len(rows), 2 * 25 * 7)
        self.assertIn("provisional", render_study(before))
        # Persisted canonical JSON sorts keys; it must not reorder labelled table columns.
        reloaded = json.loads(json.dumps(before, sort_keys=True))
        self.assertIn("| 900301 | 6 | 3 | 2 | 1 |", render_study(reloaded))

    def test_invalid_threshold_grids_fail_before_study(self):
        for minutes, appearances in (((), (1,)), ((90, 90), (1,)), ((-1,), (2,)), ((True,), (2,)), ((90,), (1.5,))):
            with self.assertRaises(DataError):
                self.study(minute_grid=minutes, appearance_grid=appearances)

    def test_minute_case_rechecks_pin_identity_pointer_and_retained_values(self):
        box = self.snapshots[1]
        case = {"match_id": 930001, "player_id": 930101, "provider_minutes": 90,
                "cache_provenance": {"stored_body_sha256": digest(box["body"])},
                "source_field": "/body/0/players/0/minutesPlayed", "verdict": "Fictional prior event-clock review"}
        result = check_minute_cases(self.snapshots, [case], match_holds=self.holds)
        self.assertTrue(result["all_retained_provider_values_reproduced"])
        self.assertFalse(result["cases"][0]["independent_elapsed_minutes_verified"])
        wrong = deepcopy(case)
        wrong["source_field"] = "/body/0/players/1/minutesPlayed"  # Same minutes, wrong player.
        self.assertFalse(check_minute_cases(self.snapshots, [wrong], match_holds=self.holds)["all_retained_provider_values_reproduced"])

    def test_cli_writes_private_study_evidence_report_and_matrix_without_transport(self):
        script = Path(__file__).resolve().parents[1] / "scripts/audit_cache_coverage.py"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            atomic_json(root / "holds.json", self.holds)
            atomic_json(root / "minute-cases.json", {"minutes_cases": [], "study_notes": ["Fictional retained evidence note."]})
            (root / "official.html").write_bytes(b"Fictional preserved page")
            atomic_json(root / "sources.json", [{"name": "official", "requested_url": "https://offline.invalid/example",
                "retrieved_utc": "2026-01-01T00:00:00+00:00", "sha256": hashlib.sha256(b"Fictional preserved page").hexdigest()}])
            argv = [str(script), "--study", "--manifest", str(root / "fictional-campaign.json"), "--match-holds", str(root / "holds.json"),
                "--minutes-evidence", str(root / "minute-cases.json"), "--source-manifest", str(root / "sources.json"),
                "--output", str(root / "study.json"), "--report", str(root / "report.md"), "--threshold-csv", str(root / "matrix.csv")]
            with patch("style_xi.campaign.Campaign") as campaign, patch("sys.argv", argv), redirect_stdout(io.StringIO()), \
                 patch("style_xi.acquire.send", side_effect=AssertionError("no transport")):
                campaign.return_value.snapshots.return_value = self.snapshots
                runpy.run_path(str(script), run_name="__main__")
            result = json.loads((root / "study.json").read_text(encoding="utf-8"))
            self.assertFalse(result["real_player_rankings_allowed"])
            self.assertTrue(result["archived_source_checks"]["sources"][0]["sha256_matches"])
            self.assertIn("Fictional retained evidence note.", (root / "report.md").read_text(encoding="utf-8"))
            self.assertIn("source_position_bucket", (root / "matrix.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
