# Profiles of accepted recorded matches

These profiles describe the accepted records available in an import result.
They are incomplete samples, even when all inputs to a metric are present.
Missing fixtures, missing box scores and excluded records remain separate gaps.
No minimum-minutes cutoff, ranking, tactical-role label or quality score is applied.

## Run offline

From the repository root:

```powershell
.\.venv\Scripts\python.exe examples/synthetic_demo.py
.\.venv\Scripts\python.exe -m style_xi import-cache --input data/synthetic --output outputs/sample.json
.\.venv\Scripts\python.exe -m style_xi profiles --input outputs/sample.json --output outputs/profiles.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The demo requires no key, network or external data. Generated files remain ignored.
`profiles` reads a version-1 import-result JSON file and writes a deterministic JSON
document plus a readable console summary. Python callers can use
`style_xi.profiles.build_profiles(import_result)` or
`profile_file(input_file, output_file)`. The normal importer and its acceptance
policy remain the source of records; this layer does not accept raw provider data.

## Metric contract

The stable machine-readable contract is returned by `metric_contract()` and included
in output under `metric_contract`, version 1. Every family has a `_total` key for
the counted sample total and a `_per_90` key for its recorded frequency. Only the
three supported success pairs below have `_success_pct` keys: 17 metrics in total.

| Key prefix | Count field | Additional required fields for consistency | Success numerator / attempts |
| --- | --- | --- | --- |
| `passes` | `passesTotal` | `passesSuccessful`, `passesFailed` | `passesSuccessful` / `passesTotal` |
| `key_passes` | `passesKey` | None | Not supplied |
| `dribbles` | `dribblesTotal` | `dribblesSuccessful`, `dribblesFailed` | `dribblesSuccessful` / `dribblesTotal` |
| `duels` | `duelsTotal` | `duelsWon`, `duelsLost` | `duelsWon` / `duelsTotal` |
| `tackles` | `tacklesTotal` | None | Not supplied |
| `interceptions` | `interceptionsTotal` | None | Not supplied |
| `shots` | `shotsTotal` | `shotsOnTarget`, `shotsOffTarget` | Not supplied |

All count inputs must be nonnegative integers, excluding booleans. Where components
are listed, successes plus failures must equal the total in every accepted row.
These components are required even for the family total: a number is unavailable
when its consistency cannot be established. No attempt count is reconstructed.
Shot frequency retains the provider's `shotsTotal` definition: on-target plus
off-target attempts, **excluding blocked attempts**. Existing `shots_per_90` keys
remain stable and carry this scope in their contract metadata. No player blocked
counter is available; team blocks must not be assigned to players. The provider
describes woodwork as off target without specifying every combined event case.
Team “Shots accuracy” includes blocks in its denominator and is separate from a
player ratio; it cannot be reproduced from player rows. Shot accuracy and additional
efficiency measures are omitted here.

Additive `source_field_semantics_version: 1` and `source_field_semantics` metadata
record provider-confirmed scope separately from unpublished definitions. Relevant
metric entries include `source_semantics`. These statements do not independently
verify a cache, every league, or cross-supplier agreement:

- Pass totals equal successful plus failed passes; what constitutes a pass,
  including restart treatment, is unpublished.
- `tacklesTotal` is the provider-recorded tackle count with an unpublished operational
  definition and no won/lost split. Neither attempted nor successful tackles is
  established. Its presence does not clear it for real-player similarity.
- One provider duel contest is recorded against both players with exactly one
  winner. Team-sum checks need complete player rows; another publisher's labels
  do not establish a comparable counting model.
- Source `minutesPlayed` is a nonnegative integer. A starter finishing a full
  match receives 90, or 120 with extra time. Substituted players receive recorded
  exit/remainder minutes; the final substitute may receive second-half added time.
  Keep these values unchanged. This mixed convention is not precise, uniform
  elapsed exposure. Short cameos may be materially affected, with no quantified
  error bound. Substitutes later removed, first-half added time, dismissals,
  extra-time substitutions and rounding remain incompletely specified.

No team minute sum is an unconditional invariant: consider team size, dismissals
and incomplete rows. Recorded zero alone is not independent proof of nonappearance.
No minute correction or real-rate eligibility threshold is established here. Future
analysis needs sufficient exposure, a reviewed role/goalkeeper policy, stable
source semantics and a method that avoids undefined inputs. Private raw import and
profile computation do not make real comparisons or integration ready. The fictional
four-feature method and weights remain unchanged; duels are only a later candidate.

Units and formulas:

- `*_total`: counted actions; `sum(count)` over the entire accepted match scope.
- `*_per_90`: actions per 90 recorded player minutes;
  `90 * sum(count) / sum(minutes)`. Minutes must be finite and nonnegative in every
  row and their sum must be positive. Importer-accepted appearances have positive
  minutes; extra time is retained, including 120-minute appearances.
- `*_success_pct`: percent; `100 * sum(successes) / sum(attempts)`. Each compatible
  pair must pass its component checks, and the summed attempts must be positive.

Frequency describes recorded involvement. Efficiency describes the proportion of
recorded attempts that succeeded. Neither automatically measures quality or an
intrinsic playing style. Per-90 is not a prediction of a full-match performance and
does not adjust for possession, team tactics, opposition, league or opportunity.
No progressive actions, pressures, carries or coordinates are inferred.

## Missingness and precision

Required inputs must be valid in **every accepted row** for a metric. One absent,
null, invalid or inconsistent input makes that metric unavailable across this scope.
The value is `null`; no partial action sum is divided by all minutes, and partial
observations are not presented as complete totals. Independent metric families can
remain available. This is also enforced defensively if an existing import result
is edited or supplied by another caller.

Every metric includes `value`, `unit`, `reason`, `coverage` and `issues`:

- Coverage reports eligible and observed appearances and minutes. An observed row
  has every required input for that metric valid. `inputs_complete` describes fields
  within accepted records, not season coverage. Unknown minute totals remain `null`.
- Issues identify affected match IDs, required fields and `missing_input`,
  `invalid_input` or `inconsistent_counts`. No source values are silently corrected.
- Unavailable reasons are `incomplete_or_invalid_inputs`, `zero_attempts`,
  `zero_minutes`, `nonfinite_result` or `no_accepted_records` at the calculation API.
  A genuine recorded zero remains a numeric zero; zero attempts yield `null` percent.

The importer still quarantines an entire record with a missing core count. Its other
counts do not contribute to a profile. In the demo, Cora's accepted-scope metrics
therefore have complete inputs for one accepted record, while match coverage shows
one of two collected player matches accepted. Separate boundary tests cover the
case of a missing field inside a caller-supplied accepted scope.

Structured results retain calculation precision. Only console values are rounded
to two decimal places. Percentages are on a 0-100 scale; legacy sample-aggregate
`ratios` remain on a 0-1 scale. JSON never encodes infinity or NaN.

## Identity and coverage

Profiles are keyed by `provider`, `competition_id`, `season`, `stage`, `team_id` and
`player_id`. Names are sorted observed display labels, never join keys. Empty name
lists mean no display label was available. Different clubs, stages, seasons and
competitions stay separate; a combined transfer-season profile is deferred. A club
group does not infer chronological spell boundaries if a player leaves and returns
within the same season; that needs fuller history.

`accepted_appearances` counts unique accepted player-match rows in that context.
`accepted_minutes` sums their recorded player minutes, not match durations. Exact
repeated inputs do not add appearances; conflicting player-match inputs stop profile
generation. The importer continues to quarantine ambiguous duplicates upstream.
Zero-minute bench exclusions never create profiles on their own. Identities with no
accepted rows do not produce a profile, and exclusions remain in the input report.

Each profile includes contributing match IDs and source snapshot IDs. Its coverage
distinguishes known collected player matches, accepted matches, attributable excluded
matches/records and exclusion reasons. Collection here means that player's record
was observed; it is not an expected-appearance count. Match diagnostics without a
safe player attachment are reported separately and are not assigned to a player.

The manifest fields retain provider-listed totals across all stages, listed/acquired
matches in the profile's stage, pagination status and independent-coverage status.
If manifest context is absent, its values are `null`. Complete provider pagination
does not make `full_season_profile` true or establish expected real-world fixtures.
No accepted or collected count implies the player participated in uncollected matches.

## Output and compatibility

The profile document has `schema_version: 1`,
`kind: "accepted_match_sample_profiles"`, `metric_contract_version: 1`, a summary,
the metric contract and a sorted `profiles` list. Profiles sort by their identity
tuple; contributing matches, names, snapshots and diagnostics have stable ordering.
No timestamps are inserted during calculation.

The import-result schema stays version 1. Records now retain optional `player_name`,
`team_name` and `competition_name`; saved older imports work with unknown names.
Sample aggregates add `appearances` and per-field `count_coverage`. Complete validated
counts, per-90 values and legacy ratios keep their previous meanings. Missing inputs
at the aggregation boundary now propagate as `null` instead of raising a field error.
Reimport source cache to recover display names when they were previously discarded.

Expected/modelled goal and assist fields, ratings, cards and arbitrary new numeric
fields never enter the profile metric contract or calculation. Goal/assist outcome
metrics and additional efficiencies are not selected for this first profile set.
These profiles do not establish independent data accuracy, complete seasons,
validated player similarity or scouting conclusions.
