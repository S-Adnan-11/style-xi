"""The same scouting workflow runs over either bundled fictional catalog."""

from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from streamlit.testing.v1 import AppTest

from style_xi.scouting_data import BUNDLED_DATASETS
from style_xi.similarity import identity, rank_candidates, selector
from style_xi.storage import DataError, digest
from style_xi.ui import demo_data, profile_label

APP = Path(__file__).resolve().parents[1] / "app.py"


def action(prefix, key):
    return prefix + "_" + "_".join(map(str, key))


def cards(app):
    markup = next(m.value for m in app.markdown if m.value.startswith('<div class="comparison-grid">'))
    return {card.find("h4").text: {row.find("dt").text: row.find("dd").text for row in card.findall("dl/div")}
            for card in ElementTree.fromstring(markup)}


class DatasetInterfaceTests(unittest.TestCase):
    def setUp(self):
        demo_data.clear()

    def app(self, dataset):
        app = AppTest.from_file(str(APP), default_timeout=20).run()
        if dataset != "lantern":
            app.selectbox(key="dataset").set_value(dataset).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_picker_defaults_to_lantern_and_each_catalog_uses_its_own_reference(self):
        for dataset in BUNDLED_DATASETS:
            with self.subTest(dataset=dataset):
                document, cohort, fit = demo_data(dataset)
                profiles = {identity(selector(p)): p for p in document["profiles"]}
                app = self.app(dataset)
                self.assertEqual(app.selectbox(key="dataset").value, dataset)
                self.assertEqual(app.selectbox(key="dataset").options, list(BUNDLED_DATASETS.values()))
                reference = document["fictional_example"]["default_reference"]
                self.assertEqual(app.selectbox(key="query").value, identity(reference))
                expected = rank_candidates(fit, document, reference, cohort["candidates"], limit=5)
                headings = [ElementTree.fromstring(m.value).find("div/strong").text
                            for m in app.markdown if m.value.startswith('<div class="candidate-heading">')]
                self.assertEqual(headings, [" / ".join(profiles[identity(p["candidate"]["identity"])]["display_names"]["player"])
                                            for p in expected["neighbours"]])
                self.assertTrue(any(f"{fit.metadata['reference']['count']}-profile scaling reference" in m.value for m in app.markdown))
                self.assertEqual(len(app.get("file_uploader")), 0)

    def test_both_workflows_keep_notes_and_export_current_cohort_comparisons(self):
        for dataset in BUNDLED_DATASETS:
            with self.subTest(dataset=dataset), \
                 patch("style_xi.ui.st.download_button", return_value=False) as download, \
                 patch("style_xi.pipeline.load_snapshots", side_effect=AssertionError("cache forbidden")), \
                 patch("style_xi.storage.read_json", side_effect=AssertionError("file inputs forbidden")), \
                 patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
                document, cohort, fit = demo_data(dataset)
                profiles = {identity(selector(p)): p for p in document["profiles"]}
                reference = document["fictional_example"]["default_reference"]
                app = self.app(dataset)
                result = rank_candidates(fit, document, reference, cohort["candidates"], limit=5)
                saved = [identity(p["candidate"]["identity"]) for p in result["neighbours"][:2]]
                for key in saved:
                    app.button(key=action("add", key)).click().run()
                    app.text_area(key=action("note", key)).set_value("Keep " + profile_label(profiles[key])).run()
                before = download.call_args.kwargs["data"]
                fit_before = digest(fit.metadata)
                with patch("style_xi.scouting_data.fit_reference", side_effect=AssertionError("must keep the fixed fit")):
                    app.text_input(key="candidate_search").set_value("no-fictional-match").run()
                    self.assertTrue(any("No eligible candidates" in info.value for info in app.info))
                    self.assertEqual(app.session_state["saved_shortlist"], saved)
                    self.assertEqual(download.call_args.kwargs["data"], before)
                    app.selectbox(key="query").set_value(saved[0]).run()
                expected = rank_candidates(fit, document, selector(profiles[saved[0]]),
                                           [selector(profiles[key]) for key in saved], limit=len(saved))
                text = download.call_args.kwargs["data"]
                pair = expected["neighbours"][0]
                self.assertIn(f"Distance squared: {pair['distance_squared']}\n", text)
                for feature in pair["features"]:
                    self.assertIn(f"| {feature['query_value']} | {feature['candidate_value']} | {feature['raw_delta']} | "
                                  f"{feature['standardized_delta']} | {feature['weight']} | {feature['squared_distance_contribution']} |", text)
                for key in saved:
                    self.assertEqual(app.text_area(key=action("note", key)).value, "Keep " + profile_label(profiles[key]))
                candidate_name = " / ".join(profiles[saved[1]]["display_names"]["player"])
                self.assertEqual(cards(app)[candidate_name]["Distance from reference"], f"{pair['distance']:.6f}")
                self.assertEqual(digest(fit.metadata), fit_before)
                app.button(key=action("remove", saved[0])).click().run()
                self.assertNotIn(saved[0], app.session_state["shortlist_notes"])
                app.button(key="clear_shortlist").click().run()
                self.assertEqual(app.session_state["shortlist_notes"], {})
                self.assertEqual(len(app.exception), 0)

    def test_each_dataset_applies_combined_filters_before_the_five_result_limit(self):
        for dataset, league, position, search, player in (
            ("lantern", 900301, "Forward", "  MOSSBRIDGE ", 901210),
            ("harbour", 810301, "Striker", "  GLASSPORT ", 812479),
        ):
            with self.subTest(dataset=dataset):
                document, _, _ = demo_data(dataset)
                key = next(identity(selector(p)) for p in document["profiles"] if p["player_id"] == player)
                app = self.app(dataset)
                self.assertFalse(any(b.key == action("add", key) for b in app.button))
                with patch("style_xi.scouting_data.fit_reference", side_effect=AssertionError("filters must not refit")):
                    app.selectbox(key="candidate_league").set_value(league).run()
                    app.selectbox(key="candidate_position").set_value(position).run()
                    app.text_input(key="candidate_search").set_value(search).run()
                self.assertTrue(any(b.key == action("add", key) for b in app.button))
                self.assertEqual(len(app.exception), 0)

    def test_dataset_switch_clears_foreign_samples_notes_filters_and_exports(self):
        with patch("style_xi.ui.st.download_button", return_value=False) as download:
            app = self.app("lantern")
            for current, other in (("lantern", "harbour"), ("harbour", "lantern")):
                document, cohort, fit = demo_data(current)
                reference = document["fictional_example"]["default_reference"]
                result = rank_candidates(fit, document, reference, cohort["candidates"])
                key = identity(result["neighbours"][0]["candidate"]["identity"])
                app.button(key=action("add", key)).click().run()
                app.text_area(key=action("note", key)).set_value("This note belongs to " + current).run()
                app.selectbox(key="query").set_value(key).run()
                app.selectbox(key="candidate_league").set_value(reference["competition_id"]).run()
                app.selectbox(key="candidate_position").set_value("Forward" if current == "lantern" else "Striker").run()
                app.text_input(key="candidate_search").set_value("no-fictional-match").run()
                revision = app.session_state["comparison_revision"]
                download.reset_mock()
                app.selectbox(key="dataset").set_value(other).run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(app.session_state["saved_shortlist"], [])
                self.assertEqual(app.session_state["shortlist_notes"], {})
                self.assertEqual(app.session_state["comparison_selection"], [])
                self.assertGreater(app.session_state["comparison_revision"], revision)
                self.assertNotIn(action("note", key), app.session_state)
                self.assertIsNone(app.selectbox(key="candidate_league").value)
                self.assertIsNone(app.selectbox(key="candidate_position").value)
                self.assertEqual(app.text_input(key="candidate_search").value, "")
                expected = identity(demo_data(other)[0]["fictional_example"]["default_reference"])
                self.assertEqual(app.selectbox(key="query").value, expected)
                download.assert_not_called()

    def test_malformed_bundled_data_shows_a_clear_error_and_stops_the_workflow(self):
        message = "Malformed bundled fictional dataset 'lantern': profile display_names must contain nonempty label lists"
        with patch("style_xi.ui.load_bundled_dataset", side_effect=DataError(message)), \
             patch("style_xi.ui.st.download_button") as download:
            app = AppTest.from_file(str(APP), default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([error.value for error in app.error], [message])
        self.assertFalse(any(widget.key == "query" for widget in app.selectbox))
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
