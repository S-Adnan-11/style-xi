"""Fictional input for an offline demo. No provider or player observations."""

from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from style_xi.fictional import fixture, player
from style_xi.normalize import CORE
from style_xi.storage import atomic_json


def body():
    return [{"team": {"id": 900101}, "players": [player()]},
            {"team": {"id": 900102}, "players": [player(900202)]}]


def snapshots():
    return [{"status": 200, "endpoint": "https://soccer.highlightly.net/matches",
             "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
             "body": {"data": [fixture()], "pagination": {"limit": 10, "offset": 0, "totalCount": 2}}},
            {"status": 200, "endpoint": "https://soccer.highlightly.net/box-score/900001",
             "parameters": {}, "scope": {"match_id": 900001}, "body": body()}]


def profile_snapshots():
    """Fictional arithmetic examples, including an incomplete collected record."""
    matches = [fixture(), fixture(match=900002), fixture(match=900003, team=900103),
               fixture(match=900004, stage="Final")]
    for match in matches:
        match["league"]["name"] = "Fictional Lantern League"
        match["homeTeam"]["name"] = "Mossbridge" if match["homeTeam"]["id"] == 900101 else "Emberfield"
        match["awayTeam"]["name"] = "Paperford"

    def fictional(pid, name, minutes, **counts):
        result = player(pid, minutes)
        result.update(name=name)
        result["statistics"] = dict.fromkeys(CORE, 0) | counts
        return result

    first = [fictional(900201, "Aster Vale", 30, passesTotal=20, passesSuccessful=10, passesFailed=10),
             fictional(900202, "Bram Quill", 30, dribblesTotal=5, dribblesSuccessful=4, dribblesFailed=1),
             fictional(900203, "Cora Flint", 60, tacklesTotal=5, interceptionsTotal=4,
                       duelsTotal=8, duelsWon=4, duelsLost=4),
             fictional(900204, "Dara Wisp", 0)]
    second = [fictional(900201, "Aster Vale", 90, passesTotal=80, passesSuccessful=72, passesFailed=8, passesKey=2),
              fictional(900202, "Bram Quill", 90, dribblesTotal=15, dribblesSuccessful=6, dribblesFailed=9),
              fictional(900203, "Cora Flint", 30, tacklesTotal=1, duelsTotal=12, duelsWon=9, duelsLost=3)]
    del second[2]["statistics"]["interceptionsTotal"]
    transfer = [fictional(900201, "Aster Vale", 45, passesTotal=5, passesSuccessful=5, passesFailed=0)]
    playoff = [fictional(900201, "Aster Vale", 120, passesTotal=120, passesSuccessful=100, passesFailed=20)]
    page = {"status": 200, "endpoint": "https://soccer.highlightly.net/matches",
            "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
            "body": {"data": matches, "pagination": {"limit": 10, "offset": 0, "totalCount": 6}}}
    result = [page]
    for match, players in zip(matches, (first, second, transfer, playoff)):
        result.append({"status": 200, "endpoint": f"https://soccer.highlightly.net/box-score/{match['id']}",
                       "parameters": {}, "scope": {"match_id": match["id"]},
                       "body": [{"team": match["homeTeam"], "players": players},
                                {"team": match["awayTeam"], "players": []}]})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write fictional football examples; no network or credentials")
    parser.add_argument("--directory", type=Path, default=Path("data/synthetic"))
    args = parser.parse_args()
    destination = args.directory
    for index, snapshot in enumerate(profile_snapshots()):
        atomic_json(destination / f"synthetic-{index}.json", snapshot)
    atomic_json(Path("data/synthetic-plan.json"), {"calls": [
        {"path": "/matches", "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
         "scope": {"competition_id": 900301, "season": 2025, "stage": "all_provider_stages"}}]})
    print(f"Wrote fictional responses to {destination} and a fictional dry-run plan.")
    print("Aster: 120 regular minutes at Mossbridge, 100 passes = 75 per 90; 82/100 = 82% success.")
    print("Bram: 20 dribbles in 120 minutes = 15 per 90; 10/20 = 50% success.")
    print("Cora: one missing-field record is quarantined. Aster's transfer and playoff stay separate.")
