"""Render descriptive eligibility coverage, with no individual performance ordering."""

import csv
import io

PAIRS = ((90, 1), (90, 2), (180, 2), (180, 3), (270, 3), (360, 4), (450, 5))


def threshold_csv(study):
    stream = io.StringIO(newline="")
    fields = ("competition_id", "league", "season", "stage", "min_minutes", "min_appearances",
              "source_position_bucket", "denominator", "meeting_thresholds", "fraction")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for group in study["leagues"]:
        for threshold in group["thresholds"]:
            for role in threshold["by_source_position"]:
                writer.writerow({**{k: group[k] for k in fields[:4]},
                    **{k: threshold[k] for k in fields[4:6]}, **role})
    return stream.getvalue()


def render_study(study):
    lines = ["# Private eligibility coverage study", "",
        "Zero provider requests. Real-player rankings and integration remain disabled. All thresholds and the proposed policy are provisional research settings.", "",
        f"{study['cached_matches']} cached matches. Holds removed {study['held_accepted_player_matches']} accepted player-match rows and {study['held_recorded_minutes']} recorded minutes before exposure or label classification; {study['held_only_player_team_samples']} held-only samples leave the study population.", "",
        "Unit: provider / competition / season / stage / team / player. Counts are samples, not unique people. Clubs, seasons and stages are never merged. Percentages describe the current cache, not full-league or full-season coverage. Recorded minutes are retained unchanged.", "",
        "Stable means the same nonmissing source label on every observed accepted unheld appearance. Any missing label gives a missing status; otherwise multiple labels give mixed. Known mixtures with missing observations are also counted separately. Stable labels do not establish tactical or season roles.", ""]

    def table(headers, rows):
        lines.extend(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"])
        lines.extend("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
        lines.append("")

    def lookup(group, pair):
        return next((t for t in group["thresholds"] if (t["min_minutes"], t["min_appearances"]) == pair), None)

    for stage in study["stage_totals"]:
        lines.extend([f"## {stage['season']} / {stage['stage']}", "",
            f"Samples: {stage['unheld_player_team_samples']}; recorded minutes: {stage['recorded_minutes']}; accepted appearances: {stage['appearances']}.",
            f"Position status: {stage['position_status_counts']}. Source-position buckets: {stage['position_bucket_counts']}.", ""])
        table(["Minutes / appearances", "Meeting exposure screen", "Share of samples", "Stable outfield + complete inputs", "With goalkeeper label"],
              [(f"{t['min_minutes']} / {t['min_appearances']}", t["meeting_thresholds"],
                f"{100*t['fraction']:.1f}%" if t["fraction"] is not None else "unavailable",
                t["stable_outfield_complete_inputs"], t["goalkeeper_observed"])
               for pair in PAIRS if (t := lookup(stage, pair)) is not None])
        groups = [g for g in study["leagues"] if (g["season"], g["stage"]) == (stage["season"], stage["stage"])]
        table(["League", "Samples", "Stable", "Mixed", "Missing", "90/2", "180/3", "270/3", "360/4"],
              [(g["league"], g["unheld_player_team_samples"],
                *[g["position_status_counts"][state] for state in ("stable", "mixed", "missing")],
                *[(t["meeting_thresholds"] if (t := lookup(g, p)) else "outside grid") for p in ((90, 2), (180, 3), (270, 3), (360, 4))]) for g in groups])
        for g in [stage, *groups]:
            label = g.get("league", "All leagues, sample counts summed")
            lines.extend([f"### {label}: thresholds by observed source position", ""])
            table(["Position bucket", "Population", *[f"{m}/{a}" for m, a in PAIRS if lookup(g, (m, a))]],
                  [(role, n, *[next(r["meeting_thresholds"] for r in t["by_source_position"] if r["source_position_bucket"] == role)
                               for pair in PAIRS if (t := lookup(g, pair))]) for role, n in g["position_bucket_counts"].items()])

    lines.extend(["## Proposed policy and trade-offs", "",
        "Research proposal only: apply holds and required-field validation first. Keep the existing 90/2 fictional settings provisional. Consider 180 recorded minutes and three accepted appearances as a candidate research screen; compare 270/3 and 360/4 for sensitivity, with 450/5 as a sparsity stress check. This is a coverage/exposure choice, not a validated reliability rule and not permission to run real-player rankings.", "",
        "For an initial single-label outfield study, retain only samples whose accepted unheld appearances all carry the same nonmissing Defender, Midfielder or Forward source label. Keep mixed and missing samples visible in separate audit buckets. Do not choose a majority label, infer a tactical role, duplicate matches across role cohorts, or silently drop mixed observations. Longer samples have more opportunity to reveal mixtures, so report this selection bias.", "",
        "Any observed Goalkeeper label, including a mixed or partly missing sample, requires separate goalkeeper review. Exclude such samples from the outfield screen. Goalkeeper exposure retention does not validate the current outfield features for keepers; no keeper ranking or goalkeeper threshold is enabled.", "",
        "Higher thresholds remove cameos and increase observed exposure but shrink and reshape the pool. Compare source-position retention shares and league counts before selecting a future rule. The balanced collection is incomplete and not a random sample; injury, rotation, substitutions and selection opportunities cannot be inferred from low cache exposure. Single-label stability can be an artefact of one observed appearance. Playoff exposure must not be borrowed to satisfy a regular-season threshold.", ""])
    if review := study.get("minute_evidence_review"):
        lines.extend(["## Existing recorded-minute evidence", "",
            f"Retained cases rechecked: {review['cases_checked']}; all provider values, identities, body pins and pointers reproduced: {review['all_retained_provider_values_reproduced']}.",
            "These are purposive, historical cases. A displayed substitution clock is not exact elapsed exposure. Prior review findings below remain evidence of agreement or unresolved differences, not a numerical accuracy estimate or correction rule.", ""])
        table(["Player / match", "Recorded minutes", "Retained independent finding", "Source"],
              [(f"{c.get('player_name') or c['player_id']} / {c['match_id']}", c["recorded_minutes"], c["retained_review_finding"],
                f"[retained source]({c['independent_source_url']})" if c["independent_source_url"] else "not supplied") for c in review["cases"]])
        for note in review.get("study_notes", []):
            lines.extend([note, ""])
    if archive := study.get("archived_source_checks"):
        lines.extend(["### Retained source integrity", "",
            "The following files were checked locally against the retained manifest. Matching a hash establishes preservation, not event correctness. No webpage was fetched.", ""])
        table(["Archive", "Retained retrieval UTC", "Pinned HTML agrees"],
              [(s["name"], s.get("retrieved_utc"), s["sha256_matches"]) for s in archive["sources"]])
    lines.extend(["## Evidence still needed", "",
        "Independently align complete substitution/entry/exit and final-whistle clocks, including first- and second-half added time, substituted substitutes, dismissals, rounding and extra time. Include starters, brief and repeated cameos, genuine zero-minute appearances, goalkeepers and every league. No uniform minute correction or team 996/1320 invariant is established.", "",
        "Validate whether 180/3 or alternatives produce sufficiently stable rates using broader repeated samples and held-out time blocks, with league and source-position sensitivity. Quantify uncertainty and the bias from excluding mixed positions. Check historical label reliability and develop a separate goalkeeper feature/cohort policy. Continue independent source-field, lineup/coverage and match-hold review. Coverage and arithmetic alone do not validate the method, weights, tactical roles or real comparisons.", "",
        "Artifacts: full threshold grid and failure partitions in study JSON; league-by-position matrix in CSV. Input snapshot and hold-registry digests identify the evidence. No profiles, fitted comparisons, player rankings, gate releases or source-minute edits are produced."])
    return "\n".join(lines) + "\n"
