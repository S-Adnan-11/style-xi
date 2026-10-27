"""Fictional comparison inputs built through the existing importer and profiles."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.synthetic_demo import fixture, player
from style_xi.normalize import CORE
from style_xi.pipeline import import_cache
from style_xi.profiles import build_profiles
from style_xi.similarity import selector
from style_xi.storage import atomic_json


def comparison_snapshots():
    """A declared fictional midfield example; role membership is not inferred."""
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


def make_example(directory=Path("data/similarity"), output=Path("outputs")):
    directory, output = Path(directory), Path(output)
    responses = directory / "responses"
    for i, snapshot in enumerate(comparison_snapshots()):
        atomic_json(responses / f"fictional-{i}.json", snapshot)
    imported = import_cache(responses, output / "fictional-import.json")
    # This labelled boundary fixture exercises missingness after import. The raw
    # validator still rejects missing core counts; its policy is not weakened.
    for row in imported["player_matches"]:
        if row["player_id"] == 901207 and row["match_id"] == 901002:
            del row["counts"]["dribblesTotal"]
    profiles = build_profiles(imported)
    profiles["fictional_example"] = {
        "role_group": "Declared fictional central-midfield examples; no role inferred from counts",
        "missingness_scenario": "One Rumi dribble count intentionally removed after validation to test the profile boundary; not a raw-validator acceptance claim."}
    atomic_json(output / "fictional-profiles.json", profiles)
    regular = [p for p in profiles["profiles"] if p["team_id"] == 900101 and p["stage"] == "regular"]
    cohort = {"schema_version": 1, "fictional": True, "name": "Lantern activity example",
              "scope": {"provider": "highlightly", "competition_id": 900301, "season": 2025, "stage": "regular"},
              "role_group": "Declared fictional central-midfield group",
              "role_player_ids": list(range(901201, 901209)),
              "reference": [selector(p) for p in regular if p["player_id"] <= 901205],
              "candidates": [selector(p) for p in profiles["profiles"]]}
    atomic_json(directory / "cohort.json", cohort)
    return profiles, cohort


if __name__ == "__main__":
    profiles, cohort = make_example()
    print(f"Wrote {len(profiles['profiles'])} fictional profiles and a fixed five-player reference declaration.")
    print("Mira/Neri are identical close patterns; Pax has a different pattern; Quin has genuine zero actions.")
    print("Rumi has a labelled missing-input scenario; Sable has 30 minutes/one appearance; Tavi is outside the declared role group.")
    print("Lumen's other club and playoff are present to test same-player exclusion. No real-player comparison is run.")
