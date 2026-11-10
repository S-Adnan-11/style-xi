"""Fictional shortlist downloads follow applied session edits and current v2 results."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from style_xi.similarity import identity, rank_candidates, selector
from style_xi.storage import DataError
from style_xi.ui import demo_data, shortlist_markdown

APP = Path(__file__).resolve().parents[1] / "app.py"


def key(player):
    return ("highlightly", 900301, 2025, "regular", 900101, player)


def action(prefix, player):
    return prefix + "_" + "_".join(map(str, key(player)))


class ShortlistExportTests(unittest.TestCase):
    def setUp(self):
        self.document, self.cohort, self.fit = demo_data()
        self.profiles = {identity(selector(p)): p for p in self.document["profiles"]}
        self.saved = [key(901202), key(901205)]

    def result(self, reference=901201, saved=None):
        saved = self.saved if saved is None else saved
        return rank_candidates(self.fit, self.document, selector(self.profiles[key(reference)]),
                               [selector(self.profiles[k]) for k in saved], limit=max(1, len(saved)))

    def export(self, reference=901201, saved=None, notes=None, result=None):
        saved = self.saved if saved is None else saved
        return shortlist_markdown(self.profiles[key(reference)], self.profiles, saved, notes or {},
                                  self.result(reference, saved) if result is None else result)

    def test_current_reference_exposure_notes_rates_and_precise_contributions(self):
        result = self.result()
        text = self.export(notes={key(901202): "Check the passing", key(901205): "Keep for another look"}, result=result)
        self.assertTrue(text.startswith("# Style-X\u2160 fictional scouting shortlist\n"))
        self.assertIn("Real-player analysis remains gated", text)
        self.assertIn("at least 90 recorded minutes and 2 appearances", text)
        self.assertIn("## Current reference\n\n**Lumen Ash", text)
        self.assertIn("## Saved candidates (2)", text)
        self.assertEqual(text.count("180 recorded minutes"), 3)
        self.assertEqual(text.count("2 accepted appearances"), 3)
        self.assertIn("> Check the passing", text)
        self.assertIn("> Keep for another look", text)
        for pair in result["neighbours"]:
            self.assertIn(f"Distance from reference: {pair['distance']}\n", text)
            self.assertIn(f"Distance squared: {pair['distance_squared']}\n", text)
            for feature in pair["features"]:
                self.assertIn(f"| {feature['query_value']} | {feature['candidate_value']} | {feature['raw_delta']} | "
                              f"{feature['standardized_delta']} | {feature['weight']} | {feature['squared_distance_contribution']} |", text)
        self.assertIn("Main differences: More shots excluding blocks; more dribble attempts.", text)

    def test_reference_changes_recalculate_and_saved_reference_has_no_candidate_distance(self):
        old = self.export()
        new = self.export(reference=901202, notes={key(901202): "Keep this note"})
        self.assertIn("## Current reference\n\n**Mira Reed", new)
        self.assertIn("> Keep this note", new)
        self.assertIn("### Mira Reed", new)
        self.assertIn("Current reference player. No candidate distance is calculated", new)
        self.assertEqual(new.count("Distance from reference:"), 1)
        old_pax = next(p for p in self.result()["neighbours"] if p["candidate"]["identity"]["player_id"] == 901205)
        new_pax = self.result(901202)["neighbours"][0]
        self.assertNotEqual(old_pax["distance"], new_pax["distance"])
        self.assertNotIn(f"Distance from reference: {old_pax['distance']}\n", new)
        self.assertIn(f"Distance from reference: {new_pax['distance']}\n", new)
        self.assertNotEqual(old, new)

    def test_ineligible_reference_keeps_rates_and_notes_without_stale_distances(self):
        text = self.export(reference=901207, notes={key(901205): "Remember this sample"})
        self.assertIn("Reference sample is ineligible:", text)
        self.assertIn("Unavailable", text)
        self.assertIn("Distance unavailable: the reference sample is ineligible.", text)
        self.assertNotIn("Distance from reference:", text)
        self.assertIn("### Pax Ember", text)
        self.assertIn("| Passes / 90 | 80.0 |", text)
        self.assertIn("> Remember this sample", text)

    def test_notes_stay_literal_without_markdown_links_tables_or_html(self):
        text = self.export(notes={key(901202): "# Heading\n| cells |\n<script>bad</script>\n![image](https://invalid.test)\n*literal*"})
        self.assertIn("> \\# Heading", text)
        self.assertIn("> \\| cells \\|", text)
        self.assertIn("> &lt;script&gt;bad&lt;/script&gt;", text)
        self.assertIn("> \\!\\[image\\]\\(https://invalid\\.test\\)", text)
        self.assertIn("> \\*literal\\*", text)
        self.assertNotIn("<script>", text)
        self.assertNotIn("![image](", text)

    def test_export_rejects_real_or_stale_reference_results(self):
        for field, value in [("fictional", False), ("real_player_rankings_allowed", True),
                             ("real_integration_allowed", True), ("contract_version", 1)]:
            result = deepcopy(self.result())
            result["fit"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(DataError, "fictional_v2_shortlist_export_required"):
                self.export(result=result)
        result = self.result()
        result["fictional"] = False
        with self.assertRaisesRegex(DataError, "fictional_v2_shortlist_export_required"):
            self.export(result=result)
        with self.assertRaisesRegex(DataError, "shortlist_export_requires_current_reference"):
            self.export(reference=901202, result=self.result())

    def test_empty_export_is_explicit(self):
        text = self.export(saved=[])
        self.assertIn("## Saved candidates (0)\n\nNo saved candidates.", text)
        self.assertNotIn("Distance from reference:", text)

    def test_download_tracks_notes_reference_search_removal_and_clear_without_live_inputs(self):
        with patch("style_xi.ui.st.download_button", return_value=False) as download, \
             patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
             patch("style_xi.pipeline.load_snapshots", side_effect=AssertionError("cache forbidden")), \
             patch("style_xi.storage.read_json", side_effect=AssertionError("file data forbidden")):
            app = AppTest.from_file(str(APP), default_timeout=20).run()
            download.assert_not_called()
            for player in (901202, 901205):
                app.button(key=action("add", player)).click().run()
            app.text_area(key=action("note", 901202)).set_value("First note").run()
            app.text_area(key=action("note", 901202)).set_value("Edited note").run()
            text = download.call_args.kwargs["data"]
            self.assertIn("> Edited note", text)
            self.assertNotIn("First note", text)
            self.assertEqual(download.call_args.kwargs["file_name"], "style-xi-fictional-shortlist.md")
            self.assertEqual(download.call_args.kwargs["mime"], "text/markdown; charset=utf-8")
            app.selectbox(key="query").set_value(key(901202)).run()
            changed = download.call_args.kwargs["data"]
            self.assertIn("## Current reference\n\n**Mira Reed", changed)
            self.assertIn("> Edited note", changed)
            self.assertIn(f"Distance from reference: {self.result(901202)['neighbours'][0]['distance']}\n", changed)
            app.text_input(key="candidate_search").set_value("no-fictional-match").run()
            app.multiselect[0].set_value([]).run()
            self.assertEqual(download.call_args.kwargs["data"], changed)
            app.selectbox(key="query").set_value(key(901207)).run()
            self.assertIn("Distance unavailable:", download.call_args.kwargs["data"])
            app.button(key=action("remove", 901205)).click().run()
            self.assertNotIn("### Pax Ember", download.call_args.kwargs["data"])
            download.reset_mock()
            app.button(key="clear_shortlist").click().run()
            download.assert_not_called()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(self.fit.metadata["real_player_rankings_allowed"])
            self.assertFalse(self.fit.metadata["real_integration_allowed"])


if __name__ == "__main__":
    unittest.main()
