"""Streamlit workflow tests against the same fictional v2 engine results."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from streamlit.testing.v1 import AppTest

from style_xi.similarity import parse_selector, rank_candidates
from style_xi.storage import digest
from style_xi.ui import (MAX_NOTE_LENGTH, _save_comparison_selection, _save_shortlist_note,
                         contributor_text, demo_data, neighbour_rows)

APP = Path(__file__).resolve().parents[1] / "app.py"


def profile_key(player):
    return tuple(parse_selector(f"highlightly/900301/2025/regular/900101/{player}").values())


def action_key(action, player):
    return action + "_" + "_".join(map(str, profile_key(player)))


def details(app, label):
    return next(e for e in app.expander if e.label == label)


def comparison_cards(app):
    markup = next(m.value for m in app.markdown if m.value.startswith('<div class="comparison-grid">'))
    return {card.find("h4").text: {row.find("dt").text: row.find("dd").text for row in card.findall("dl/div")}
            for card in ElementTree.fromstring(markup)}


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        demo_data.clear()

    def app(self):
        return AppTest.from_file(str(APP), default_timeout=20).run()

    def test_startup_offline_with_visible_gate_criteria_count_and_collapsed_reference_stats(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch("http.client.HTTPSConnection", side_effect=AssertionError("network forbidden")), \
             patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
             patch("style_xi.storage.atomic_json", side_effect=AssertionError("app writes forbidden")), \
             patch("style_xi.pipeline.load_snapshots", side_effect=AssertionError("file data forbidden")):
            app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Style-XⅠ")
        self.assertTrue(any("Fictional demo" in m.value for m in app.markdown))
        self.assertTrue(any("Shortlist · 0" in m.value for m in app.markdown))
        self.assertTrue(any("180 minutes · 2 appearances" in m.value for m in app.markdown))
        self.assertIn("90+ recorded minutes · 2+ appearances", app.caption[0].value)
        self.assertIn("all four v2 rates complete", app.caption[0].value)
        self.assertTrue(any("Real-player analysis gated" in m.value for m in app.markdown))
        self.assertEqual(len(app.selectbox), 3)
        self.assertEqual(len(app.selectbox(key="query").options), 14)
        reference = details(app, "Reference stats and method")
        self.assertFalse(reference.proto.expanded)
        # All full numeric tables belong to collapsed reference/candidate details.
        self.assertEqual(len(app.dataframe), sum(len(e.dataframe) for e in app.expander))

    def test_candidate_cards_plain_top_two_differences_and_precise_details_match_engine(self):
        app = self.app()
        document, cohort, fit = demo_data()
        selected = parse_selector("highlightly/900301/2025/regular/900101/901201")
        result = rank_candidates(fit, document, selected, cohort["candidates"])
        rows = neighbour_rows(result)
        headers = [ElementTree.fromstring(m.value) for m in app.markdown if m.value.startswith('<div class="candidate-heading">')]
        self.assertEqual([h.find("div/strong").text for h in headers], [row["Player"] for row in rows])
        self.assertEqual(rows[0]["Distance group"], "1 (tie)")
        self.assertEqual(rows[1]["Distance group"], "1 (tie)")
        reference = details(app, "Reference stats and method").dataframe[0].value
        self.assertEqual(reference["Per 90 minutes"].tolist(), ["40.00", "4.00", "10.00", "2.00"])
        for pair, row in zip(result["neighbours"], rows):
            candidate = details(app, "Details for " + row["Player"])
            self.assertFalse(candidate.proto.expanded)
            self.assertEqual(candidate.dataframe[0].value["Candidate / 90"].tolist(),
                             [f["candidate_value"] for f in pair["features"]])
            self.assertEqual(candidate.dataframe[1].value["Squared contribution"].tolist(),
                             [f["squared_distance_contribution"] for f in pair["features"]])
            exact = json.loads(candidate.json[0].value)
            self.assertEqual(exact["distance_squared"], pair["distance_squared"])
            self.assertEqual(sum(exact["squared_contributions"].values()), pair["distance_squared"])
        self.assertEqual(contributor_text(result["neighbours"][0]), "More recorded duels; higher pass rate.")
        self.assertEqual(contributor_text(result["neighbours"][-1]), "More shots excluding blocks; more dribble attempts.")
        plain = [m.value for m in app.markdown if m.value.startswith("**Main differences:**")]
        self.assertEqual(plain, ["**Main differences:** " + row["Main differences"] for row in rows])
        self.assertTrue(all(not any(c.isdigit() for c in text) for text in plain))
        self.assertTrue(any("Tied examples" in c.value for c in app.caption))

    def test_short_scope_and_role_examples_remain_ineligible(self):
        for token in ("highlightly/900301/2025/regular/900101/901208",
                      "highlightly/900301/2025/regular/900101/901209",
                      "highlightly/900301/2025/playoff/900101/901201"):
            with self.subTest(token=token):
                app = self.app()
                app.selectbox(key="query").set_value(tuple(parse_selector(token).values())).run()
                self.assertEqual(len(app.exception), 0)
                self.assertTrue(app.warning)
                self.assertFalse(any(b.key.startswith("add_") for b in app.button))
                self.assertTrue(any("Shortlist · 0" in m.value for m in app.markdown))

    def test_empty_and_single_candidate_results_are_explicit_without_padding(self):
        document, cohort, fit = demo_data()
        mira = parse_selector("highlightly/900301/2025/regular/900101/901202")
        for candidates in ([], [mira]):
            modified = deepcopy(cohort)
            modified["candidates"] = candidates
            with patch("style_xi.ui.demo_data", return_value=(document, modified, fit)):
                app = self.app()
            self.assertEqual(len(app.exception), 0)
            add_buttons = [b for b in app.button if b.key.startswith("add_")]
            self.assertEqual(len(add_buttons), len(candidates))
            if not candidates:
                self.assertTrue(any("No eligible candidates" in i.value for i in app.info))

    def test_add_multiple_samples_compare_remove_and_clear_shortlist(self):
        app = self.app()
        mira, pax = profile_key(901202), profile_key(901205)
        app.button(key=action_key("add", 901202)).click().run()
        self.assertEqual(app.session_state["saved_shortlist"], [mira])
        self.assertTrue(app.button(key=action_key("add", 901202)).disabled)
        app.button(key=action_key("add", 901205)).click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["saved_shortlist"], [mira, pax])
        self.assertEqual(app.multiselect[0].value, [mira, pax])
        self.assertTrue(any("Shortlist · 2" in m.value for m in app.markdown))
        cards = comparison_cards(app)
        self.assertEqual(list(cards), ["Lumen Ash", "Mira Reed", "Pax Ember"])
        self.assertEqual([c["Recorded minutes"] for c in cards.values()], ["180"] * 3)
        self.assertEqual([c["Accepted appearances"] for c in cards.values()], ["2"] * 3)
        self.assertEqual([c["Passes / 90"] for c in cards.values()], ["40.00", "42.00", "80.00"])
        self.assertEqual([c["Provider-recorded duels / 90"] for c in cards.values()], ["10.00", "12.00", "4.00"])
        self.assertEqual(cards["Pax Ember"]["Distance from reference"], "1.804115")
        app.button(key=action_key("remove", 901202)).click().run()
        self.assertEqual(app.session_state["saved_shortlist"], [pax])
        self.assertEqual(app.multiselect[0].value, [pax])
        self.assertEqual(list(comparison_cards(app)), ["Lumen Ash", "Pax Ember"])
        app.button(key="clear_shortlist").click().run()
        self.assertEqual(app.session_state["saved_shortlist"], [])
        self.assertTrue(any("Shortlist · 0" in m.value for m in app.markdown))

    def test_several_saved_players_and_reference_change_recalculate_without_refitting(self):
        app = self.app()
        before = digest(demo_data()[2].metadata)
        saved = [profile_key(p) for p in (901202, 901205, 901203)]
        for player in (901202, 901205, 901203):
            app.button(key=action_key("add", player)).click().run()
        self.assertEqual(len(comparison_cards(app)), 4)
        app.selectbox(key="query").set_value(profile_key(901202)).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["saved_shortlist"], saved)
        self.assertTrue(any("Shortlist · 3" in m.value for m in app.markdown))
        cards = comparison_cards(app)
        self.assertEqual(list(cards), ["Mira Reed", "Pax Ember", "Neri Lark"])
        self.assertEqual(cards["Pax Ember"]["Distance from reference"], "1.855428")
        self.assertEqual(cards["Neri Lark"]["Distance from reference"], "0.000000")
        self.assertEqual(cards["Mira Reed"]["Passes / 90"], "42.00")
        self.assertTrue(any("Current reference player" in c.value for c in app.caption))
        self.assertTrue(any("All four recorded rates match" in c.value for c in app.caption))
        self.assertFalse(any(b.key == action_key("add", 901202) for b in app.button))
        fit = demo_data()[2]
        self.assertEqual(digest(fit.metadata), before)
        self.assertFalse(fit.metadata["real_player_rankings_allowed"])
        self.assertFalse(fit.metadata["real_integration_allowed"])

    def test_search_zero_eligible_explains_missingness_and_keeps_saved_samples(self):
        app = self.app()
        app.button(key=action_key("add", 901202)).click().run()
        for search in ("Rumi", "Sable", "no-such-fictional-player"):
            with self.subTest(search=search):
                app.text_input(key="candidate_search").set_value(search).run()
                self.assertEqual(len(app.exception), 0)
                self.assertTrue(any("No eligible candidates" in i.value for i in app.info))
                self.assertEqual(app.session_state["saved_shortlist"], [profile_key(901202)])
                self.assertEqual(len(comparison_cards(app)), 2)
                if search == "Rumi":
                    self.assertTrue(any("1 of 2 accepted appearances" in c.value for c in app.caption))
                    self.assertTrue(any("Missing recorded inputs: dribble attempts" in c.value for c in app.caption))
                elif search == "Sable":
                    self.assertTrue(any("30 recorded minutes · 1 accepted appearance" in c.value for c in app.caption))
                    reasons = " ".join(m.value for m in app.markdown)
                    self.assertIn("Fewer than 90", reasons)
                    self.assertIn("Fewer than two", reasons)
        app.text_input(key="candidate_search").set_value("  MOSSBRIDGE  ").run()
        self.assertEqual(len([b for b in app.button if b.key.startswith("add_")]), 5)
        self.assertEqual(app.session_state["saved_shortlist"], [profile_key(901202)])

    def test_ineligible_reference_keeps_shortlist_rates_without_stale_distances(self):
        app = self.app()
        app.button(key=action_key("add", 901202)).click().run()
        app.selectbox(key="query").set_value(profile_key(901207)).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["saved_shortlist"], [profile_key(901202)])
        cards = comparison_cards(app)
        self.assertEqual(cards["Mira Reed"]["Distance from reference"], "Unavailable")
        self.assertTrue(cards["Rumi Mist"]["Dribbles / 90"].startswith("Unavailable"))
        self.assertEqual(cards["Mira Reed"]["Dribbles / 90"], "4.00")
        self.assertTrue(any("reference sample is ineligible" in c.value for c in app.caption))
        self.assertTrue(any("artificial downstream" in m.value for m in app.markdown))
        app.button(key=action_key("remove", 901202)).click().run()
        self.assertEqual(app.session_state["saved_shortlist"], [])

    def test_comparison_selection_and_new_session_are_independent_of_saved_membership(self):
        app = self.app()
        app.button(key=action_key("add", 901202)).click().run()
        app.multiselect[0].set_value([]).run()
        self.assertEqual(app.session_state["saved_shortlist"], [profile_key(901202)])
        self.assertTrue(any("Select a shortlisted candidate" in i.value for i in app.info))
        app.multiselect[0].set_value([profile_key(901202)]).run()
        self.assertEqual(len(comparison_cards(app)), 2)
        fresh = self.app()
        self.assertEqual(fresh.session_state["saved_shortlist"], [])
        self.assertTrue(any("Shortlist · 0" in m.value for m in fresh.markdown))

    def test_delayed_picker_update_cannot_remove_newly_selected_samples(self):
        selected = [profile_key(p) for p in (901202, 901203, 901205)]
        state = {"comparison_revision": 3, "comparison_selection": selected,
                 "comparison_picker_2": selected[:1], "comparison_picker_3": selected[1:]}
        with patch("style_xi.ui.st.session_state", state):
            _save_comparison_selection("comparison_picker_2")
            self.assertEqual(state["comparison_selection"], selected)
            _save_comparison_selection("comparison_picker_3")
            self.assertEqual(state["comparison_selection"], selected[1:])

    def test_shortlist_notes_edit_independently_and_survive_reference_and_search_changes(self):
        app = self.app()
        for player in (901202, 901205):
            app.button(key=action_key("add", player)).click().run()
        before_fit = digest(demo_data()[2].metadata)
        before_distance = comparison_cards(app)["Pax Ember"]["Distance from reference"]
        mira, pax = profile_key(901202), profile_key(901205)
        app.text_area(key=action_key("note", 901202)).set_value("Close passing pattern; review the duels.").run()
        app.text_area(key=action_key("note", 901205)).set_value("More shots; keep for a second look.").run()
        edited = "Passing looks close. Check the recorded exposure next."
        app.text_area(key=action_key("note", 901202)).set_value(edited).run()
        self.assertEqual(app.session_state["shortlist_notes"][mira], edited)
        self.assertEqual(app.session_state["shortlist_notes"][pax], "More shots; keep for a second look.")
        self.assertEqual(app.text_area(key=action_key("note", 901202)).proto.max_chars, MAX_NOTE_LENGTH)
        self.assertEqual(comparison_cards(app)["Pax Ember"]["Distance from reference"], before_distance)
        for reference in (901202, 901207):
            app.selectbox(key="query").set_value(profile_key(reference)).run()
            self.assertEqual(app.text_area(key=action_key("note", 901202)).value, edited)
            self.assertEqual(app.text_area(key=action_key("note", 901205)).value, "More shots; keep for a second look.")
        app.text_input(key="candidate_search").set_value("no-such-fictional-player").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["shortlist_notes"][mira], edited)
        self.assertEqual(digest(demo_data()[2].metadata), before_fit)

    def test_removing_and_clearing_shortlist_remove_notes_and_readding_starts_empty(self):
        app = self.app()
        for player in (901202, 901205):
            app.button(key=action_key("add", player)).click().run()
            app.text_area(key=action_key("note", player)).set_value("Remember this fictional sample.").run()
        app.button(key=action_key("remove", 901202)).click().run()
        self.assertNotIn(profile_key(901202), app.session_state["shortlist_notes"])
        self.assertNotIn(action_key("note", 901202), app.session_state)
        self.assertIn(profile_key(901205), app.session_state["shortlist_notes"])
        app.button(key=action_key("add", 901202)).click().run()
        self.assertEqual(app.text_area(key=action_key("note", 901202)).value, "")
        app.button(key="clear_shortlist").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["shortlist_notes"], {})
        self.assertNotIn(action_key("note", 901202), app.session_state)
        self.assertNotIn(action_key("note", 901205), app.session_state)
        app.button(key=action_key("add", 901205)).click().run()
        self.assertEqual(app.text_area(key=action_key("note", 901205)).value, "")

    def test_notes_are_session_only_and_late_edits_cannot_restore_removed_notes(self):
        app = self.app()
        app.button(key=action_key("add", 901202)).click().run()
        app.text_area(key=action_key("note", 901202)).set_value("Only in this session.").run()
        fresh = self.app()
        self.assertEqual(fresh.session_state["shortlist_notes"], {})
        key, widget_key = profile_key(901202), action_key("note", 901202)
        state = {"saved_shortlist": [], "shortlist_notes": {}, widget_key: "A late edit"}
        with patch("style_xi.ui.st.session_state", state):
            _save_shortlist_note(key, widget_key)
            self.assertEqual(state["shortlist_notes"], {})


if __name__ == "__main__":
    unittest.main()
