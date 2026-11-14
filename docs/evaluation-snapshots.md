# Frozen evaluation inputs

Capture an evaluation bundle outside every Git worktree:

```powershell
.\.venv\Scripts\python.exe -B scripts/evaluation_snapshot.py capture --campaign <campaign.json> --protocol <protocol.md> --match-holds <holds.json> --output <snapshot-directory>
```

Capture uses the collector's shared account run lock and campaign lock. It reads
the latest completed batch and checks the campaign, accepted replay, calendar,
holds and gate. Halted collection, uncertain requests, failed validation or a
changed input prevents publication. No credential or provider request is needed.

The bundle contains `input-manifest.json`, exact `ledger.json`, `account.json` and
`checkpoint.json` bytes, plus the campaign, batch, protocol, holds, gate, source
responses, baseline evidence, history ledgers and supplied code files. Source files
have short local names; their original provenance strings remain in the manifest.

Package Python files are included by default. Add private evaluation code with
repeatable `--implementation-file LABEL PATH` pairs. `--engine-file LABEL PATH`
pairs replace the default engine file set. `--code-revision` records an optional
revision label; file hashes identify the actual code. To preserve an existing
manifest, pass `--input-manifest` and the same code mappings and revision. Every
pin must match the locked inputs; a stale manifest is not silently updated.

Copied inputs are hashed and replayed in staging. Capture then reserves a new
destination, moves the files, verifies them again and publishes `READY.json` last
with an atomic file link. Existing destinations are never overwritten. Interrupted
captures can leave an incomplete destination or `.capture-*` directory; the verifier
rejects unpublished bundles. Inspect these privately and choose a new destination
rather than resuming or replacing partial files. `.capture-*` is reserved for staging.

Save the returned snapshot and input-manifest fingerprints separately. Verify a
published bundle using its snapshot fingerprint:

```powershell
.\.venv\Scripts\python.exe -B scripts/evaluation_snapshot.py verify <snapshot-directory> --expected-sha256 <capture-fingerprint>
```

Verification reads only snapshot-relative copies. It does not follow the original
manifest paths or inspect current acquisition state. Later collection, unavailable
live files and moving the complete bundle do not invalidate it. Missing or changed
files, invalid control anchors, unsafe paths and incomplete publication fail.
Retaining the capture fingerprint also detects replacement of the bundle's index.

For Python use, `capture_evaluation_snapshot()` returns the fingerprints.
`verify_evaluation_snapshot()` returns aggregate verification metadata.
`read_evaluation_snapshot()` returns the verified inputs in memory for an existing
evaluation workflow. Keep generated reports separate from the immutable bundle.
These functions do not fit profiles, score players or change analytical gates.
