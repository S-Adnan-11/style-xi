"""Fictional method regression, whole-match hold exclusion and coverage audits."""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from style_xi.coverage_audit import audit_coverage
from style_xi.fictional import comparison_snapshots, fictional_example, fixture, player
from style_xi.pipeline import prepare_snapshot, replay
from style_xi.profiles import build_profiles
from style_xi.similarity import fit_reference, rank_candidates, selector
from style_xi.storage import DataError, digest
from style_xi.storage import atomic_json


def hold_registry(match_id=920002):
    return {"version": 1, "cases": {str(match_id): {"match_id": match_id, "hold_scope": "match",
                                                   "analytical_use_allowed": False}}}


def two_team_snapshots():
    """Both clubs share one held and one unheld match; each has a held-only player."""
    matches = [fixture(match=920001), fixture(match=920002)]
    items = [{"endpoint": "https://soccer.highlightly.net/matches", "status": 200,
              "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
              "body": {"data": matches, "pagination": {"totalCount": 2, "limit": 10, "offset": 0}}}]
    for match in matches:
        sides = []
        for team, pid in zip(("homeTeam", "awayTeam"), (920101, 920102)):
            row = player(pid=pid, minutes=30 if match["id"] == 920001 else 90)
            row["position"] = "Fictional midfield"
            if match["id"] == 920001:
                row["statistics"].update(duelsTotal=6, duelsWon=2, duelsLost=4)
            else:
                row["statistics"].update(passesTotal=900, passesSuccessful=800, passesFailed=100,
                                          duelsTotal=100, duelsWon=50, duelsLost=50)
            players = [row]
            if match["id"] == 920002:
                extra = deepcopy(row)
                extra["id"] += 10
                players.append(extra)
            sides.append({"team": match[team], "players": players})
        items.append({"endpoint": f"https://soccer.highlightly.net/box-score/{match['id']}",
                      "status": 200, "parameters": {}, "body": sides})
    return [prepare_snapshot(item, f"fixture-{i}.json") for i, item in enumerate(items)]


class MethodRevisionTests(unittest.TestCase):
    def test_original_artifacts_reproduce_pre_revision_hashes(self):
        # Captured before the revision, including the original fictional raw counts.
        document, cohort = fictional_example(method_version=1)
        fit = fit_reference(document, cohort, method_version=1)
        result = rank_candidates(fit, document, cohort["reference"][0], cohort["candidates"])
        self.assertEqual(digest(comparison_snapshots(1)), "bba0c32fdee8344187500c7f8f69ebc653f171cb503c0ab3e1e37acaf2403dd9")
        self.assertEqual(digest(document), "49c94c547a8209566b4cc6d1c9e0b55717229efde22f827f6b2f50fe90abbe47")
        self.assertEqual(digest(fit.metadata), "24fdd8d3b08b2f9b2226cd74a986deaa7408aa35e4e5d4389e00005b78e6e1a6")
        self.assertEqual(digest(result), "584aea0cc2ed3df2f31a2ba71fb45b44af8225f1e44dbb617785a95b7e6402df")

    def test_version_two_uses_duels_not_tackles_and_explains_every_contribution(self):
        document, cohort = fictional_example()
        fit = fit_reference(document, cohort)
        result = rank_candidates(fit, document, cohort["reference"][0], cohort["candidates"])
        self.assertEqual(fit.metadata["contract_version"], 2)
        self.assertEqual([f["key"] for f in fit.metadata["features"]],
                         ["passes_per_90", "dribbles_per_90", "duels_per_90", "shots_per_90"])
        self.assertEqual(fit.metadata["features"][3]["label"], "Shots excluding blocks")
        self.assertEqual(fit.metadata["threshold_status"], "provisional_demonstration_only")
        for neighbour in result["neighbours"]:
            self.assertEqual(len(neighbour["features"]), 4)
            self.assertAlmostEqual(math.fsum(f["squared_distance_contribution"] for f in neighbour["features"]),
                                   neighbour["distance"] ** 2)
        for profile in document["profiles"]:
            profile["metrics"]["tackles_per_90"]["value"] = 123456
        self.assertEqual(result, rank_candidates(fit, document, cohort["reference"][0], cohort["candidates"]))
        self.assertEqual(fit.metadata, fit_reference(document, cohort).metadata)
        del document["profiles"][0]["metrics"]["duels_per_90"]
        missing = rank_candidates(fit, document, selector(document["profiles"][0]), [])
        self.assertIn("missing_feature:duels_per_90", missing["query_exclusion_reasons"])
        self.assertEqual(missing["neighbours"], [])

    def test_eligibility_shows_missing_source_fields_and_short_sample(self):
        document, cohort = fictional_example()
        result = rank_candidates(fit_reference(document, cohort), document, cohort["reference"][0], cohort["candidates"])
        rumi = next(p for p in result["candidate_eligibility"] if p["identity"]["player_id"] == 901207)
        missing = next(f for f in rumi["features"] if f["key"] == "dribbles_per_90")
        self.assertFalse(rumi["eligible"])
        self.assertEqual(missing["missing_fields"], ["dribblesTotal"])
        self.assertEqual(missing["coverage"]["observed_appearances"], 1)
        sable = next(p for p in result["candidate_eligibility"] if p["identity"]["player_id"] == 901208)
        self.assertEqual((sable["sample"]["minutes"], sable["sample"]["appearances"]), (30, 1))
        self.assertEqual(sable["reasons"], ["below_min_appearances", "below_min_minutes"])
        self.assertEqual(sable["thresholds"]["status"], "provisional_demonstration_only")
        for version in (0, 3, True, "2"):
            with self.assertRaisesRegex(DataError, "unsupported_comparison_method"):
                fit_reference(document, cohort, method_version=version)


class WholeMatchHoldTests(unittest.TestCase):
    def test_profiles_cli_applies_explicit_registry_before_aggregation(self):
        from style_xi.__main__ import main
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp)
            atomic_json(root / "import.json", replay(two_team_snapshots()))
            atomic_json(root / "holds.json", hold_registry())
            result = main(["profiles", "--input", str(root / "import.json"), "--output", str(root / "profiles.json"),
                           "--match-holds", str(root / "holds.json")])
            output = json.loads((root / "profiles.json").read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(sum(p["accepted_minutes"] for p in output["profiles"]), 60)
        self.assertEqual(sum(p["accepted_appearances"] for p in output["profiles"]), 2)

    def test_both_teams_lose_all_held_actions_minutes_appearances_and_provenance(self):
        imported = replay(two_team_snapshots())
        original_hash = digest(imported)
        held = build_profiles(imported, match_holds=hold_registry())
        unheld_only = deepcopy(imported)
        unheld_only["player_matches"] = [r for r in imported["player_matches"] if r["match_id"] != 920002]
        baseline = build_profiles(unheld_only)
        self.assertEqual(len(held["profiles"]), 4)
        for expected in baseline["profiles"]:
            actual = next(p for p in held["profiles"] if selector(p) == selector(expected))
            self.assertEqual(actual["metrics"], expected["metrics"])
            self.assertEqual((actual["accepted_minutes"], actual["accepted_appearances"]), (30, 1))
            self.assertEqual(actual["contributing_match_ids"], [920001])
            self.assertEqual(actual["source_snapshot_ids"], expected["source_snapshot_ids"])
            self.assertEqual(actual["metrics"]["passes_total"]["value"], 10)
            self.assertEqual(actual["metrics"]["duels_total"]["value"], 6)
            self.assertEqual(actual["coverage"]["held_match_ids"], [920002])
        for pid in (920111, 920112):
            actual = next(p for p in held["profiles"] if p["player_id"] == pid)
            self.assertEqual((actual["accepted_minutes"], actual["accepted_appearances"]), (0, 0))
            self.assertEqual(actual["contributing_match_ids"], [])
            self.assertTrue(all(m["value"] is None and m["reason"] == "no_accepted_records" for m in actual["metrics"].values()))
        self.assertEqual(held["match_hold_policy"]["excluded_accepted_player_matches"], 4)
        self.assertEqual(digest(imported), original_hash)

    def test_provider_scope_and_invalid_registry_fail_closed(self):
        imported = replay(two_team_snapshots())
        other = hold_registry()
        other["cases"]["920002"]["provider"] = "other-provider"
        for actual, expected in zip(build_profiles(imported, match_holds=other)["profiles"], build_profiles(imported)["profiles"]):
            self.assertEqual(actual["metrics"], expected["metrics"])
            self.assertEqual(actual["contributing_match_ids"], expected["contributing_match_ids"])
            self.assertEqual(actual["accepted_minutes"], expected["accepted_minutes"])
        for invalid in ({}, {"version": 1, "cases": []}, {"version": 1, "cases": {"920002": {}}}):
            with self.assertRaisesRegex(DataError, "invalid_match_analytical_hold"):
                build_profiles(imported, match_holds=invalid)

    def test_hold_changes_exposure_eligibility_before_fitting(self):
        imported = replay(two_team_snapshots())
        document, cohort = fictional_example()
        fit = fit_reference(document, cohort)
        held_profiles = build_profiles(imported, match_holds=hold_registry())["profiles"]
        document["profiles"].extend(held_profiles)
        declared = deepcopy(fit.metadata["cohort"])
        declared["role_player_ids"].extend(p["player_id"] for p in held_profiles)
        # A reference fit keeps its cohort; use a fit built with explicit extra role members.
        cohort["role_player_ids"] = declared["role_player_ids"]
        fit = fit_reference(document, cohort)
        for profile in held_profiles:
            result = rank_candidates(fit, document, selector(profile), [])
            self.assertEqual(result["status"], "ineligible_query")
            self.assertEqual(result["neighbours"], [])


class CoverageAuditTests(unittest.TestCase):
    def test_duel_missingness_roles_and_held_exposure_are_explicit(self):
        snapshots = two_team_snapshots()
        del snapshots[1]["body"][0]["players"][0]["statistics"]["duelsTotal"]
        snapshots[1]["body"][1]["players"][0].pop("position")
        before = digest(snapshots)
        with patch("style_xi.profiles.build_profiles", side_effect=AssertionError("no real profiles")), \
             patch("style_xi.similarity.fit_reference", side_effect=AssertionError("no real fit")), \
             patch("style_xi.similarity.rank_candidates", side_effect=AssertionError("no real rankings")), \
             patch("style_xi.acquire.send", side_effect=AssertionError("no transport")):
            result = audit_coverage(snapshots, match_holds=hold_registry())
        group = result["groups"][0]
        fields = group["field_availability_all_source_rows"]
        self.assertEqual(fields["duelsTotal"]["missing"], 1)
        self.assertFalse(fields["duelsTotal"]["complete"])
        self.assertTrue(fields["duelsWon"]["complete"])
        self.assertEqual(group["held_source_rows"], 4)
        exposure = group["unheld_accepted_sample_exposure"]
        self.assertEqual((exposure["accepted_player_matches"], exposure["accepted_minutes"]), (1, 30))
        self.assertEqual(group["role_coverage"]["positive_source_rows_without_role"], 1)
        self.assertFalse(result["real_player_rankings_allowed"])
        self.assertFalse(result["rankings_computed"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertEqual(digest(snapshots), before)

    def test_audit_distinguishes_zero_missing_and_invalid_duel_counts(self):
        for value, missing, invalid in ((0, 0, 0), (None, 1, 0), (-1, 0, 1), (True, 0, 1)):
            with self.subTest(value=value):
                snapshots = two_team_snapshots()
                snapshots[1]["body"][0]["players"][0]["statistics"]["duelsWon"] = value
                fields = audit_coverage(snapshots)["groups"][0]["field_availability_all_source_rows"]
                self.assertEqual(fields["duelsWon"]["missing"], missing)
                self.assertEqual(fields["duelsWon"]["invalid"], invalid)
                self.assertEqual(fields["duelsWon"]["complete"], not (missing or invalid))


if __name__ == "__main__":
    unittest.main()
