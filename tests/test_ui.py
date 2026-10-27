"""Actual Streamlit AppTest over the write-free fictional interface."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from style_xi.similarity import parse_selector, rank_candidates, selector
from style_xi.storage import digest
from style_xi.ui import demo_data, neighbour_rows

APP = Path(__file__).resolve().parents[1] / "app.py"


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        demo_data.clear()

    def app(self):
        return AppTest.from_file(str(APP), default_timeout=20).run()

    def test_startup_offline_without_credentials_generated_data_or_writes(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch("http.client.HTTPSConnection", side_effect=AssertionError("network forbidden")), \
             patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
             patch("style_xi.storage.atomic_json", side_effect=AssertionError("app writes forbidden")), \
             patch("style_xi.pipeline.load_snapshots", side_effect=AssertionError("file data forbidden")):
            app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Style-XⅠ")
        self.assertIn("Fictional data", app.info[0].value)
        self.assertEqual(len(app.selectbox), 2)
        self.assertEqual(len(app.selectbox[0].options), 11)

    def test_values_ties_and_reference_equal_package_output(self):
        app = self.app()
        document, cohort, fit = demo_data()
        selected = parse_selector("highlightly/900301/2025/regular/900101/901201")
        result = rank_candidates(fit, document, selected, cohort["candidates"])
        self.assertEqual(app.dataframe[1].value.to_dict("records"), neighbour_rows(result))
        self.assertEqual(app.dataframe[0].value["Per 90 minutes"].tolist(), ["40.00", "4.00", "2.00", "2.00"])
        self.assertEqual(app.dataframe[1].value["Distance group"].tolist()[:2], ["1 (tie)", "1 (tie)"])
        self.assertEqual(app.dataframe[2].value["Difference / 90"].tolist(), [2.0, 0.0, 0.0, 0.0])
        self.assertTrue(any("Tied examples" in c.value for c in app.caption))

    def test_neighbour_and_query_changes_clear_stale_state_without_refit(self):
        app = self.app()
        before = digest(demo_data()[2].metadata)
        pax = tuple(parse_selector("highlightly/900301/2025/regular/900101/901205").values())
        app.selectbox(key="neighbour").set_value(pax).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.dataframe[2].value["Neighbour / 90"].tolist(), [80.0, 10.0, 0.0, 8.0])
        rumi = tuple(parse_selector("highlightly/900301/2025/regular/900101/901207").values())
        app.selectbox(key="query").set_value(rumi).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.selectbox), 1)
        self.assertEqual(len(app.dataframe), 1)
        self.assertIn("Unavailable", app.dataframe[0].value["Per 90 minutes"].tolist()[1])
        self.assertTrue(any("unavailable for comparison" in w.value for w in app.warning))
        self.assertTrue(any("artificial downstream" in m.value for m in app.markdown))
        lumen = tuple(parse_selector("highlightly/900301/2025/regular/900101/901201").values())
        app.selectbox(key="query").set_value(lumen).run()
        self.assertEqual(len(app.selectbox), 2)
        self.assertNotEqual(app.selectbox(key="neighbour").value, pax)
        self.assertEqual(digest(demo_data()[2].metadata), before)

    def test_short_scope_and_role_examples_have_no_shortlist(self):
        for token in ("highlightly/900301/2025/regular/900101/901208",
                      "highlightly/900301/2025/regular/900101/901209",
                      "highlightly/900301/2025/playoff/900101/901201"):
            with self.subTest(token=token):
                app = self.app()
                app.selectbox(key="query").set_value(tuple(parse_selector(token).values())).run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.selectbox), 1)
                self.assertEqual(len(app.dataframe), 1)
                self.assertTrue(app.warning)

    def test_empty_and_short_results_are_explicit_without_padding(self):
        document, cohort, fit = demo_data()
        for candidates in ([], [selector(next(p for p in document["profiles"] if p["player_id"] == 901202))]):
            modified = deepcopy(cohort)
            modified["candidates"] = candidates
            with patch("style_xi.ui.demo_data", return_value=(document, modified, fit)):
                app = self.app()
            self.assertEqual(len(app.exception), 0)
            if not candidates:
                self.assertEqual(len(app.selectbox), 1)
                self.assertTrue(any("No eligible patterns" in i.value for i in app.info))
            else:
                self.assertEqual(len(app.dataframe[1].value), 1)
                self.assertEqual(len(app.selectbox(key="neighbour").options), 1)


if __name__ == "__main__":
    unittest.main()
