# Fictional activity neighbours

This prototype tests a transparent comparison method on constructed football counts.
It is not validated player scouting. Only a declared fictional cohort is supported;
the declaration documents the example's provenance, not automatic detection of real
versus fictional people. Do not use it as evidence for real-player recommendations.

## End-to-end example

From the repository root, using the existing environment:

```powershell
.\.venv\Scripts\python.exe examples/similarity_demo.py
.\.venv\Scripts\python.exe -m style_xi compare --input outputs/fictional-profiles.json --cohort data/similarity/cohort.json --query highlightly/900301/2025/regular/900101/901201 --min-minutes 90 --min-appearances 2 --limit 5 --output outputs/neighbours.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Existing `synthetic_demo.py`, `import-cache` and `profiles` commands continue to work.
The new example writes fictional raw envelopes under `data/similarity/responses/`,
uses `import_cache()` and `build_profiles()`, and saves `outputs/fictional-import.json`,
`outputs/fictional-profiles.json` and `data/similarity/cohort.json`. It needs no key or
network. The valid comparison rows all come from the existing pipeline, rather than
a separate table of manually entered profile vectors.

Rumi's missingness example deliberately removes one dribble count **after validation**,
before `build_profiles()`, exercising its defensive calculation boundary. This labelled
fixture is not a claim that raw validation accepts missing core fields. The saved raw
import remains unmodified; the generated profile document explains the boundary scenario.
Sable has 30 minutes and one accepted appearance. The query's other club and playoff
are present but excluded. Tavi is outside the declared fictional role membership.
Mira and Neri have identical values under different identities and remain valid ties.
Quin has positive recorded exposure and genuinely zero activity; Euclidean distance
does not require a nonzero activity vector.

## Fixed feature contract, version 2

Ordered inputs, all in actions per 90 recorded player minutes:

| Key | Family | Source meaning | Default weight |
| --- | --- | --- | --- |
| `passes_per_90` | passing | Recorded pass attempts | 0.25 |
| `dribbles_per_90` | dribbling | Recorded dribble attempts | 0.25 |
| `duels_per_90` | duels | Provider-recorded duel contests, requiring total/won/lost counts | 0.25 |
| `shots_per_90` | shooting | **Shots excluding blocks**: player on-target plus off-target counts | 0.25 |

These four existing profile metrics give one frequency per action family. Equal family
weights are an initial design choice, not a learned or football-validated optimum.
There is one feature per family, so no within-family split is needed. Additional profile
metrics remain available outside the distance. No raw totals, constituent counters,
minutes, appearances, goals, assists, efficiencies, ratings, cards or modelled fields
are selected. Unrecognized cohort configuration fields are rejected; there is no generic
numeric-feature discovery or feature/weight tuning interface.

Passing, dribbling and duel success percentages are shown in JSON as
`efficiency_context_only`. They never affect eligibility for activity features, scaling,
distance or order. These are efficiency observations, not an ability score.
No pressing, progression, tactical movement or possession adjustment is inferred.

## Cohort, identity and eligibility

The cohort file declares `schema_version: 1`, `fictional: true`, a `name`, a `role_group`,
explicit `role_player_ids`, a four-field `scope`, and separate `reference` and `candidates`
identity lists. Scope is one provider, competition, season and regular-season stage.
The role group is an example fact, not inferred from action counts. The generated cohort
file is a runnable format example; all identity lists use the six fields below.

Every selector must give `provider`, `competition_id`, `season`, `stage`, `team_id`,
`player_id`. CLI selectors use that exact slash-separated order. Names or player ID
alone cannot select a profile. Duplicate full identities are errors. Club/stage identity
is never merged. Recommendations exclude the query player across every club and stage.

Eligibility requires positive finite accepted minutes, a positive integer accepted
appearance count, matching unique contributing match IDs and consistent feature-coverage
metadata. Every configured feature must be finite, nonnegative, have the expected unit,
have no unavailability reason/issues, and cover all accepted appearances and minutes.
All configured inputs remain mandatory even if a reference feature is later inactive.
Missing values are not imputed and different pairs cannot use different feature subsets.
Manifest completeness is not an eligibility threshold; unavailable coverage stays null.

The example defaults are **90 minutes and two appearances**, exposed as `--min-minutes`
and `--min-appearances`. They are **provisional demonstration thresholds**, not reliability
policy or real-player eligibility rules. Version-2 `query_eligibility` and
`candidate_eligibility` include actual exposure, provisional threshold values, reasons,
feature availability, missing source fields and observed/eligible feature coverage.
Reference exclusions include the same detail. Missing fields and short samples remain
visible; absent values are never imputed.
Minutes/appearances affect eligibility only. At least three eligible reference profiles
and two varying features are operating safeguards, not statistical-reliability evidence.
The reference permits at most one declared profile per player; alternate reference spells
are rejected rather than silently choosing a club. Reference exclusions retain reasons.

An ineligible query returns `ineligible_query` with no ranking. A missing/ambiguous query
selector fails clearly. No eligible candidates returns `no_eligible_candidates`; short
lists return their actual length, with no padding. `--limit` must be a positive integer.

## Scaling and distance

The declared eligible reference is sorted canonically and fitted once, using population
standard deviation (`ddof=0`). A query may be in that reference; this example's query is.
Candidates and queries use the same fixed parameters. Filtering candidates or asking a
different query never refits them. Changing the reference is an explicit new fit, and
its distances need not be comparable to those from the previous reference.

```text
mean_j = sum(reference_j) / reference_count
std_j  = sqrt(sum((reference_j - mean_j)^2) / reference_count)
z_j(x) = (x_j - mean_j) / std_j
contribution_j(q,c) = weight_j * (z_j(c) - z_j(q))^2
distance(q,c) = sqrt(sum(contribution_j(q,c)))
```

The implementation uses standard-library `math.fsum` and `sqrt`. Reference values are
scaled by their maximum before variance calculation to reduce numerical overflow and
underflow. A feature is globally inactive when all reference values are zero or
`population_std / reference_max <= 1e-12`. This relative rule remains consistent under
multiplicative unit changes. If an otherwise varying scale cannot be represented, or
a comparison overflows, the operation fails with a numerical diagnostic; it does not
silently drop another feature, clip values or emit nonfinite JSON.

Inactive features have weight zero. The remaining equal family weights are renormalized
once to sum to one; fewer than two active features stops fitting. All configured raw
values and signed deltas remain visible, including differences on inactive fields.
Their standardized delta is null and their contribution is zero. Equal distance does
not imply agreement on dropped fields. Zero and near-constant columns are handled at
fit time globally, never separately for a pair.

Signed differences are candidate minus query. Contributions sum to **distance squared**,
not distance. Ranking uses unrounded distance, then full candidate identity for exact
ties. Only display values are rounded. The two smallest and two largest active-feature
contributions identify measured gaps; ties use contract order. They do not establish
that a feature caused similarity. Inactive raw differences are reported separately.

## Reusable API and output

```python
fit = fit_reference(profile_document, cohort, min_minutes=90, min_appearances=2, method_version=2)
result = rank_candidates(fit, profile_document, query_identity, candidate_identities, limit=5)
# Reuse fit for another declared eligible query or a smaller candidate pool.
```

Import these functions from `style_xi.similarity`. `explain_pair()` checks eligibility
and explains an individual pair under an existing fit. `fit.metadata` returns a fresh
plain-data copy, so modifying that copy cannot change the fit. Fit state is in memory;
there is no pickle/joblib loading, separate fit-state file or model registry.

Result schema version 1, kind `fictional_activity_neighbours`, includes the fictional
marker, contract/settings, ordered active/inactive keys, reference identities/count/
digest, reference exposure/coverage context, means/scales, final weights, query/candidate
identity/exposure/coverage, exclusion lists/counts and neighbour explanations. Each
neighbour has unrounded `distance`, `display_distance`, `distance_squared`, raw values,
signed and standardized deltas and weighted squared contributions. The full output is
deterministic JSON with no timestamps. Unknown coverage is explicit, not upgraded.

Distances depend on this small artificial reference, chosen features, weighting and
sample scope. Standardization is outlier-sensitive and does not remove role, team,
opportunity or data-quality effects. Future real position and competition comparability
remain uncertain. No distance is converted to a similarity percentage, probability,
confidence interval, quality ranking or calibrated scouting score. This prototype does
not establish that this algorithm is best or ready for real scouting.


## Revision and original-method reproduction

Version 2 is the API, CLI, demo and interface default. Only the feature contract and
shot label change: fixed reference, population scaling, constant handling and equal
weights remain. Tackle values cannot affect version-2 eligibility, scaling or distance.
Duels are provider-recorded counts, without established cross-supplier equivalence.
No player blocked-shot counter is invented or borrowed from team statistics.

The demo prints each feature's contribution and writes `outputs/fictional-neighbours-v2.json`.
Its version-2 inputs contain separate fictional duel total/won/lost counts; these are
not renamed tackles. Lumen Ash versus Pax Ember under the fixed five-player reference:

| Feature | Lumen / 90 | Pax / 90 | Standardized difference | Weighted squared contribution |
| --- | ---: | ---: | ---: | ---: |
| Passes | 40 | 80 | 1.800122 | 0.810110 |
| Dribbles | 4 | 10 | 1.875000 | 0.878906 |
| Provider-recorded duels | 10 | 4 | -1.171303 | 0.342988 |
| Shots excluding blocks | 2 | 8 | 2.211629 | 1.222826 |

The unrounded contributions sum to **3.254830316818368**; their square root gives
distance **1.804114829166472**. The interface shows the same calculation under
"How this distance is calculated." This demonstrates arithmetic, not player quality.

To reproduce version 1, select it for both source generation and comparison, using
separate directories so original and revised data remain side by side:

```powershell
.\.venv\Scripts\python.exe examples/similarity_demo.py --method-version 1 --directory data/similarity-v1 --output outputs/v1
.\.venv\Scripts\python.exe -m style_xi compare --method-version 1 --input outputs/v1/fictional-profiles.json --cohort data/similarity-v1/cohort.json --query highlightly/900301/2025/regular/900101/901201 --output outputs/v1/neighbours.json
```

Python callers use `fictional_example(method_version=1)` and
`fit_reference(..., method_version=1)`. Version 1 keeps passes, dribbles, tackles and
shots per 90, with its original metadata and historical shot wording. This does not
expand the provider's shot definition or clear real-player use. Regression tests pin
pre-revision hashes of original source envelopes, profiles, fit and complete comparison
output. The fit's `contract_version` distinguishes methods independently of JSON schema.

## Match holds and private auditing

Supply `build_profiles(import_result, match_holds=registry)` or the profiles CLI's
`--match-holds` option before comparison. Active holds remove the entire provider match
for both teams before actions, minutes, appearances, contributing IDs and denominators
are aggregated. Held-only identities remain visible as zero-exposure, unavailable
profiles. Coverage keeps held IDs/reasons; source records stay unchanged. The registry
digest and application policy accompany profiles and the version-2 fit. No private
registry is loaded implicitly. Old profiles must be rebuilt from their import with
the registry; a whole match cannot be safely subtracted from an aggregated profile.

`scripts/audit_cache_coverage.py --manifest <private-campaign.json> --match-holds
<private-holds.json> [--output <private-audit.json>]` reads only existing cache evidence.
It explicitly reports total/won/lost duel availability, other feature inputs, recorded
minutes, unheld player-team exposure distributions and source position coverage by
competition/stage. It loads no credential, spends no requests and produces no real
profiles, fit or ranking. Keep audit evidence outside the worktree.

Complete fields do not establish accuracy. Source labels are not validated tactical
roles; multiple labels and goalkeeper policy still need review. Unresolved match holds,
provider semantics, mixed-minute/cameo/clock effects, sufficient exposure, roles,
independent coverage and method/weight validation remain blockers. Version 2 records
`real_player_rankings_allowed: false` and `real_integration_allowed: false`. No real-data
interface mode is added.

The [private eligibility study](eligibility-study.md) extends this audit with hold-first
threshold sensitivity by league, stage and observed source position. It does not
enable real-player eligibility or rankings or validate the provisional 90/2 settings.
