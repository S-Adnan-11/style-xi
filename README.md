# Style-XⅠ

Football player analysis, starting with dependable match data preparation.
The Python package imports cached Highlightly responses, validates player-match
records and produces explainable sample profiles with counts, actions per 90,
supported success percentages and explicit field and match coverage.
A fictional nearest-neighbour prototype compares activity patterns and explains each
distance. Real-player similarity, clustering and a dashboard remain future work.

## Setup

The existing environment targets standard CPython 3.15.1 on Windows x64:

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: --require-hashes -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Run commands from the repository root. The importer uses Python's standard library;
the hash-pinned requirements also include the project's numerical and UI libraries.
Other Python versions and platforms are untested.

## Offline example

```powershell
.\.venv\Scripts\python.exe examples/synthetic_demo.py
.\.venv\Scripts\python.exe -m style_xi import-cache --input data/synthetic --output outputs/sample.json
.\.venv\Scripts\python.exe -m style_xi profiles --input outputs/sample.json --output outputs/profiles.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The example generates fictional IDs and statistics locally. No football dataset,
credential or downloaded response is bundled. Keep runtime inputs under `data/`
and generated outputs under `outputs/`; both are ignored by Git.

The CLI prints a readable summary and writes structured profiles. All names, clubs,
competitions, IDs and statistics in the example are fictional. Aster Vale records
100 passes over 120 accepted minutes: 75 passes per 90, with 82 successful out of
100 for 82% success. Bram Quill records 20 dribbles over 120 minutes, with 50%
success. Cora Flint has a collected row with a missing interception count, so that
entire row is quarantined and her profile shows only one of two collected player
matches accepted. Aster's other club and playoff sample stay separate.

Use `build_profiles(import_result)` from `style_xi.profiles` for the reusable API.
It consumes the existing import result, retaining player, club, competition,
season and stage IDs. Names are display labels only. Each metric reports valid-input
rows against eligible accepted rows; each profile also reports attributable
exclusions and provider-manifest coverage. A zero-attempt ratio is unavailable,
with a reason. Missing metric inputs never become zero or partial full-scope totals.
See the [metric contract and profile schema](docs/profiles.md) for formulas,
required fields, definitions and limitations.

## Fictional activity comparison

```powershell
.\.venv\Scripts\python.exe examples/similarity_demo.py
.\.venv\Scripts\python.exe -m style_xi compare --input outputs/fictional-profiles.json --cohort data/similarity/cohort.json --query highlightly/900301/2025/regular/900101/901201 --min-minutes 90 --min-appearances 2 --limit 5 --output outputs/neighbours.json
```

This example uses the existing importer and profile functions with fictional match
counts. Its declared reference has five fictional midfield examples in one competition,
season and regular-season stage. The fixed features are passes, dribbles, tackles and
shots per 90, with equal family weights. The result includes reference means/scales,
eligibility decisions, raw and standardized deltas and each squared-distance contribution.
**Lower distance means closer recorded activity patterns**, not greater player ability.

Mira and Neri tie as close patterns; a genuine zero-activity profile remains eligible.
Missing-input and short samples are excluded, as are the query player's other club
and playoff. The missing-input fixture is explicitly labelled: one count is removed
after raw validation to exercise the existing profile missingness boundary. Raw-record
acceptance rules remain unchanged. All generated files are ignored and require no
credentials, private files or network. See [the comparison contract](docs/similarity.md)
for the numerical method, cohort format, limitations and reusable API.

## Bounded acquisition

Inspect an explicit request plan without accessing a credential or the network:

```powershell
.\.venv\Scripts\python.exe -m style_xi acquire --plan data/synthetic-plan.json --state data/acquisition --account data/account.json
```

This generated plan uses fictional IDs and is for dry runs only. For actual
acquisition, supply a plan containing at most 50 explicit `calls`, each with
`path`, `parameters` and `scope`. Supported paths are `/matches` and
`/box-score/{matchId}`. Match parameters are `leagueId`, `season`, `limit` and
`offset`. Scope must include `competition_id`, `season` and `stage`; match-list
scope uses `all_provider_stages` because the endpoint mixes stages.

See [acquisition and recovery](docs/acquisition.md) for the plan and account-state
formats. Only `--live` dispatches uncached calls, using `HIGHLIGHTLY_API_KEY` from
the process environment. Supply credentials through your local secret loader;
never place them in a plan, argument, URL or committed file.

The downloader reserves every attempted request before dispatch. Its persistent
budget is at most 50 calls, including failures, across invocations using the same
state directory. Use a single shared account file for all participating clients,
and provide existing usage ledgers with repeatable `--account-history` options.
It requires a balance observed within five minutes on the same UTC day, accounts
for subsequent known usage, and retains ten daily requests. It never guesses a
quota reset. Unknown current balance stops acquisition.

Requests are sequential with a 20-second socket timeout, an 8 MiB response limit,
no automatic retries and no redirect following. HTTP errors, provider errors,
unexpected plans and uncertain interrupted requests stop the run. Successful
responses are cached atomically, with retrieval times, body hashes and nonsecret
request identities. A completed cache hit uses no credential and spends no quota.
Conflicting cached snapshots are retained and require review.

The runner checkpoints coverage after each response. It records page offsets,
limits, listed match IDs and acquisition state; it detects repeated/empty pages,
duplicate IDs, changed snapshots, inconsistent totals and incomplete pages.
It runs only the supplied calls and does not schedule or expand a harvest.

## Inputs and outputs

`import_cache(input_directory, output_file)` reads JSON response envelopes with
`endpoint`, `status`, `parameters` and `body`. Retrieval time and nonsecret `scope`
can accompany each envelope. Both match-list and box-score responses are needed:
box scores alone do not establish competition, season or stage. New cache envelopes
with `stored_body_sha256` are checked before import. Older envelopes without that
field are accepted as unverified inputs and assigned deterministic snapshot IDs.

The result contains accepted `player_matches`, `excluded_records`, match-level
diagnostics, `sample_aggregates` and `coverage`. Records identify the provider,
competition, season, source stage, match, team stint, player and contributing source
snapshots. Use IDs to join records. Current player metadata is never used to infer
historical club membership.

Only explicit `Regular Season - N` labels map to `regular`; `Final` maps to
`playoff`. Other labels are quarantined for classification. Regular and playoff
aggregates stay separate. A transfer produces separate club rows.

## Validation policy

The core input allowlist is `style_xi.normalize.CORE`: counted passing, dribbling,
duel, shooting, penalty, defending, goalkeeping, goal, assist and foul measures.
New numeric fields never become inputs automatically. Expected/modelled goal and
assist fields, all card fields, ratings and appearance flags are excluded from
analytical records. Model and card interpretations need separate source validation.

Minutes must be finite and nonnegative; counts must be nonnegative integers.
Missing values stay unavailable and quarantine a record. Successful/failed/total
relationships and available displayed percentages are checked at their supplied
precision. Statistics objects and singleton arrays are supported; ambiguous arrays,
duplicate player entries and conflicting response snapshots are quarantined.
Exact repeated snapshots add provenance without adding analytical rows.

Zero minutes with zero core actions is retained as excluded evidence. Zero minutes
with positive core actions requires investigation. Positive minutes without actions
is allowed. Excluded and quarantined rows never contribute to aggregates.

Aggregates sum validated counts and observed minutes within each club stint,
player, season, competition and stage. Ratios use summed successes and attempts;
zero denominators produce JSON `null`. Per-90 values use observed minutes, with no
invented eligibility threshold. They remain **incomplete sample aggregates**.

Coverage reports acquired pages, listed match IDs, missing box scores and gaps.
A complete provider list requires contiguous, consistent pages with unique IDs;
an HTTP 200 or advertised total alone is insufficient. Provider completeness does
not establish independently expected competition coverage or box-score accuracy.

These checks establish structure and internal consistency where possible, not
independent accuracy, complete seasons or a validated playing-style model.
Review [Highlightly's field definitions](https://highlightly.net/football-api/documentation/box-score/)
for the source schema. No project code licence has been selected.

## Data and credits

Football statistics for Style-XⅠ come from [Highlightly](https://highlightly.net/football-api/). I contacted their team to clarify the permissions for this project, and they confirmed that their Basic plan allows collecting and retaining statistics, building player analyses, and displaying statistics and derived comparisons publicly—including at hackathons with prizes.

Thanks to the Highlightly team for providing the API and clarifying these permissions. Raw API responses remain private and aren’t redistributed. Their [terms](https://highlightly.net/terms/) also restrict API resale, pass-through services and competing databases or services.

The demos use invented players and statistics. This permission does not establish
data accuracy, complete coverage, a partnership or endorsement.
