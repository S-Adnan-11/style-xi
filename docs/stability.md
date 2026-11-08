# Offline fictional window stability

Run the example and focused tests from the repository root:

```powershell
.\.venv\Scripts\python.exe examples/stability_demo.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_stability.py -v
```

On Linux, replace the interpreter path with `.venv/bin/python`. The example builds
fictional source envelopes in memory, replays the existing importer, and calls
`build_profiles()` separately for each window. It reads no private cache or
credential and makes no network request. `--output <directory>` changes its output
directory; the default is `outputs/stability/`.

The two reports are `fictional-stability.json` and `fictional-stability-held.json`.
The first has one qualifying sample; the second has zero after holding match
940001. The invented player, Aven Reed, has three 60-minute appearances per window.
The explicit cutoff is `2025-07-01`: dates before it enter the earlier window;
dates on or after it enter the later window.

| V2 feature | Earlier / 90 | Later / 90 | Absolute change |
| --- | ---: | ---: | ---: |
| Passes | 45 | 54 | 9 |
| Dribbles | 3 | 6 | 3 |
| Provider-recorded duels | 9 | 6 | 3 |
| Shots excluding blocks | 3 | 0 | 3 |

Passing totals are 90 earlier and 108 later, each over 180 recorded minutes. After
the hold, the earlier window has 120 minutes and two appearances; its reasons are
`below_min_minutes` and `below_min_appearances`. The later window still qualifies.
Available rates remain visible for inspection, but changes and their aggregate
statistics become unavailable when either window fails.

## Reusable API

```python
from style_xi.stability import check_stability, readable_stability

result = check_stability(
    import_result,
    match_dates=[
        {"provider": "highlightly", "match_id": 940001, "date": "2025-06-01"},
        # One explicit entry per unheld accepted match, including the later window.
    ],
    cutoff="2025-07-01",
    fictional=True,
    match_holds=hold_registry,  # Or None when no registry is supplied.
)
print(readable_stability(result))
```

`import_result` is the existing schema-version-1 importer result. Its accepted
records are the analytical inputs; excluded records never supply exposure or
actions. The fixture calendar is explicit because normalized imports do not
retain source dates. Dates must be canonical `YYYY-MM-DD` calendar dates in one
declared convention, such as UTC. Missing, invalid or duplicate unheld dates fail
with a diagnostic. The check never guesses dates from IDs, record order or
retrieval times. Held dates are ignored and need not be present.

The version-1 registry uses the same `held_matches()` rules as profile building.
An active provider/match hold removes both teams before dates, minutes,
appearances and action denominators are considered. Released cases remain usable.
The report records the registry digest, held IDs and removed player-match count.
No private registry is discovered implicitly. Input objects remain unchanged.

The sample key is **provider / competition / season / stage / team / player**.
Another league, season, stage, club or player cannot complete either window.
Repeated identical player-match rows do not add appearances; conflicting rows
fail through the profile aggregator. A missing window has zero minutes and
appearances. Held-only identities remain visible as failures in both windows.
`summary.samples` counts all accepted-input identities, including held-only ones;
these are player-team samples, not unique people or full-season coverage.

Each window independently needs at least **180 recorded minutes and three
accepted appearances**. The check also reuses v2 `eligibility()` validation of
complete finite per-90 features and consistent input/exposure coverage. No
missing value is imputed, and genuine zero activity remains valid. This is an
exposure and feature-input screen; no tactical role is assigned or validated.
It does not change the comparison or interface's provisional 90/2 settings.

Rates use **90 times summed counts divided by summed recorded minutes**. They are
not averages of match rates. For samples passing in both windows, each feature's
change is `abs(later_rate - earlier_rate)`, in actions per 90 recorded minutes.
Features come directly from the v2 contract: passes, dribbles, provider-recorded
duels, and shots excluding blocks. Tackles and success percentages do not enter
this check. There is no fit, standardization, weighting, distance or ranking.

`samples` reports full identity, both windows' exposure, match IDs, metric values
and coverage, qualification reasons, failed windows and absolute changes. The
summary reports total/qualifying/ineligible counts, held-only samples, counts of
failures in each window, and each feature's qualifying count, minimum, mean,
median and maximum absolute change. Window failure counts may overlap. Every
feature uses the same fully qualifying sample set. Empty distributions have
count zero and null statistics. JSON retains calculation precision; the readable
report rounds only its display. Outputs are deterministic without timestamps.

## Real-player gate

The API rejects inputs without an explicit `fictional=True` declaration before
building profiles. As with the existing fictional cohort declaration, this
documents provenance; it cannot detect relabelled real data. Use only fictional
fixtures. Reports retain `real_player_rankings_allowed: false` and
`real_integration_allowed: false`. No real-player profile, fit or ranking workflow
is enabled, and no real cache is read by the example.

180/3 is a candidate research screen, not a validated reliability policy. Small
changes do not establish accuracy or a stable playing style; large changes can
reflect exposure, opponent, role, team or opportunity effects. There is no
validated tolerance classifying a sample as stable. The [existing eligibility
study](eligibility-study.md) and [comparison limitations](similarity.md) still
apply, including source semantics, recorded-minute uncertainty, role review,
independent coverage and unresolved holds. This fictional arithmetic check does
not clear any real-player analysis gate.
