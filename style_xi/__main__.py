"""Run with python -m style_xi. Dry runs never read a credential or call HTTP."""

import argparse
import json
import os
from pathlib import Path

from .acquire import Downloader
from .pipeline import import_cache
from .profiles import profile_file, readable_summary
from .similarity import compare_file, parse_selector, readable_comparison
from .runner import read_plan, run_plan
from .storage import DataError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Style-XⅠ observed-sample data tools")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import-cache", help="Normalize cached envelopes; no network")
    importer.add_argument("--input", type=Path, required=True)
    importer.add_argument("--output", type=Path, required=True)
    profiles = commands.add_parser("profiles", help="Build explainable profiles from an offline import result")
    profiles.add_argument("--input", type=Path, required=True)
    profiles.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare", help="Compare declared fictional profiles using one fixed reference cohort")
    compare.add_argument("--input", type=Path, required=True)
    compare.add_argument("--cohort", type=Path, required=True)
    compare.add_argument("--query", required=True, help="provider/competition/season/stage/club/player")
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--min-minutes", type=float, default=90)
    compare.add_argument("--min-appearances", type=int, default=2)
    compare.add_argument("--limit", type=int, default=5)
    acquire = commands.add_parser("acquire", help="Inspect or run a bounded explicit request plan")
    acquire.add_argument("--plan", type=Path, required=True)
    acquire.add_argument("--state", type=Path, required=True)
    acquire.add_argument("--account", type=Path, required=True)
    acquire.add_argument("--account-history", action="append", type=Path, default=[])
    acquire.add_argument("--cap", type=int, default=50)
    acquire.add_argument("--live", action="store_true", help="Dispatch uncached calls after quota checks")
    args = parser.parse_args(argv)
    try:
        if args.command == "import-cache":
            result = import_cache(args.input, args.output)
            print(json.dumps(result["summary"], sort_keys=True))
        elif args.command == "profiles":
            print(readable_summary(profile_file(args.input, args.output)))
        elif args.command == "compare":
            print(readable_comparison(compare_file(args.input, args.cohort, parse_selector(args.query), args.output,
                                                  args.min_minutes, args.min_appearances, args.limit)))
        else:
            client = Downloader(args.state, args.account, args.cap, args.account_history)
            calls = read_plan(args.plan)
            if not args.live:
                print(json.dumps(client.plan(calls), indent=2))
            else:
                result = run_plan(client, calls, os.environ.get("HIGHLIGHTLY_API_KEY"))
                print(json.dumps({"completed_calls": len(result["completed_call_indexes"]),
                                  "checkpoint": str(args.state / "checkpoint.json")}))
        return 0
    except DataError as error:
        print(json.dumps({"error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
