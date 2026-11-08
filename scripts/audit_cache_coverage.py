"""Read-only private cache audit. An explicit output path is optional."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from style_xi.campaign import Campaign
from style_xi.coverage_audit import audit_coverage
from style_xi.eligibility_study import APPEARANCE_GRID, MINUTE_GRID, check_minute_cases, study_eligibility
from style_xi.study_report import render_study, threshold_csv
from style_xi.storage import atomic_json, read_json


def main():
    parser = argparse.ArgumentParser(description="Offline field, exposure and role coverage audit; no rankings")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--match-holds", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--study", action="store_true", help="Study threshold sensitivity and observed positions; never enable rankings")
    parser.add_argument("--minute-thresholds", type=int, nargs="+", default=MINUTE_GRID)
    parser.add_argument("--appearance-thresholds", type=int, nargs="+", default=APPEARANCE_GRID)
    parser.add_argument("--minutes-evidence", type=Path, help="Existing field-evidence JSON with retained minutes_cases")
    parser.add_argument("--source-manifest", type=Path, help="Existing local public-source manifest; verify archived HTML without fetching")
    parser.add_argument("--report", type=Path, help="Private study Markdown report")
    parser.add_argument("--threshold-csv", type=Path, help="Private league/source-position threshold matrix")
    args = parser.parse_args()
    if not args.study and any((args.minutes_evidence, args.source_manifest, args.report, args.threshold_csv)):
        parser.error("study evidence/report options require --study")
    campaign = Campaign(args.manifest)
    snapshots, holds = campaign.snapshots(), read_json(args.match_holds)
    result = audit_coverage(snapshots, match_holds=holds)
    if args.study:
        result = {**study_eligibility(snapshots, match_holds=holds, minute_grid=args.minute_thresholds,
                                      appearance_grid=args.appearance_thresholds), "coverage_audit": result}
        if args.minutes_evidence:
            evidence = read_json(args.minutes_evidence)
            result["minute_evidence_review"] = check_minute_cases(snapshots, evidence["minutes_cases"],
                                                                 match_holds=holds)
            result["minute_evidence_review"]["evidence_file_sha256"] = hashlib.sha256(args.minutes_evidence.read_bytes()).hexdigest()
            result["minute_evidence_review"]["study_notes"] = evidence.get("study_notes", [])
        if args.source_manifest:
            checks = []
            for source in read_json(args.source_manifest):
                name = source["name"]
                if not isinstance(name, str) or any(c in name for c in ("/", "\\")) or name in (".", ".."):
                    parser.error("invalid local archived source name")
                path = args.source_manifest.parent / (name + ".html")
                actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
                checks.append({"name": name, "requested_url": source["requested_url"],
                    "retrieved_utc": source["retrieved_utc"], "sha256": actual, "expected_sha256": source["sha256"],
                    "sha256_matches": actual == source["sha256"]})
            result["archived_source_checks"] = {"manifest_sha256": hashlib.sha256(args.source_manifest.read_bytes()).hexdigest(),
                                                "sources": checks, "new_fetches": 0}
        for path, content in ((args.report, render_study(result)), (args.threshold_csv, threshold_csv(result))):
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    if args.output:
        atomic_json(args.output, result)
    else:
        print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
