"""Local, fictional-only presentation over the package's fixed comparison method."""

from collections import Counter

import streamlit as st

from .fictional import fictional_example
from .similarity import FEATURES, fit_reference, identity, rank_candidates, selector

LABELS = {"passes_per_90": "Passes / 90", "dribbles_per_90": "Dribbles / 90",
          "tackles_per_90": "Tackles / 90", "shots_per_90": "Shots / 90"}


@st.cache_resource(show_spinner=False)
def demo_data():
    profiles, cohort = fictional_example()
    return profiles, cohort, fit_reference(profiles, cohort, min_minutes=90, min_appearances=2)


def profile_label(profile):
    names = profile["display_names"]
    stage = "Regular season" if profile["stage"] == "regular" else "Playoff"
    return f"{' / '.join(names['player'])} · {' / '.join(names['team'])} · {stage}"


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
    return {"same_player": "Same player as the selection, including other clubs or stages.",
            "below_min_minutes": "Fewer than 90 accepted minutes in this example.",
            "below_min_appearances": "Fewer than two accepted appearances in this example.",
            "outside_cohort_scope": "Outside this competition, season or regular-season comparison.",
            "outside_declared_role_group": "Outside the declared fictional comparison group.",
            "invalid_or_missing_minutes": "Recorded minutes are unavailable or invalid.",
            "invalid_or_missing_appearances": "Accepted appearances are unavailable or invalid."}.get(reason, "Sample inputs are inconsistent or unavailable.")


def neighbour_rows(result):
    counts = Counter(n["distance"] for n in result["neighbours"])
    distances = sorted(counts)
    return [{"Distance group": f"{distances.index(n['distance']) + 1}" + (" (tie)" if counts[n["distance"]] > 1 else ""),
             "Player": " / ".join(n["candidate"]["display_names"]["player"]),
             "Club": " / ".join(n["candidate"]["display_names"]["team"]),
             "Distance": n["distance"], "Minutes": n["candidate"]["minutes"],
             "Appearances": n["candidate"]["appearances"]} for n in result["neighbours"]]


def _clear_neighbour():
    st.session_state.pop("neighbour", None)


def render_app():
    st.set_page_config(page_title="Style-XⅠ | Recorded patterns", layout="centered")
    st.title("Style-XⅠ")
    st.write("Compare recorded playing patterns.")
    st.info("Fictional data · These players, clubs and statistics are examples.", icon=None)
    document, cohort, fit = demo_data()
    profiles = {identity(selector(p)): p for p in document["profiles"]}
    choices = sorted(profiles, key=lambda key: profile_label(profiles[key]))
    default = next(key for key in choices if key[-1] == 901201 and key[-2] == 900101 and key[3] == "regular")
    selected = st.selectbox("Choose a player", choices, index=choices.index(default),
                            format_func=lambda key: profile_label(profiles[key]), key="query", on_change=_clear_neighbour)
    profile = profiles[selected]
    coverage = profile["coverage"]
    st.subheader("Recorded sample")
    st.write(f"**{profile['accepted_minutes']:g} minutes · {profile['accepted_appearances']} accepted appearances**")
    st.caption(f"{coverage['accepted_player_matches']} of {coverage['collected_player_matches']} collected player matches accepted · "
               f"{coverage['excluded_records']} excluded records · Incomplete match coverage")
    st.dataframe([{"Activity": LABELS[key], "Per 90 minutes": "Unavailable" if profile["metrics"][key]["value"] is None else shown_metric(profile["metrics"][key])}
                  for key, _, _ in FEATURES], hide_index=True, width="stretch", key="sample_rates")
    for key, _, _ in FEATURES:
        if profile["metrics"][key]["value"] is None:
            st.caption(f"{LABELS[key]} is unavailable: {unavailable_reason(profile['metrics'][key].get('reason'))}.")
    if profile["player_id"] == 901207:
        with st.expander("About this fictional sample"):
            st.write("This is an artificial downstream missingness test: one dribble count was removed after raw validation. "
                     "The raw validator still rejects missing core fields; this example tests the profile's unavailable-value handling.")
    result = rank_candidates(fit, document, selector(profile), cohort["candidates"], limit=5)
    with st.expander("Sample and method details"):
        st.write("One declared fictional central-midfield group, competition, season and regular-season stage. "
                 "The fixed example policy needs 90 minutes and two appearances. These are demonstration choices.")
        st.write("The reference contains five fictional profiles and stays fixed when you change selections. "
                 "Activity frequencies can reflect team context and opportunity; this example does not measure player ability.")
        st.json({"selected_identity": selector(profile), "sample_coverage": coverage})
    st.subheader("Nearest eligible patterns")
    st.caption("Lower distance means closer recorded activity patterns.")
    if result["status"] == "ineligible_query":
        st.warning("This sample is unavailable for comparison.")
        for reason in result["query_exclusion_reasons"]:
            st.write("• " + exclusion_text(reason))
        return
    st.caption(f"{result['eligible_candidates']} eligible candidate profiles · "
               f"{len(result['candidate_exclusions'])} excluded · {result['returned_neighbours']} shown")
    with st.expander("Why some profiles are excluded"):
        for item in result["candidate_exclusions"]:
            p = profiles.get(identity(item["identity"]))
            label = profile_label(p) if p else "Unavailable profile"
            st.write(f"**{label}**")
            for reason in item["reasons"]:
                st.write("• " + exclusion_text(reason))
    if not result["neighbours"]:
        st.info("No eligible patterns are available for this selection.")
        return
    rows = neighbour_rows(result)
    st.dataframe(rows, hide_index=True, width="stretch", key="shortlist",
                 column_config={"Distance": st.column_config.NumberColumn(format="%.4f")})
    if any("tie" in row["Distance group"] for row in rows):
        st.caption("Equal distances share a group. Tied examples are equally close under this method.")
    neighbours = {identity(n["candidate"]["identity"]): n for n in result["neighbours"]}
    chosen = st.selectbox("Compare with", list(neighbours), key="neighbour",
                          format_func=lambda key: profile_label(profiles[key]))
    pair = neighbours[chosen]
    st.subheader("Activity side by side")
    st.caption(f"{profile_label(profile)} compared with {profile_label(profiles[chosen])}")
    st.dataframe([{"Activity": LABELS[f["key"]], "Selected / 90": f["query_value"],
                   "Neighbour / 90": f["candidate_value"], "Difference / 90": f["raw_delta"]}
                  for f in pair["features"]], hide_index=True, width="stretch", key="comparison_rates")
    st.caption("Difference = neighbour minus selected player. Each rate uses recorded player minutes.")
    with st.expander("Efficiency context — outside the distance"):
        efficiency = pair["efficiency_context_only"]
        st.dataframe([{"Measure": name.replace("_success_pct", " success").replace("_", " ").capitalize(),
                       "Selected (%)": shown_metric(efficiency["query"][name]),
                       "Neighbour (%)": shown_metric(efficiency["candidate"][name])}
                      for name in efficiency["query"]], hide_index=True, width="stretch")
        st.caption("These observed success percentages do not affect the neighbour order.")
    with st.expander("How this distance is calculated"):
        st.write(f"Distance: {pair['distance']:.6f} · Distance squared: {pair['distance_squared']:.6f}")
        st.caption("Weighted squared contributions add to distance squared, not distance.")
        st.dataframe(pair["features"], hide_index=True, width="stretch")
        st.json({"reference_count": fit.metadata["reference"]["count"], "scaling": fit.metadata["scaling"],
                 "active_features": fit.metadata["active_features"], "inactive_features": fit.metadata["inactive_features"],
                 "reference_data_sha256": fit.metadata["reference"]["data_sha256"]})
        st.write("Small contributions are small measured gaps; they do not show what caused similarity.")
    st.caption("A small fictional sample of activity patterns. No real-player or scouting conclusions are established.")
