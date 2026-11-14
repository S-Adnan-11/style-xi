"""Reviewed fictional match counts and a write-free demo builder."""

from copy import deepcopy

from .normalize import CORE
from .pipeline import replay_envelopes
from .profiles import build_profiles
from .similarity import METHOD_VERSION, method_features, selector


def fixture(match=900001, team=900101, season=2025, stage="Regular Season - 1"):
    return {"id": match, "round": stage, "league": {"id": 900301, "season": season},
            "homeTeam": {"id": team}, "awayTeam": {"id": 900102},
            "state": {"description": "Finished"}}


def player(pid=900201, minutes=90):
    counts = dict.fromkeys(CORE, 0)
    counts.update(passesTotal=10, passesSuccessful=8, passesFailed=2)
    return {"id": pid, "minutesPlayed": minutes, "statistics": counts}


def comparison_snapshots(method_version=METHOD_VERSION):
    """A declared fictional midfield example; role membership is not inferred."""
    method_features(method_version)
    patterns = [
        (901201, "Lumen Ash", (40, 4, 2, 2)),
        (901202, "Mira Reed", (42, 4, 2, 2)),
        (901203, "Neri Lark", (42, 4, 2, 2)),
        (901204, "Orin Birch", (10, 0, 6, 0)),
        (901205, "Pax Ember", (80, 10, 0, 8)),
        (901206, "Quin Fern", (0, 0, 0, 0)),
        (901207, "Rumi Mist", (30, 3, 2, 1)),
        (901208, "Sable Wren", (10, 1, 0, 0)),
        (901209, "Tavi Moss", (20, 0, 0, 0)),
    ]

    def appearance(pid, name, pattern, minutes=90):
        passes, dribbles, tackles, shots = pattern
        result = player(pid, minutes)
        result["name"] = name
        # All counted components are written explicitly; these are not profile vectors.
        result["statistics"] = dict.fromkeys(CORE, 0) | {
            "passesTotal": passes, "passesSuccessful": passes, "passesFailed": 0,
            "dribblesTotal": dribbles, "dribblesSuccessful": dribbles, "dribblesFailed": 0,
            "tacklesTotal": tackles, "shotsTotal": shots, "shotsOnTarget": shots, "shotsOffTarget": 0}
        if method_version == 2:
            # Independent fictional source counts; do not relabel tackles as duels.
            duels = {901201: 10, 901202: 12, 901203: 12, 901204: 20, 901205: 4,
                     901206: 0, 901207: 8, 901208: 2, 901209: 5}[pid] if minutes else 0
            result["statistics"].update(duelsTotal=duels, duelsWon=duels // 2, duelsLost=duels - duels // 2)
        return result

    matches = [fixture(match=901001), fixture(match=901002),
               fixture(match=901003, team=900103), fixture(match=901004, stage="Final")]
    for match in matches:
        match["league"]["name"] = "Fictional Lantern League"
        match["homeTeam"]["name"] = "Mossbridge" if match["homeTeam"]["id"] == 900101 else "Emberfield"
        match["awayTeam"]["name"] = "Paperford"
    first = [appearance(pid, name, pattern, 30 if pid == 901208 else 90) for pid, name, pattern in patterns]
    second = [appearance(pid, name, pattern) for pid, name, pattern in patterns if pid != 901208]
    second.append(appearance(901208, "Sable Wren", (0, 0, 0, 0), 0))
    alternate = [appearance(901201, "Lumen Ash", (40, 4, 2, 2))]
    playoff = [appearance(901201, "Lumen Ash", (40, 4, 2, 2), 120)]
    snapshots = [{"endpoint": "https://soccer.highlightly.net/matches", "status": 200,
                  "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
                  "body": {"data": matches, "pagination": {"totalCount": 6, "limit": 10, "offset": 0}}}]
    for match, appearances in zip(matches, (first, second, alternate, playoff)):
        snapshots.append({"endpoint": f"https://soccer.highlightly.net/box-score/{match['id']}", "status": 200,
                          "parameters": {}, "scope": {"match_id": match["id"]},
                          "body": [{"team": match["homeTeam"], "players": appearances},
                                   {"team": match["awayTeam"], "players": []}]})
    return snapshots


def profiles_from_fictional_import(imported, *, method_version=METHOD_VERSION, match_holds=None):
    """Apply the labelled synthetic missingness case without changing raw import."""
    working = deepcopy(imported)
    for row in working["player_matches"]:
        if row["player_id"] == 901207 and row["match_id"] == 901002:
            del row["counts"]["dribblesTotal"]
    method_features(method_version)
    profiles = build_profiles(working, match_holds=match_holds)
    profiles["fictional_example"] = {
        "role_group": "Declared fictional central-midfield examples; no role inferred from counts",
        "missingness_scenario": "One Rumi dribble count intentionally removed after validation to test the profile boundary; not a raw-validator acceptance claim."}
    regular = [p for p in profiles["profiles"] if p["team_id"] == 900101 and p["stage"] == "regular"]
    cohort = {"schema_version": 1, "fictional": True, "name": "Lantern activity example",
              "scope": {"provider": "highlightly", "competition_id": 900301, "season": 2025, "stage": "regular"},
              "role_group": "Declared fictional central-midfield group",
              "role_player_ids": list(range(901201, 901209)),
              "reference": [selector(p) for p in regular if p["player_id"] <= 901205],
              "candidates": [selector(p) for p in profiles["profiles"]]}
    return profiles, cohort


def fictional_example(method_version=METHOD_VERSION):
    """Build reviewed fictional profiles in memory: no paths, credentials or I/O."""
    return profiles_from_fictional_import(replay_envelopes(comparison_snapshots(method_version)),
                                          method_version=method_version)


def fictional_discovery_example():
    """Extend the app catalog; keep the original five v2 reference samples."""
    snapshots = comparison_snapshots(2)
    positions = {901201: "Midfielder", 901202: "Midfielder", 901203: "Midfielder",
                 901204: "Defender", 901205: "Forward", 901206: "Defender",
                 901207: "Midfielder", 901208: "Forward"}

    def extra(pid, name, position, counts):
        row = player(pid)
        passes, dribbles, duels, shots = counts
        row.update(name=name, position=position)
        row["statistics"].update(passesTotal=passes, passesSuccessful=passes, passesFailed=0,
            dribblesTotal=dribbles, dribblesSuccessful=dribbles, dribblesFailed=0,
            duelsTotal=duels, duelsWon=duels, duelsLost=0,
            shotsTotal=shots, shotsOnTarget=shots, shotsOffTarget=0)
        return row

    for box in snapshots[1:]:
        for side in box["body"]:
            for row in side["players"]:
                row["position"] = positions.get(row["id"])
        if box["scope"]["match_id"] in (901001, 901002):
            box["body"][0]["players"].append(extra(901210, "Vela Dawn", "Forward", (120, 20, 40, 16)))
    matches = [fixture(match=902001), fixture(match=902002)]
    for match in matches:
        match["league"].update(id=900302, name="Fictional Meadow League")
        match["homeTeam"].update(id=900104, name="Briarhaven")
        match["awayTeam"]["name"] = "Dewford"
    snapshots.append({"endpoint": "https://soccer.highlightly.net/matches", "status": 200,
        "parameters": {"leagueId": 900302, "season": 2025, "limit": 10, "offset": 0},
        "body": {"data": matches, "pagination": {"totalCount": 2, "limit": 10, "offset": 0}}})
    for match in matches:
        snapshots.append({"endpoint": f"https://soccer.highlightly.net/box-score/{match['id']}", "status": 200,
            "parameters": {}, "scope": {"match_id": match["id"]},
            "body": [{"team": match["homeTeam"], "players": [
                extra(902201, "Ivo Vale", "Forward", (200, 24, 50, 16)),
                extra(902202, "Zuri Elm", "Defender", (180, 12, 44, 10))]},
                {"team": match["awayTeam"], "players": []}]})
    imported = replay_envelopes(snapshots)
    document, cohort = profiles_from_fictional_import(imported, method_version=2)
    # Source labels are joined on accepted identity/match keys, never action rates.
    source_positions = {(box["scope"]["match_id"], side["team"]["id"], row["id"]): row.get("position")
                        for box in snapshots if "/box-score/" in box["endpoint"]
                        for side in box["body"] for row in side["players"]}
    for profile in document["profiles"]:
        labels = [source_positions[(mid, profile["team_id"], profile["player_id"])]
                  for mid in profile["contributing_match_ids"]]
        profile["observed_positions"] = sorted({label.strip() for label in labels if isinstance(label, str) and label.strip()})
        profile["observed_position_missing"] = not labels or any(not isinstance(label, str) or not label.strip() for label in labels)
    cohort["name"] = "Fictional discovery catalog"
    cohort["role_group"] = "Explicit fictional discovery examples; observed labels are not tactical roles"
    document["fictional_example"]["role_group"] = cohort["role_group"]
    cohort["role_player_ids"].extend([901210, 902201, 902202])
    cohort["discovery_scopes"] = [{**cohort["scope"], "competition_id": 900302}]
    return document, cohort
