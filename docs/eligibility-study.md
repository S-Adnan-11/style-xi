# Private eligibility coverage study

This is a descriptive extension of the cache availability audit, with zero API
requests, credential loads, real-player profiles, fitted comparisons or rankings.
Real-player rankings and integration remain disabled. It does not change the
fictional comparison's provisional 90-minute/two-appearance settings.

From the repository root, supply the existing private manifest, holds and evidence:

```powershell
.\.venv\Scripts\python.exe -B scripts/audit_cache_coverage.py --study --manifest <private-campaign.json> --match-holds <private-holds.json> --minutes-evidence <private-field-evidence.json> --source-manifest <private-public-source-manifest.json> --output <private-study.json> --report <private-report.md> --threshold-csv <private-thresholds.csv>
```

Keep generated study artifacts outside every worktree. Omitting `--study` preserves
the original coverage audit. Evidence options read existing files only; archived
HTML is checked against its retained SHA-256 manifest without fetching URLs. Minute
cases reproduce cached identities, pinned bodies, recorded values and JSON pointers.
That checks preservation and extraction, not independent elapsed-minute accuracy.

The default sensitivity grid crosses 90, 180, 270, 360 and 450 recorded minutes
with one through five accepted appearances. Override it with `--minute-thresholds`
and `--appearance-thresholds`, each followed by distinct positive integers. Invalid
settings fail before output. Every grid value, including 90/2, remains provisional.

The sample unit is provider / competition / season / stage / team / player. Match
holds exclude both teams before exposure and label classification. Held-only samples
are counted separately and leave the study denominator. Regular and playoff minutes
and appearances stay separate; another club, stage or season cannot supply exposure.
League and source-position denominators, passing counts/fractions, exclusive exposure
failure reasons, retained minutes/appearances and hypothetical stable-outfield counts
are available in JSON. The CSV contains every league-by-position threshold cell.
Fractions describe the observed cache population, not complete-season coverage.

Position states describe only labels on accepted, unheld appearances:

- **Stable:** one consistent, nonmissing observed label. This does not prove a
  season-long or tactical role; one appearance can appear stable.
- **Mixed:** multiple known labels with none missing.
- **Missing:** at least one absent, blank or invalid label. Known mixtures with
  missing observations are counted separately too. Unknown nonblank strings stay
  in an unreviewed source-label bucket rather than being mapped into a role.

The proposed research policy retains mixed/missing samples in descriptive buckets
and excludes them from an initial single-label outfield screen. It does not choose
a majority label or infer a role from actions or formation. Any observed Goalkeeper
label, including mixtures, requires a separate goalkeeper feature/cohort review;
no goalkeeper ranking is enabled. The study reports threshold coverage before and
after this hypothetical screen, so its coverage costs and position bias are visible.

180 minutes/three appearances is a candidate research screen to validate, with 90/2
as the provisional benchmark and 270/3, 360/4 and 450/5 as stricter sensitivity checks.
Retention counts cannot establish statistical reliability or justify activation.
More exposure can reveal more mixed labels, making a stability requirement selective.
Stricter thresholds can favour full-match players and goalkeepers and remove forwards
and substitutes disproportionately. These effects must be quantified in the private
report before proposing a real eligibility rule.

Keep source minutes unchanged. Existing event clocks, narrative reports and provider
explanations are separate evidence classes; none alone establishes exact elapsed
exposure. No fixed minute correction, nominal clipping or team-minute invariant is
introduced. Validation still needs representative independent entry/exit/whistle
evidence, added-time/rounding/dismissal/extra-time cases, genuine zero-minute
appearances, role-label and goalkeeper review, repeated-sample stability, independent
coverage and unresolved match-hold/source-field review.
