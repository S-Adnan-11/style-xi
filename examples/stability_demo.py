"""Runnable fictional v2 stability example; no credentials, private cache or network."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from style_xi.fictional import fixture, player
from style_xi.pipeline import replay_envelopes
from style_xi.stability import check_stability, readable_stability
from style_xi.storage import atomic_json


CUTOFF = "2025-07-01"


def fictional_inputs():
    """Six 60-minute appearances: 90 earlier passes and 108 later passes."""
    dates = ("2025-06-01", "2025-06-08", "2025-06-15", "2025-07-01", "2025-07-08", "2025-07-15")
    fixtures, boxes, calendar = [], [], []
    for index, day in enumerate(dates):
        match = fixture(match=940001 + index)
        match["date"] = day
        match["league"]["name"] = "Fictional Lantern League"
        match["homeTeam"]["name"] = "Mossbridge"
        match["awayTeam"]["name"] = "Paperford"
        fixtures.append(match)
        calendar.append({"provider": "highlightly", "match_id": match["id"], "date": day})
        row = player(pid=940101, minutes=60)
        row["name"] = "Aven Reed (fictional)"
        passes, dribbles, duels, shots = (30, 2, 6, 2) if index < 3 else (36, 4, 4, 0)
        row["statistics"].update(passesTotal=passes, passesSuccessful=passes, passesFailed=0,
                                 dribblesTotal=dribbles, dribblesSuccessful=dribbles, dribblesFailed=0,
                                 duelsTotal=duels, duelsWon=duels // 2, duelsLost=duels // 2,
                                 shotsTotal=shots, shotsOnTarget=shots, shotsOffTarget=0)
        boxes.append({"endpoint": f"https://soccer.highlightly.net/box-score/{match['id']}",
                      "status": 200, "parameters": {},
                      "body": [{"team": match["homeTeam"], "players": [row]},
                               {"team": match["awayTeam"], "players": []}]})
    envelopes = [{"endpoint": "https://soccer.highlightly.net/matches", "status": 200,
                  "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
                  "body": {"data": fixtures, "pagination": {"totalCount": 6, "limit": 10, "offset": 0}}}, *boxes]
    holds = {"version": 1, "cases": {"940001": {"match_id": 940001, "hold_scope": "match",
                                               "analytical_use_allowed": False}}}
    return replay_envelopes(envelopes), calendar, holds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/stability"))
    args = parser.parse_args(argv)
    imported, calendar, holds = fictional_inputs()
    print("Aven Reed is fictional. Six invented matches are replayed through the existing importer.")
    for title, registry, filename in (("Before hold", None, "fictional-stability.json"),
                                      ("After holding first-window match 940001", holds, "fictional-stability-held.json")):
        result = check_stability(imported, match_dates=calendar, cutoff=CUTOFF,
                                 fictional=True, match_holds=registry)
        atomic_json(args.output / filename, result)
        print(title)
        print(readable_stability(result))
    print(f"Wrote fictional reports to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
