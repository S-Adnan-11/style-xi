"""Capture or verify a private evaluation bundle without network access."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def offline(event, args):
    if event.startswith("socket.") and event not in {"socket.__new__", "socket.gethostname"}:
        raise RuntimeError("evaluation_snapshot_network_disabled")


from style_xi.campaign import Campaign
from style_xi.evaluation_snapshot import capture_evaluation_snapshot, verify_evaluation_snapshot
from style_xi.storage import DataError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="Freeze verified local inputs under the collector locks")
    capture.add_argument("--campaign", type=Path, required=True)
    capture.add_argument("--protocol", type=Path, required=True)
    capture.add_argument("--match-holds", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--input-manifest", type=Path, help="Preserve an existing manifest only if every pin matches")
    capture.add_argument("--implementation-file", nargs=2, action="append", default=[], metavar=("LABEL", "PATH"))
    capture.add_argument("--engine-file", nargs=2, action="append", metavar=("LABEL", "PATH"),
                         help="Defaults to the package's Python files")
    capture.add_argument("--code-revision", help="Optional source revision label; file hashes identify actual code")
    verify = commands.add_parser("verify", help="Read only the published frozen bundle")
    verify.add_argument("snapshot", type=Path)
    verify.add_argument("--expected-sha256", help="Snapshot fingerprint returned at capture")
    verify.add_argument("--expected-input-manifest-sha256")
    args = parser.parse_args(argv)
    if args.command == "capture":
        for entries in (args.implementation_file, args.engine_file or []):
            if len({name for name, _ in entries}) != len(entries):
                parser.error("File labels must be unique within each code group")
        engines = (dict(args.engine_file) if args.engine_file is not None
                   else {"style_xi/" + p.name: p for p in sorted((ROOT / "style_xi").glob("*.py"))})
        result = capture_evaluation_snapshot(Campaign(args.campaign), args.output,
            protocol=args.protocol, match_holds=args.match_holds, input_manifest=args.input_manifest,
            implementation_files=dict(args.implementation_file), engine_files=engines,
            code_revision=args.code_revision)
    else:
        result = verify_evaluation_snapshot(args.snapshot, expected_snapshot_sha256=args.expected_sha256,
            expected_input_manifest_sha256=args.expected_input_manifest_sha256)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    sys.addaudithook(offline)
    try:
        main()
    except DataError as error:
        print("Snapshot stopped: " + str(error))
        raise SystemExit(2)
