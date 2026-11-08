"""Fictional comparison inputs built through the existing importer and profiles."""

from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from style_xi.fictional import comparison_snapshots, profiles_from_fictional_import
from style_xi.pipeline import import_cache
from style_xi.storage import atomic_json
from style_xi.similarity import fit_reference, rank_candidates, readable_comparison


def make_example(directory=Path("data/similarity"), output=Path("outputs"), *, method_version=2):
    directory, output = Path(directory), Path(output)
    responses = directory / "responses"
    for i, snapshot in enumerate(comparison_snapshots(method_version)):
        atomic_json(responses / f"fictional-{i}.json", snapshot)
    imported = import_cache(responses, output / "fictional-import.json")
    profiles, cohort = profiles_from_fictional_import(imported, method_version=method_version)
    atomic_json(output / "fictional-profiles.json", profiles)
    atomic_json(directory / "cohort.json", cohort)
    return profiles, cohort


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Versioned fictional comparison; no network or private cache")
    parser.add_argument("--method-version", type=int, choices=(1, 2), default=2)
    parser.add_argument("--directory", type=Path, default=Path("data/similarity"))
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    profiles, cohort = make_example(args.directory, args.output, method_version=args.method_version)
    print(f"Wrote {len(profiles['profiles'])} fictional profiles and a fixed five-player reference declaration.")
    print("Mira/Neri are identical close patterns; Pax has a different pattern; Quin has genuine zero actions.")
    print("Rumi has a labelled missing-input scenario; Sable has 30 minutes/one appearance; Tavi is outside the declared role group.")
    print("Lumen's other club and playoff are present to test same-player exclusion. No real-player comparison is run.")
    fit = fit_reference(profiles, cohort, method_version=args.method_version)
    result = rank_candidates(fit, profiles, cohort["reference"][0], cohort["candidates"])
    atomic_json(args.output / f"fictional-neighbours-v{args.method_version}.json", result)
    print(readable_comparison(result))
