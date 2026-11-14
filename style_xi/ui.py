"""Local, fictional-only scouting over the package's fixed v2 comparison method."""

from collections import Counter
from html import escape
import re
from pathlib import Path

import streamlit as st

from .fictional import fictional_discovery_example
from .similarity import FEATURES, fit_reference, identity, rank_candidates, selector
from .storage import DataError

LABELS = {"passes_per_90": "Passes / 90", "dribbles_per_90": "Dribbles / 90",
          "duels_per_90": "Provider-recorded duels / 90", "shots_per_90": "Shots excluding blocks / 90"}
MAX_NOTE_LENGTH = 240
DRIVERS = {
    "passes_per_90": ("Higher pass rate", "Lower pass rate", "Matching pass rate"),
    "dribbles_per_90": ("More dribble attempts", "Fewer dribble attempts", "Matching dribble rate"),
    "duels_per_90": ("More recorded duels", "Fewer recorded duels", "Matching duel rate"),
    "shots_per_90": ("More shots excluding blocks", "Fewer shots excluding blocks", "Matching shot rate"),
}


@st.cache_resource(show_spinner=False)
def demo_data():
    profiles, cohort = fictional_discovery_example()
    return profiles, cohort, fit_reference(profiles, cohort, min_minutes=90, min_appearances=2, method_version=2)


def player_name(profile):
    return " / ".join(profile["display_names"]["player"])


def profile_label(profile):
    stage = "Regular season" if profile["stage"] == "regular" else "Playoff"
    return f"{player_name(profile)} · {' / '.join(profile['display_names']['team'])} · {stage}"


def observed_position_text(profile):
    labels = list(profile.get("observed_positions", []))
    if profile.get("observed_position_missing", not labels):
        labels.append("Unavailable")
    return " / ".join(labels)


def discovery_candidates(profiles, candidates, *, search="", league=None, position=None):
    """Filter the catalog before the scorer applies its display limit."""
    search = search.strip().casefold()
    selected = []
    for candidate in candidates:
        profile = profiles[identity(candidate)]
        if league is not None and profile["competition_id"] != league:
            continue
        labels = profile.get("observed_positions", [])
        if position == "Unavailable":
            if not profile.get("observed_position_missing", not labels):
                continue
        elif position is not None and position not in labels:
            continue
        if not search or search in profile_label(profile).casefold():
            selected.append(candidate)
    return selected


def sample_text(minutes, appearances):
    label = "appearance" if appearances == 1 else "appearances"
    return f"{minutes:g} recorded minutes · {appearances} accepted {label}"


def unavailable_reason(reason):
    return {"zero_attempts": "no recorded attempts", "incomplete_or_invalid_inputs": "incomplete recorded inputs",
            "unavailable": "not recorded", "nonfinite_result": "calculation unavailable"}.get(reason, "required input unavailable")


def shown_metric(metric):
    if metric.get("value") is None:
        return "Unavailable — " + unavailable_reason(metric.get("reason"))
    return f"{metric['value']:.2f}"


def exclusion_text(reason):
    if reason.startswith("missing_feature:") or reason.startswith("incomplete_feature_inputs:"):
        key = reason.split(":", 1)[1]
        return f"{LABELS.get(key, 'An activity rate')} is unavailable for the full accepted sample."
    return {"same_player": "Same player as the reference, including other clubs or stages.",
            "below_min_minutes": "Fewer than 90 accepted minutes in this example.",
            "below_min_appearances": "Fewer than two accepted appearances in this example.",
            "outside_cohort_scope": "Outside this competition, season or regular-season comparison.",
            "outside_declared_role_group": "Outside the declared fictional comparison group.",
            "invalid_or_missing_minutes": "Recorded minutes are unavailable or invalid.",
            "invalid_or_missing_appearances": "Accepted appearances are unavailable or invalid."}.get(reason, "Sample inputs are inconsistent or unavailable.")


def contributor_text(pair):
    """Describe exactly the engine's top two gaps, without contribution arithmetic."""
    features = {f["key"]: f for f in pair["features"]}
    phrases = []
    for key in pair["largest_measured_gaps"]:
        delta = features[key]["raw_delta"]
        phrases.append(DRIVERS[key][0 if delta > 0 else 1 if delta < 0 else 2])
    return "; ".join(phrase if i == 0 else phrase[0].lower() + phrase[1:] for i, phrase in enumerate(phrases)) + "."


def _markdown_text(value):
    """Keep names and free-text notes literal in the downloaded Markdown."""
    return re.sub(r"([\\`*_{}\[\]()#+!|.>-])", r"\\\1", escape(str(value), quote=False))


def shortlist_markdown(profile, profiles, saved, notes, result):
    """Format the current fictional shortlist result; no cache access or refitting."""
    fit = result["fit"]
    if (result.get("fictional") is not True or fit.get("fictional") is not True
            or fit.get("contract_version") != 2
            or fit.get("real_player_rankings_allowed") is not False
            or fit.get("real_integration_allowed") is not False):
        raise DataError("fictional_v2_shortlist_export_required")
    reference = identity(selector(profile))
    if identity(result["query"]["identity"]) != reference:
        raise DataError("shortlist_export_requires_current_reference")
    pairs = {identity(p["candidate"]["identity"]): p for p in result["neighbours"]}
    exclusions = {identity(d["identity"]): d for d in result["candidate_eligibility"]}
    screen = fit["eligibility"]
    lines = ["# Style-XⅠ fictional scouting shortlist", "",
             "Fictional demo. All players, clubs and statistics are invented. Real-player analysis remains gated.", "",
             f"Eligibility: at least {screen['min_minutes']:g} recorded minutes and {screen['min_appearances']} appearances, "
             "with all four v2 rates complete. Provisional demo screen.", "",
             f"Method: v2, with a fixed fictional scaling reference of {fit['reference']['count']} samples. "
             "Lower distance means closer recorded activity patterns, not player ability. "
             "Per-90 rates use recorded minutes. Match coverage is incomplete.", "", "## Current reference", ""]

    def sample(p):
        return [f"**{_markdown_text(profile_label(p))}**", "",
                f"Competition: {_markdown_text(' / '.join(p['display_names']['competition']))} · Season: {p['season']}", "",
                sample_text(p["accepted_minutes"], p["accepted_appearances"]), ""]

    def rates(p):
        return ["| Activity | Per 90 recorded minutes |", "|---|---:|",
                *[f"| {LABELS[key]} | {p['metrics'][key]['value'] if p['metrics'][key]['value'] is not None else shown_metric(p['metrics'][key])} |"
                  for key, _, _ in FEATURES], ""]

    lines.extend(sample(profile))
    lines.extend(rates(profile))
    if result["status"] == "ineligible_query":
        lines.extend(["Reference sample is ineligible: " + " ".join(dict.fromkeys(
            exclusion_text(r) for r in result["query_exclusion_reasons"])), ""])
    lines.extend([f"## Saved candidates ({len(saved)})", ""])
    if not saved:
        lines.extend(["No saved candidates.", ""])
    for key in saved:
        candidate = profiles[key]
        lines.extend([f"### {_markdown_text(player_name(candidate))}", "", *sample(candidate), "**Note**", ""])
        note = notes.get(key, "")
        lines.extend(["> " + _markdown_text(line) for line in note.splitlines()] if note else ["No note saved."])
        lines.append("")
        if key == reference:
            lines.extend(["Current reference player. No candidate distance is calculated for this sample.", "", *rates(candidate)])
        elif key in pairs:
            pair = pairs[key]
            lines.extend([f"Distance from reference: {pair['distance']}", "",
                          f"Distance squared: {pair['distance_squared']}", "",
                          "Main differences: " + contributor_text(pair), "",
                          "Differences are candidate minus reference. Weighted squared contributions add to distance squared.", "",
                          "| Activity | Reference / 90 | Candidate / 90 | Difference / 90 | Standardized difference | Weight | Squared contribution |",
                          "|---|---:|---:|---:|---:|---:|---:|"])
            for f in pair["features"]:
                standardized = f["standardized_delta"] if f["active"] else "Inactive in the fixed fit"
                lines.append(f"| {LABELS[f['key']]} | {f['query_value']} | {f['candidate_value']} | {f['raw_delta']} | "
                             f"{standardized} | {f['weight']} | {f['squared_distance_contribution']} |")
            lines.append("")
        else:
            reason = ("the reference sample is ineligible." if result["status"] == "ineligible_query" else
                      " ".join(dict.fromkeys(exclusion_text(r) for r in exclusions[key]["reasons"])))
            lines.extend(["Distance unavailable: " + reason, "", *rates(candidate)])
    lines.extend(["Saved order is kept. Equal distances remain ties; order does not break them.", ""])
    return "\n".join(lines)


def neighbour_rows(result):
    counts = Counter(n["distance"] for n in result["neighbours"])
    distances = sorted(counts)
    return [{"Distance group": f"{distances.index(n['distance']) + 1}" + (" (tie)" if counts[n["distance"]] > 1 else ""),
             "Player": " / ".join(n["candidate"]["display_names"]["player"]),
             "Club": " / ".join(n["candidate"]["display_names"]["team"]),
             "Distance": n["distance"], "Minutes": n["candidate"]["minutes"],
             "Appearances": n["candidate"]["appearances"],
             "Main differences": contributor_text(n)} for n in result["neighbours"]]


def _key(prefix, key):
    return prefix + "_" + "_".join(map(str, key))


def _add_to_shortlist(key):
    if key not in st.session_state.saved_shortlist:
        st.session_state.saved_shortlist = [*st.session_state.saved_shortlist, key]
        st.session_state.comparison_revision += 1
    if key not in st.session_state.comparison_selection:
        st.session_state.comparison_selection = [*st.session_state.comparison_selection, key]
    st.session_state.shortlist_notes.setdefault(key, "")


def _remove_from_shortlist(key):
    st.session_state.saved_shortlist = [k for k in st.session_state.saved_shortlist if k != key]
    st.session_state.comparison_selection = [k for k in st.session_state.comparison_selection if k != key]
    st.session_state.comparison_revision += 1
    st.session_state.shortlist_notes.pop(key, None)
    st.session_state.pop(_key("note", key), None)


def _clear_shortlist():
    for key in st.session_state.saved_shortlist:
        st.session_state.pop(_key("note", key), None)
    st.session_state.saved_shortlist = []
    st.session_state.comparison_selection = []
    st.session_state.comparison_revision += 1
    st.session_state.shortlist_notes = {}


def _save_shortlist_note(key, widget_key):
    if key in st.session_state["saved_shortlist"]:
        st.session_state["shortlist_notes"][key] = st.session_state[widget_key]


def _save_comparison_selection(widget_key):
    if widget_key == f"comparison_picker_{st.session_state['comparison_revision']}":
        st.session_state["comparison_selection"] = list(st.session_state[widget_key])


def _show_eligibility(details):
    sample, thresholds = details.get("sample"), details["thresholds"]
    if sample:
        st.caption(sample_text(sample["minutes"], sample["appearances"]) +
                   f". Screen: at least {thresholds['min_minutes']:g} minutes and {thresholds['min_appearances']} appearances.")
    for text in dict.fromkeys(exclusion_text(reason) for reason in details["reasons"]):
        st.write("• " + text)
    fields = {"dribblesTotal": "dribble attempts", "dribblesSuccessful": "successful dribbles",
              "dribblesFailed": "failed dribbles", "passesTotal": "passes",
              "passesSuccessful": "successful passes", "passesFailed": "failed passes",
              "duelsTotal": "duels", "duelsWon": "duels won", "duelsLost": "duels lost",
              "shotsTotal": "shots", "shotsOnTarget": "shots on target", "shotsOffTarget": "shots off target"}
    for feature in details.get("features") or []:
        if feature["available"]:
            continue
        coverage = feature.get("coverage") or {}
        if coverage:
            st.caption(f"{LABELS[feature['key']]}: complete inputs for {coverage['observed_appearances']} "
                       f"of {coverage['eligible_appearances']} accepted appearances.")
        if feature["missing_fields"]:
            st.caption("Missing recorded inputs: " + ", ".join(fields.get(f, f) for f in feature["missing_fields"]) + ".")


def _render_pair(profile, candidate, pair):
    """Full precision and rate context live inside a candidate's details."""
    st.caption(f"{player_name(profile)} → {player_name(candidate)}. Differences are candidate minus reference.")
    st.dataframe([{"Activity": LABELS[f["key"]], "Reference / 90": f["query_value"],
                   "Candidate / 90": f["candidate_value"], "Difference / 90": f["raw_delta"]}
                  for f in pair["features"]], hide_index=True, width="stretch")
    st.write("**Distance contributions**")
    st.caption("Weighted squared contributions add to distance squared. They describe measured gaps, not player ability.")
    st.dataframe([{"Feature": LABELS[f["key"]], "Standardized difference": f["standardized_delta"],
                   "Weight": f["weight"], "Squared contribution": f["squared_distance_contribution"]}
                  for f in pair["features"]], hide_index=True, width="stretch",
                 column_config={"Squared contribution": st.column_config.NumberColumn(format="%.9f")})
    st.json({"distance": pair["distance"], "distance_squared": pair["distance_squared"],
             "squared_contributions": {LABELS[f["key"]]: f["squared_distance_contribution"] for f in pair["features"]}})
    st.write("**Efficiency context · outside the distance**")
    efficiency = pair["efficiency_context_only"]
    st.dataframe([{"Measure": name.replace("_success_pct", " success").replace("_", " ").capitalize(),
                   "Reference (%)": shown_metric(efficiency["query"][name]),
                   "Candidate (%)": shown_metric(efficiency["candidate"][name])}
                  for name in efficiency["query"]], hide_index=True, width="stretch")


def _render_results(result, profile, profiles):
    st.subheader("Candidates")
    if result["status"] == "ineligible_query":
        st.warning("This reference sample is unavailable for comparison.")
        _show_eligibility(result["query_eligibility"])
        return
    st.caption(f"{result['eligible_candidates']} eligible · {result['returned_neighbours']} shown · "
               f"{len(result['candidate_exclusions'])} excluded")
    if not result["neighbours"]:
        st.info("No eligible candidates for these filters. Change the league, observed position or search. Your shortlist is kept.")
    else:
        st.caption("Lower distance means closer patterns. Differences compare per-90 rates with the reference.")
        rows = neighbour_rows(result)
        for pair, row in zip(result["neighbours"], rows):
            key = identity(pair["candidate"]["identity"])
            candidate = profiles[key]
            with st.container(border=True, key=_key("candidate", key)):
                st.markdown(f'<div class="candidate-heading"><div><strong>{escape(row["Player"])}</strong>'
                            f'<span>{escape(row["Club"])} · {escape(" / ".join(candidate["display_names"]["competition"]))}'
                            f' · Observed: {escape(observed_position_text(candidate))} · Regular season</span></div>'
                            f'<div class="distance-number">{pair["distance"]:.4f}'
                            f'<small>Distance · Group {escape(row["Distance group"])}</small></div></div>', unsafe_allow_html=True)
                st.caption(sample_text(row["Minutes"], row["Appearances"]))
                st.write("**Main differences:** " + row["Main differences"])
                if pair["distance"] == 0:
                    st.caption("All four recorded rates match the reference.")
                saved = key in st.session_state.saved_shortlist
                st.button(("Added · " if saved else "Add ") + player_name(candidate), key=_key("add", key),
                          type="secondary" if saved else "primary", disabled=saved, on_click=_add_to_shortlist, args=(key,))
                with st.expander("Details for " + player_name(candidate)):
                    _render_pair(profile, candidate, pair)
        if any("tie" in row["Distance group"] for row in rows):
            st.caption("Equal distances share a group. Tied examples are equally close under this method.")
    if result["candidate_exclusions"]:
        with st.expander("Why some profiles are excluded"):
            for item in result["candidate_eligibility"]:
                if item["eligible"]:
                    continue
                p = profiles.get(identity(item["identity"]))
                st.write(f"**{profile_label(p) if p else 'Unavailable profile'}**")
                _show_eligibility(item)


def _render_shortlist(document, fit, profile, profiles):
    st.subheader("Session shortlist", anchor="session-shortlist")
    saved = st.session_state.saved_shortlist
    st.caption("Saved for this session. Distances update when the reference changes.")
    if not saved:
        st.info("Your shortlist is empty. Add a candidate to start comparing.")
        return {}
    st.write(f"**{len(saved)} saved {'sample' if len(saved) == 1 else 'samples'}**")
    result = rank_candidates(fit, document, selector(profile), [selector(profiles[k]) for k in saved], limit=len(saved))
    pairs = {identity(p["candidate"]["identity"]): p for p in result["neighbours"]}
    details = {identity(d["identity"]): d for d in result["candidate_eligibility"]}
    reference = identity(selector(profile))
    for key in saved:
        candidate = profiles[key]
        with st.container(border=True, key=_key("saved", key)):
            st.write(f"**{player_name(candidate)}**")
            st.caption(" / ".join(candidate["display_names"]["team"]))
            if key == reference:
                st.caption("Current reference player. This sample stays saved.")
            elif key in pairs:
                st.caption(f"Distance from reference: {pairs[key]['distance']:.4f}")
                st.write(contributor_text(pairs[key]))
                with st.expander("Saved details for " + player_name(candidate)):
                    _render_pair(profile, candidate, pairs[key])
            elif result["status"] == "ineligible_query":
                st.caption("Distance unavailable because the reference sample is ineligible. Recorded rates remain visible below.")
            else:
                _show_eligibility(details[key])
            note_key = _key("note", key)
            st.text_area("Note for " + player_name(candidate), key=note_key,
                         value=st.session_state.shortlist_notes.get(key, ""),
                         placeholder="Why did you save this player?", max_chars=MAX_NOTE_LENGTH, height=88,
                         help="Only kept for this session. Removing the player or clearing the shortlist removes the note.",
                         on_change=_save_shortlist_note, args=(key, note_key))
            st.button("Remove " + player_name(candidate), key=_key("remove", key), on_click=_remove_from_shortlist, args=(key,))
    st.download_button("Download fictional shortlist (.md)",
                       data=shortlist_markdown(profile, profiles, saved, st.session_state.shortlist_notes, result),
                       file_name="style-xi-fictional-shortlist.md", mime="text/markdown; charset=utf-8",
                       key="shortlist_download", on_click="ignore", width="stretch",
                       help="Includes every saved player, applied note edits and comparisons with the current reference.")
    st.button("Clear shortlist", key="clear_shortlist", on_click=_clear_shortlist)
    return pairs


def comparison_markup(profile, profiles, selected, pairs):
    """A read-only comparison grid that stacks into complete cards on mobile."""
    reference = identity(selector(profile))
    cards = []
    for key in [reference, *[k for k in selected if k != reference]]:
        candidate = profiles[key]
        is_reference = key == reference
        distance = "Reference player" if is_reference else f"{pairs[key]['distance']:.6f}" if key in pairs else "Unavailable"
        values = [("Recorded minutes", f"{candidate['accepted_minutes']:g}"),
                  ("Accepted appearances", str(candidate["accepted_appearances"])), ("Distance from reference", distance),
                  *[(LABELS[f], shown_metric(candidate["metrics"][f])) for f, _, _ in FEATURES]]
        stats = "".join(f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>" for label, value in values)
        cards.append(f'<article class="comparison-card{" is-reference" if is_reference else ""}">'
                     f'<p class="card-kicker">{"Reference" if is_reference else "Candidate"}</p>'
                     f'<h4>{escape(player_name(candidate))}</h4><p class="card-club">{escape(profile_label(candidate).split(" · ", 1)[1])}</p>'
                     f'<dl>{stats}</dl></article>')
    return '<div class="comparison-grid">' + "".join(cards) + "</div>"


def _render_comparison(profile, profiles, pairs):
    if not st.session_state.saved_shortlist:
        return
    st.subheader("Shortlist side by side")
    # A membership change gets a fresh picker. A delayed browser update from the
    # previous picker cannot overwrite saved comparison choices during rapid adds.
    widget_key = f"comparison_picker_{st.session_state.comparison_revision}"
    chosen = st.multiselect("Players to compare", st.session_state.saved_shortlist,
                            default=st.session_state.comparison_selection, key=widget_key,
                            format_func=lambda key: profile_label(profiles[key]),
                            on_change=_save_comparison_selection, args=(widget_key,),
                            help="The reference always appears alongside selected saved samples.")
    if not any(key != identity(selector(profile)) for key in chosen):
        st.info("Select a shortlisted candidate to view alongside the reference player.")
        return
    st.markdown(comparison_markup(profile, profiles, chosen, pairs), unsafe_allow_html=True)
    st.caption("Per-90 rates use recorded player minutes. Cards stack on narrow screens so every selected sample stays readable.")


def _render_reference_stats(profile, fit, result):
    with st.expander("Reference stats and method", key="reference_stats"):
        coverage = profile["coverage"]
        st.caption(f"{coverage['accepted_player_matches']} of {coverage['collected_player_matches']} collected player matches accepted · "
                   f"{coverage['excluded_records']} excluded records · Incomplete match coverage")
        st.dataframe([{"Activity": LABELS[key], "Per 90 minutes": shown_metric(profile["metrics"][key])}
                      for key, _, _ in FEATURES], hide_index=True, width="stretch", key="sample_rates")
        if profile["player_id"] == 901207:
            st.write("This is an artificial downstream missingness test: one dribble count was removed after raw validation. "
                     "The raw validator still rejects missing core fields; this tests unavailable-value handling.")
        st.write("Method version 2 uses passes, dribbles, provider-recorded duels and shots excluding blocks. "
                 "An explicitly declared fictional catalog across two invented leagues in one season and regular stage. "
                 "Observed labels come from invented appearances, not inferred roles. "
                 "The original five-profile scaling reference stays fixed when you change the reference player or discovery filters. "
                 "Activity can reflect team context and opportunity; this does not measure player ability.")
        st.json({"selected_identity": selector(profile), "sample_coverage": coverage, "eligibility": result["query_eligibility"],
                 "reference_count": fit.metadata["reference"]["count"], "scaling": fit.metadata["scaling"],
                 "active_features": fit.metadata["active_features"], "inactive_features": fit.metadata["inactive_features"],
                 "reference_data_sha256": fit.metadata["reference"]["data_sha256"],
                 "real_player_rankings_allowed": fit.metadata["real_player_rankings_allowed"],
                 "real_integration_allowed": fit.metadata["real_integration_allowed"]})


def render_app():
    st.set_page_config(page_title="Style-XⅠ | Fictional scouting", layout="wide")
    st.html(Path(__file__).with_name("scouting.css"))
    st.title("Style-XⅠ")
    st.markdown('<div class="demo-banner"><span class="demo-badge">Fictional demo</span>'
                '<span class="demo-note">Real-player analysis gated</span></div>', unsafe_allow_html=True)
    st.caption("Eligibility: 90+ recorded minutes · 2+ appearances · all four v2 rates complete. Provisional demo screen.")
    document, cohort, fit = demo_data()
    profiles = {identity(selector(p)): p for p in document["profiles"]}
    st.session_state.setdefault("saved_shortlist", [])
    st.session_state.setdefault("comparison_selection", [])
    st.session_state.setdefault("comparison_revision", 0)
    st.session_state.setdefault("shortlist_notes", {})
    choices = sorted(profiles, key=lambda key: profile_label(profiles[key]))
    default = next(key for key in choices if key[-1] == 901201 and key[-2] == 900101 and key[3] == "regular")
    with st.container(key="reference_strip"):
        picker, summary = st.columns([3, 2], vertical_alignment="bottom")
        with picker:
            selected = st.selectbox("Reference player", choices, index=choices.index(default),
                                    format_func=lambda key: profile_label(profiles[key]), key="query")
        profile = profiles[selected]
        with summary:
            label = "appearance" if profile["accepted_appearances"] == 1 else "appearances"
            st.markdown(f"**{profile['accepted_minutes']:g} minutes · {profile['accepted_appearances']} {label}**")
    # Reserve the expander above search; fill it from the same engine result below.
    reference_details = st.container()
    with st.container(key="candidate_toolbar"):
        search_column, count_column = st.columns([4, 1], vertical_alignment="bottom")
        with search_column:
            search = st.text_input("Search candidates", key="candidate_search", placeholder="Player or club name").strip().casefold()
        with count_column:
            st.markdown(f"[Shortlist · {len(st.session_state.saved_shortlist)}](#session-shortlist)")
    with st.container(key="candidate_filters"):
        league_column, position_column = st.columns(2)
        leagues = {p["competition_id"]: " / ".join(p["display_names"]["competition"]) for p in profiles.values()}
        positions = sorted({label for p in profiles.values() for label in p.get("observed_positions", [])})
        if any(p.get("observed_position_missing", not p.get("observed_positions")) for p in profiles.values()):
            positions.append("Unavailable")
        with league_column:
            league = st.selectbox("League", [None, *sorted(leagues)], format_func=lambda lid: "All leagues" if lid is None else leagues[lid],
                                  key="candidate_league")
        with position_column:
            position = st.selectbox("Observed position", [None, *positions],
                                    format_func=lambda label: "All observed positions" if label is None else label,
                                    key="candidate_position")
    candidates = discovery_candidates(profiles, cohort["candidates"], search=search, league=league, position=position)
    result = rank_candidates(fit, document, selector(profile), candidates, limit=5)
    with reference_details:
        _render_reference_stats(profile, fit, result)
    with st.container(key="workflow"):
        results_column, shortlist_column = st.columns([2, 1], gap="large")
        with results_column:
            _render_results(result, profile, profiles)
        with shortlist_column:
            pairs = _render_shortlist(document, fit, profile, profiles)
    _render_comparison(profile, profiles, pairs)
    st.caption("Fictional samples of recorded activity. No real-player scouting recommendation or integration is enabled.")
