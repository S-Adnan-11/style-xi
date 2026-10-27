# Style-XⅠ

Football player analysis, starting with dependable match data preparation.
The Python package imports cached Highlightly responses, validates player-match
records and produces explicitly incomplete sample aggregates with coverage evidence.
Player similarity, clustering and a dashboard are future work.

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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The example generates fictional IDs and statistics locally. No football dataset,
credential or downloaded response is bundled. Keep runtime inputs under `data/`
and generated outputs under `outputs/`; both are ignored by Git.

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
and [terms](https://highlightly.net/terms/) for your intended use. Basic-specific
retention and public reuse conditions remain unresolved. No data rights or project
code licence are granted by this README.
