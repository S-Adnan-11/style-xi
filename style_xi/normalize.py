"""Explicit core counts only. Source accuracy is not inferred from arithmetic."""

from collections import Counter, defaultdict
import math
import re

CORE = tuple("""goalsScored goalsSaved goalsConceded assists dribblesTotal
dribblesSuccessful dribblesFailed fouledByOthers fouledOthers tacklesTotal
interceptionsTotal duelsTotal duelsWon duelsLost passesSuccessful passesFailed
passesTotal passesKey penaltiesScored penaltiesMissed penaltiesTotal shotsOnTarget
shotsOffTarget shotsTotal""".split())
RELATIONS = (
    ("passesTotal", "passesSuccessful", "passesFailed", "passesAccuracy"),
    ("dribblesTotal", "dribblesSuccessful", "dribblesFailed", "dribbleSuccessRate"),
    ("duelsTotal", "duelsWon", "duelsLost", "duelSuccessRate"),
    ("penaltiesTotal", "penaltiesScored", "penaltiesMissed", "penaltiesAccuracy"),
    ("shotsTotal", "shotsOnTarget", "shotsOffTarget", "shotsAccuracy"),
)


def positive_id(value):
    return type(value) is int and value > 0


def mapping(value):
    return value if isinstance(value, dict) else {}


def stage_for(fixture):
    """Only an explicit provider regular-season label is mapped automatically."""
    label = fixture.get("round")
    if isinstance(label, str) and re.fullmatch(r"Regular Season - [1-9][0-9]*", label):
        return "regular"
    if label == "Final":
        return "playoff"
    return "unknown"


def normalize_match(fixture, body, provenance):
    match_id = fixture.get("id")
    league = mapping(fixture.get("league"))
    expected = [mapping(fixture.get(k)).get("id") for k in ("homeTeam", "awayTeam")]
    context = {"provider": "highlightly", "competition_id": league.get("id"),
               "season": league.get("season"), "stage": stage_for(fixture),
               "source_stage": fixture.get("round"), "match_id": match_id}
    invalid_context = (not all(positive_id(x) for x in [match_id, league.get("id"), *expected])
                       or expected[0] == expected[1] or type(league.get("season")) is not int)
    match_reasons = []
    if invalid_context:
        match_reasons.append("invalid_fixture_identity")
    if context["stage"] == "unknown":
        match_reasons.append("unclassified_stage")
    if mapping(fixture.get("state")).get("description") not in (
            "Finished", "Finished after extra time", "Finished after penalties"):
        match_reasons.append("match_not_completed")
    if not isinstance(body, list):
        return [], [{**context, "status": "quarantined", "reasons": ["box_not_list"],
                     "provenance": provenance}]
    team_ids = [mapping(x.get("team")).get("id") for x in body if isinstance(x, dict)]
    if (len(body) != 2 or not all(positive_id(x) for x in team_ids + expected)
            or sorted(team_ids) != sorted(expected)):
        match_reasons.append("team_attachment_mismatch")
    entries = []
    for ti, team in enumerate(body):
        if not isinstance(team, dict) or not isinstance(team.get("players"), list):
            match_reasons.append("players_not_list")
            continue
        for pi, player in enumerate(team["players"]):
            tid = mapping(team.get("team")).get("id")
            entries.append((tid if positive_id(tid) else None, player, f"/{ti}/players/{pi}"))
    occurrences = Counter(p.get("id") for _, p, _ in entries
                          if isinstance(p, dict) and positive_id(p.get("id")))
    accepted, excluded = [], []
    for team_id, player, pointer in entries:
        reasons = list(match_reasons)
        record = {**context, "team_id": team_id, "player_id": None,
                  "minutes": None, "counts": {},
                  "provenance": [{**p, "pointer": pointer} for p in provenance]}
        if not isinstance(player, dict):
            reasons.append("player_not_object")
            player = {}
        pid = player.get("id")
        record["player_id"] = pid if positive_id(pid) else None
        if not positive_id(pid):
            reasons.append("invalid_player_identity")
        elif occurrences[pid] != 1:
            reasons.append("ambiguous_duplicate_player")
        minutes = player.get("minutesPlayed")
        if type(minutes) not in (int, float) or not math.isfinite(minutes) or minutes < 0:
            reasons.append("missing_minutes" if minutes is None else "invalid_minutes")
        else:
            record["minutes"] = minutes
        stats = player.get("statistics")
        if isinstance(stats, list) and len(stats) == 1 and isinstance(stats[0], dict):
            stats = stats[0]
        if not isinstance(stats, dict):
            reasons.append("ambiguous_or_missing_statistics")
            stats = {}
        for field in CORE:
            value = stats.get(field)
            if value is None:
                record["counts"][field] = None
                reasons.append("missing_count:" + field)
            elif type(value) is not int or value < 0:
                record["counts"][field] = None
                reasons.append("invalid_count:" + field)
            else:
                record["counts"][field] = value
        for total, success, failure, rate in RELATIONS:
            t, s, f = (record["counts"][k] for k in (total, success, failure))
            if None not in (t, s, f) and s + f != t:
                reasons.append("inconsistent_counts:" + total)
            displayed = stats.get(rate)
            if displayed is not None:
                if not isinstance(displayed, str) or not re.fullmatch(r"\d+(?:\.\d+)?\s*%", displayed):
                    reasons.append("invalid_rate:" + rate)
                else:
                    supplied = float(displayed.rstrip("% "))
                    decimals = len(displayed.split(".")[1].split()[0].rstrip("%")) if "." in displayed else 0
                    tolerance = 0.5 * 10 ** -min(decimals, 8) + 1e-9
                    if supplied > 100 or (t is not None and s is not None and t > 0
                                          and abs(supplied - 100 * s / t) > tolerance):
                        reasons.append("inconsistent_rate:" + rate)
        if record["minutes"] == 0:
            values = list(record["counts"].values())
            if any(v is not None and v > 0 for v in values):
                reasons.append("zero_minutes_positive_actions")
            elif all(v == 0 for v in values):
                reasons.append("zero_minutes_zero_actions")
        record["reasons"] = sorted(set(reasons))[:48]
        record["status"] = ("excluded" if record["reasons"] == ["zero_minutes_zero_actions"]
                            else "quarantined" if reasons else "accepted")
        (accepted if not reasons else excluded).append(record)
    if match_reasons and not entries:
        excluded.append({**context, "status": "quarantined", "reasons": sorted(set(match_reasons)),
                         "provenance": provenance})
    return accepted, excluded


def aggregate(records):
    """A separate observed-sample row for each club stint and competition stage."""
    keys = ("provider", "competition_id", "season", "stage", "team_id", "player_id")
    groups = defaultdict(list)
    for record in records:
        if record["status"] == "accepted":
            groups[tuple(record[k] for k in keys)].append(record)
    result = []
    for identity, rows in sorted(groups.items()):
        minutes = sum(r["minutes"] for r in rows)
        counts = {k: sum(r["counts"][k] for r in rows) for k in CORE}
        result.append({**dict(zip(keys, identity)), "scope": "observed_sample_incomplete",
                       "minutes": minutes, "counts": counts,
                       "per90": {k: v * 90 / minutes if minutes > 0 else None for k, v in counts.items()},
                       "ratios": {rate: counts[s] / counts[t] if counts[t] else None
                                  for t, s, _, rate in RELATIONS},
                       "contributing_matches": sorted({r["match_id"] for r in rows}),
                       "source_snapshots": sorted({p["snapshot_id"] for r in rows for p in r["provenance"]})})
    return result
