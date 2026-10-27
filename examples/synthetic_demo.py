"""Fictional input for an offline demo. No provider or player observations."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from style_xi.normalize import CORE
from style_xi.storage import atomic_json


def fixture(match=900001, team=900101, season=2025, stage="Regular Season - 1"):
    return {"id": match, "round": stage, "league": {"id": 900301, "season": season},
            "homeTeam": {"id": team}, "awayTeam": {"id": 900102},
            "state": {"description": "Finished"}}


def player(pid=900201, minutes=90):
    counts = dict.fromkeys(CORE, 0)
    counts.update(passesTotal=10, passesSuccessful=8, passesFailed=2)
    return {"id": pid, "minutesPlayed": minutes, "statistics": counts}


def body():
    return [{"team": {"id": 900101}, "players": [player()]},
            {"team": {"id": 900102}, "players": [player(900202)]}]


def snapshots():
    return [{"status": 200, "endpoint": "https://soccer.highlightly.net/matches",
             "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
             "body": {"data": [fixture()], "pagination": {"limit": 10, "offset": 0, "totalCount": 2}}},
            {"status": 200, "endpoint": "https://soccer.highlightly.net/box-score/900001",
             "parameters": {}, "scope": {"match_id": 900001}, "body": body()}]


if __name__ == "__main__":
    destination = Path("data/synthetic")
    for index, snapshot in enumerate(snapshots()):
        atomic_json(destination / f"synthetic-{index}.json", snapshot)
    atomic_json(Path("data/synthetic-plan.json"), {"calls": [
        {"path": "/matches", "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
         "scope": {"competition_id": 900301, "season": 2025, "stage": "all_provider_stages"}}]})
    print("Wrote fictional responses to data/synthetic and a fictional dry-run plan.")
