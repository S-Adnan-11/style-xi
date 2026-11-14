"""Invented discovery metadata, fixed v2 scaling and persistent shortlist filters."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from style_xi.fictional import fictional_example
from style_xi.similarity import fit_reference, identity, rank_candidates, selector
from style_xi.storage import DataError, digest
from style_xi.ui import demo_data, discovery_candidates, neighbour_rows

APP = Path(__file__).resolve().parents[1] / "app.py"


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        demo_data.clear()
        self.document, self.cohort, self.fit = demo_data()
        self.profiles = {identity(selector(p)): p for p in self.document["profiles"]}
        self.reference = next(selector(p) for p in self.document["profiles"]
                              if p["player_id"] == 901201 and p["team_id"] == 900101 and p["stage"] == "regular")

    def rank(self, **filters):
        candidates = discovery_candidates(self.profiles, self.cohort["candidates"], **filters)
        return rank_candidates(self.fit, self.document, self.reference, candidates, limit=5)

    def test_reference_samples_scaling_and_original_distances_are_unchanged(self):
        document, cohort = fictional_example()
        original = fit_reference(document, cohort, min_minutes=90, min_appearances=2, method_version=2)
        self.assertEqual(self.fit.metadata["reference"]["count"], 5)
        self.assertEqual(self.fit.metadata["reference"]["data_sha256"], original.metadata["reference"]["data_sha256"])
        self.assertEqual(self.fit.metadata["scaling"], original.metadata["scaling"])
        old = rank_candidates(original, document, self.reference, cohort["candidates"])
        new = self.rank()
        self.assertEqual([(r["candidate"]["identity"], r["distance_squared"], r["features"]) for r in new["neighbours"]],
                         [(r["candidate"]["identity"], r["distance_squared"], r["features"]) for r in old["neighbours"]])

    def test_position_filter_runs_before_limit_and_finds_a_lower_candidate(self):
        self.assertNotIn(901210, [n["candidate"]["identity"]["player_id"] for n in self.rank()["neighbours"]])
        result = self.rank(league=900301, position="Forward")
        self.assertEqual([n["candidate"]["identity"]["player_id"] for n in result["neighbours"]], [901205, 901210])
        self.assertEqual(result["eligible_candidates"], 2)

    def test_league_position_and_search_intersect_without_refitting(self):
        before = digest(self.fit.metadata)
        result = self.rank(league=900302, position="Forward", search="  BRIARHAVEN ")
        self.assertEqual([n["candidate"]["identity"]["player_id"] for n in result["neighbours"]], [902201])
        whole = rank_candidates(self.fit, self.document, self.reference, self.cohort["candidates"], limit=20)
        pair = next(n for n in whole["neighbours"] if n["candidate"]["identity"]["player_id"] == 902201)
        self.assertEqual(result["neighbours"][0], pair)
        self.assertEqual(digest(self.fit.metadata), before)

    def test_empty_and_missing_labels_are_explicit_and_mixed_labels_are_not_majority_roles(self):
        for filters in ({"league": 900302, "position": "Midfielder"}, {"search": "no-invented-match"},
                        {"position": "Unavailable"}):
            with self.subTest(filters=filters):
                self.assertEqual(self.rank(**filters)["neighbours"], [])
        profiles = deepcopy(self.profiles)
        key = next(key for key in profiles if key[-1] == 901210)
        profiles[key]["observed_positions"] = ["Defender", "Forward"]
        profiles[key]["observed_position_missing"] = True
        for label in ("Defender", "Forward", "Unavailable"):
            selected = discovery_candidates(profiles, [selector(profiles[key])], position=label)
            self.assertEqual(selected, [selector(profiles[key])])

    def test_midfield_ties_keep_shared_distance_groups(self):
        result = self.rank(league=900301, position="Midfielder")
        self.assertEqual([n["candidate"]["identity"]["player_id"] for n in result["neighbours"]], [901202, 901203])
        self.assertEqual(result["neighbours"][0]["distance_squared"], result["neighbours"][1]["distance_squared"])
        self.assertEqual([r["Distance group"] for r in neighbour_rows(result)], ["1 (tie)", "1 (tie)"])

    def test_discovery_scopes_are_explicit_and_never_extend_the_reference(self):
        restricted = deepcopy(self.cohort)
        del restricted["discovery_scopes"]
        fit = fit_reference(self.document, restricted, min_minutes=90, min_appearances=2)
        foreign = [c for c in self.cohort["candidates"] if c["competition_id"] == 900302]
        result = rank_candidates(fit, self.document, self.reference, foreign)
        self.assertEqual(result["neighbours"], [])
        self.assertTrue(all("outside_cohort_scope" in row["reasons"] for row in result["candidate_exclusions"]))
        expanded_reference = deepcopy(self.cohort)
        expanded_reference["reference"].append(foreign[0])
        frozen = fit_reference(self.document, expanded_reference, min_minutes=90, min_appearances=2)
        self.assertEqual(frozen.metadata["scaling"], self.fit.metadata["scaling"])
        self.assertEqual(frozen.metadata["reference"]["count"], 5)
        self.assertIn("outside_cohort_scope", frozen.metadata["reference"]["exclusions"][0]["reasons"])
        document = deepcopy(self.document)
        other_spell = deepcopy(next(p for p in document["profiles"] if p["player_id"] == 902201))
        other_spell["player_id"] = self.reference["player_id"]
        document["profiles"].append(other_spell)
        same_player = rank_candidates(self.fit, document, self.reference, [selector(other_spell)])
        self.assertEqual(same_player["candidate_exclusions"][0]["reasons"], ["same_player"])

    def test_invalid_or_nonfictional_scope_expansion_is_rejected(self):
        for field, value in (("provider", "other"), ("season", 2024), ("stage", "playoff"),
                             ("competition_id", 900301), ("competition_id", True)):
            cohort = deepcopy(self.cohort)
            cohort["discovery_scopes"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(DataError):
                fit_reference(self.document, cohort)
        cohort = deepcopy(self.cohort)
        cohort["fictional"] = False
        with self.assertRaisesRegex(DataError, "declared_fictional"):
            fit_reference(self.document, cohort)

    def test_ui_filters_keep_notes_shortlist_exports_and_fixed_fit(self):
        keys = {p["player_id"]: identity(selector(p)) for p in self.document["profiles"] if p["stage"] == "regular" and p["team_id"] == 900101}
        action = lambda prefix, pid: prefix + "_" + "_".join(map(str, keys[pid]))
        with patch("style_xi.ui.st.download_button", return_value=False) as download, \
             patch("style_xi.pipeline.load_snapshots", side_effect=AssertionError("private data forbidden")), \
             patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            app = AppTest.from_file(str(APP), default_timeout=20).run()
            for pid in (901202, 901205):
                app.button(key=action("add", pid)).click().run()
            app.text_area(key=action("note", 901202)).set_value("Keep this saved note.").run()
            saved = list(app.session_state["saved_shortlist"])
            exported = download.call_args.kwargs["data"]
            fit_before = digest(self.fit.metadata)
            with patch("style_xi.ui.fit_reference", side_effect=AssertionError("filter must not refit")):
                app.selectbox(key="candidate_league").set_value(900302).run()
                app.selectbox(key="candidate_position").set_value("Forward").run()
                self.assertEqual([b.label for b in app.button if b.key.startswith("add_")], ["Add Ivo Vale"])
                app.selectbox(key="candidate_position").set_value("Midfielder").run()
                self.assertTrue(any("No eligible candidates" in info.value for info in app.info))
                app.text_input(key="candidate_search").set_value("no-invented-match").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["saved_shortlist"], saved)
            self.assertEqual(app.text_area(key=action("note", 901202)).value, "Keep this saved note.")
            self.assertEqual(download.call_args.kwargs["data"], exported)
            self.assertEqual(digest(self.fit.metadata), fit_before)
            self.assertFalse(self.fit.metadata["real_player_rankings_allowed"])
            self.assertFalse(self.fit.metadata["real_integration_allowed"])
