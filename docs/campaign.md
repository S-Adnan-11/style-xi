# Manual season collection

`style_xi.campaign.Campaign` extends the existing `Downloader` for a fixed,
manually invoked five-competition season campaign. It does not start a service,
wait for a quota reset, run comparisons or connect data to the interface.

Keep the manifest, source responses, account state, validation evidence and
generated profiles in a private location outside Git worktrees. A local wrapper
can load a credential into memory, construct `Campaign(manifest_path)`, print
`status()` and call `run(key)`. Public code has no dependency on that wrapper.
`status()` is read-only and needs neither a key nor a provider call.

## Fixed manifest

Review the identifiers against existing provider evidence before initialization.
The JSON manifest requires:

| Field | Meaning |
|---|---|
| `version` | `1` |
| `season` | Integer provider season identifier |
| `competitions` | Five distinct `{ "id": ..., "name": ... }` objects in rotation order |
| `cap`, `daily_cap`, `reserve` | `1800`, `90`, `10` |
| `regular_stage_rule` | `Regular Season - [1-9][0-9]*` |
| `completed_states` | `Finished`, `Finished after extra time`, `Finished after penalties` |
| `state`, `account` | Local state directory and shared account JSON path |
| `history` | Existing request-ledger paths, including known account use |
| `baseline_files` | Objects with `path`, exact file `sha256`, and `snapshot` boolean |
| `interval_seconds` | Sequential request delay, between 1 and 60 seconds |
| `validation_gate` | Optional local JSON path with boolean `allow_box_scores` and evidence/reasons |

The manifest hash is anchored in the shared account, request ledger and checkpoint.
`initialize()` is an explicit one-time setup step. Changing the manifest, losing a
ledger, rotating state directories or deleting an account anchor does not reset
the campaign. Preserve the original configuration and investigate a mismatch.

The validation gate can pause box retrieval while useful fixture inventories are
completed. Change it only after recording a field-evidence review. An absence of
independent evidence is different from a material disagreement. Neither successful
retrieval nor arithmetic agreement establishes statistical accuracy.

## Allowance and transport

The overall counter never resets. Every dispatched request, including quota
bootstrap and failures, consumes it. Reservations are written to the shared
account before the campaign ledger and before transport. An orphan or uncertain
reservation blocks further transport; it is never assumed to cost zero.

The daily allowance is the conservative intersection of:

- 90 minus known account use, including reservations and declared outside use;
- current provider remaining quota minus the ten-request reserve;
- the campaign's remaining allowance.

Participating clients use the same account JSON. Known outside requests can be
recorded in `external_usage` as UTC-date keys and nonnegative counts; do not count
the same requests both there and in a participating ledger. Response evidence
also sets a durable daily usage floor. Prior-day history remains intact. Unknown
external use between observations cannot be predicted, so coordinate account use.

When current quota evidence is absent, the first useful uncached request may
bootstrap it, at most once per UTC day. This is a counted request, not a separate
probe. Fresh reserve/exhaustion evidence prevents bootstrap. Missing quota headers,
unexpected Basic quota limits or a contradictory increase persist a stop. The
response must report a 100-request daily plan; no billing changes are performed.

One worker uses the existing transport: 20-second socket timeout, bounded response
size, no redirects and no automatic retries. The batch exits at the UTC boundary,
allowance, completion, interruption or validation stop. It never rolls into the
next day's allowance. HTTP failures retain the existing conservative stop policy;
404/410 are counted as unavailable, other failures require manual review. Resume
never silently refetches an attempted identity.

## Inventory and selection

Earlier compatible, hash-pinned pages are reused. The next page fills the first
gap without overlapping an existing block. Advancement uses the effective response
limit, including a provider limit smaller than requested. Changed totals, repeated
IDs, changed fixture contents, incomplete pages and overlaps require reconciliation.
Keep all originals when investigating them.

Only explicit regular-stage labels and completed states form targets. The explicit
knockout labels `Final`, `Semi-finals` and `Relegation round - Quarter-finals` are
excluded; other unknown labels remain unresolved. A score alone proves neither
completion nor usable exposure. An administratively ratified result from an
abandoned match does not become a completed player-exposure sample automatically.

After inventories are exhausted, selection rotates through all five competitions.
Within each league it favours clubs with fewer cached/attempted matches, then less
represented months, then date and match ID. Valid cached targets cost no requests.

Keep these separate: pagination exhausted, targets with usable box scores, and
independently verified real competition coverage. The first does not prove the
other two. Status includes positive-minute acceptance, positive-minute rejection,
ordinary zero-minute exclusions, unavailable/manual-review targets and field
completeness; unused substitutes are not an unexplained error rate.

## Recovery and output

OS locks prevent two batch invocations from running concurrently and release on
process exit. Each response and ledger write is atomic. A complete, hash-verified
snapshot can reconcile an interrupted reservation without transport. A reservation
without that evidence remains counted and blocks continuation. Do not delete
locks, ledgers, halts or evidence to force a retry.

Each batch writes `batches/<UTC timestamp>.json`, `status.json`, `inventory.json`,
`import.json` and `profiles.json` privately. Final replay failure is a persistent
stop, not a successful batch. Existing parsing, exclusions, metric denominators
and fictional comparison rules are unchanged. Even when every target is cached,
real comparison readiness remains a separate review.
