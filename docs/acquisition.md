# Acquisition and recovery

Use only data you are entitled to acquire and retain. The tools do not establish
provider permissions, public display rights or complete competition coverage.
No raw data is included in the repository.

For a reviewed, fixed five-competition season scope, the [manual campaign workflow](campaign.md)
adds a persistent overall counter, shared daily accounting and inventory continuation
to this same downloader. The explicit-plan workflow below retains its 50-call cap.

## Plan format

The following IDs are fictional. Replace them with inspected provider IDs before
any live use. Save the plan in an ignored runtime location.

Supported paths are `/matches`, `/box-score/{matchId}` and `/lineups/{matchId}`.
Lineups are cached source evidence only; the importer does not turn match positions
into season roles or comparison cohorts.

```json
{
  "calls": [
    {
      "path": "/matches",
      "parameters": {"leagueId": 900301, "season": 2025, "limit": 10, "offset": 0},
      "scope": {"competition_id": 900301, "season": 2025, "stage": "all_provider_stages"}
    },
    {
      "path": "/box-score/900001",
      "parameters": {},
      "scope": {"competition_id": 900301, "season": 2025, "stage": "regular", "match_id": 900001}
    }
  ]
}
```

Each invocation uses the same plan and state directory to resume. Plans contain
at most 50 explicit calls; the persisted budget may be lower via `--cap`. The cap
cannot change after a ledger exists. A different plan requires review because
the checkpoint records its hash. Do not rotate directories or accounts to bypass
a budget or halt.

Pagination uses the response's actual `pagination.limit`, `offset` and
`totalCount`. Add only the next required explicit pages to a reviewed plan.
Changing a plan's hash deliberately stops automatic resume; preserve the original
state and evidence when preparing the next bounded scope. A page gap leaves
coverage incomplete. Empty/short pages before the expected end, repeated IDs,
changed page contents and inconsistent totals stop the runner. Completion is
relative to provider-listed results, never independently expected fixtures.

## Shared account state

`--account` points to a JSON file shared by participating acquisition clients.
A fresh response header updates its observation automatically. To start without
an existing fresh observation, record a current account-dashboard balance and its
actual UTC observation time. The following is a **schema example**, not a usable
balance or timestamp:

```json
{
  "observation": {
    "observed_utc": "REPLACE_WITH_ACTUAL_UTC_OBSERVATION_TIME",
    "remaining": 0,
    "source": "account_dashboard"
  },
  "attempts": [],
  "halted": null
}
```

An observation is valid for five minutes on the same UTC day. Remaining quota
must exceed ten after all subsequent known attempts. Coordinate other account
usage; the tool cannot see unreported clients. `--account-history` accepts an
existing JSON ledger with an `attempts` list whose entries have `reserved_utc`.
Each known attempt after the observation is conservatively deducted. Avoid adding
the same ledger twice: duplicate history can conservatively overcount usage.

Normal acquisition refuses a missing or stale observation. The CLI does not
bootstrap quota. A separately authorized low-level workflow may opt into
`Downloader.get(..., allow_quota_bootstrap=True)` on its first useful `/matches`
request. This exception is persisted before transport, consumes one attempt and
cannot bypass a fresh balance at or below the reserve. It is unavailable for box
scores or lineups and cannot be repeated after restart. Never infer allowance from
yesterday's quota.

Match listings must identify the Basic/free plan. Unexpected or missing plan
context stops acquisition. Each successful response must supply quota evidence;
missing evidence or a contradictory increase persists a halt before another call.
Keep the same shared account state across budget directories. Never delete
attempts or clear a halt merely to resume.

## Files and interruptions

- `requests.json`: immutable-in-purpose attempt history, configured cap and halt.
- `responses/`: content-addressed successful response envelopes. Each includes
  the parsed source body, original response hash, stored-body hash and retrieval
  time. Exact UTF-8 response text is retained when it needs no secret redaction.
  Credential echoes are redacted and exact raw text is omitted in that case.
- `failures/`: redacted HTTP failure evidence with status, bounded body/excerpt,
  hashes and nonsecret quota headers. Failed attempts still consume the budget.
- `checkpoint.json`: request-plan hash, completed indexes, coverage and coverage
  hashes after each call. A completed plan can still have incomplete coverage.

Writes use a same-directory temporary file, flush, `fsync` and atomic replacement.
OS file locks prevent concurrent writers and release on process exit. Filesystem
or machine failure guarantees beyond these operations are not claimed.

If a complete cached response exists after interruption before the final ledger
write, the next invocation verifies it and finishes without HTTP. If the outcome
is unknown, its reservation still counts and the tool stops for investigation.
Do not automatically retry an uncertain request. A missing ledger with existing
cache is an error. Corrupt or conflicting cache entries are never silently
overwritten or replaced by another network request.

The low-level `Downloader.get()` returns an envelope. Use `run_plan()` or the CLI
for pagination validation and checkpointing. Offline `import-cache` reads both
match-list and box-score envelopes and never dispatches HTTP. Retain the source
cache to investigate exclusions; analytical output intentionally omits modelled
goal/assist values, cards and other fields outside the core allowlist.

The transport follows the official [authentication](https://highlightly.net/football-api/documentation/getting-started/authentication/),
[pagination](https://highlightly.net/football-api/documentation/getting-started/pagination/)
and [box-score](https://highlightly.net/football-api/documentation/box-score/)
documentation. Actual responses can differ from the documented schema, so input
validation and coverage checks remain necessary.
