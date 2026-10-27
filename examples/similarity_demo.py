"""Fictional comparison inputs built through the existing importer and profiles."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from style_xi.fictional import comparison_snapshots, profiles_from_fictional_import
from style_xi.pipeline import import_cache
from style_xi.storage import atomic_json


def make_example(directory=Path("data/similarity"), output=Path("outputs")):
    directory, output = Path(directory), Path(output)
    responses = directory / "responses"
    for i, snapshot in enumerate(comparison_snapshots()):
        atomic_json(responses / f"fictional-{i}.json", snapshot)
    imported = import_cache(responses, output / "fictional-import.json")
    profiles, cohort = profiles_from_fictional_import(imported)
    atomic_json(output / "fictional-profiles.json", profiles)
    atomic_json(directory / "cohort.json", cohort)
    return profiles, cohort


if __name__ == "__main__":
    profiles, cohort = make_example()
    print(f"Wrote {len(profiles['profiles'])} fictional profiles and a fixed five-player reference declaration.")
    print("Mira/Neri are identical close patterns; Pax has a different pattern; Quin has genuine zero actions.")
    print("Rumi has a labelled missing-input scenario; Sable has 30 minutes/one appearance; Tavi is outside the declared role group.")
    print("Lumen's other club and playoff are present to test same-player exclusion. No real-player comparison is run.")
