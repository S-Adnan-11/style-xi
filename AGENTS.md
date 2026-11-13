# Style-XⅠ working rules

## Implementation

- Read the relevant README and docs before changing behavior. Preserve existing
  project guidance and unrelated work.
- Reuse the current architecture, Python environment and locked dependencies where
  they fit. Keep changes small, focused and maintainable.
- Verify the relevant tests before pushing. Add tests with behavior changes when
  they provide useful coverage.
- Use separate worktrees for concurrent work that could touch the same checkout.

## Data and analysis

- Preserve provider, competition, season, stage, team and player identity. Keep
  club spells and regular/playoff samples separate.
- Keep missing inputs unavailable. Preserve recorded minutes, validation rules,
  source provenance and match-level analytical holds.
- The public interface and comparison examples use fictional data. General
  real-player comparisons and app integration remain gated.
- Keep offline checks and fictional examples runnable without private inputs,
  credentials or network access. Make API requests only within explicit task scope.

## Writing

- Write public docs, code comments, commit messages, PR descriptions and review
  comments in a concise, direct and relaxed developer voice.
- Describe actual behavior and useful instructions. Keep chat references, internal
  milestone names and assistant commentary out of public text.
- Preserve the Style-XⅠ spelling in user-facing copy; use ASCII technical names.

## Git and review

- Make small, atomic commits and push each tested increment on a feature branch.
  Open a PR for changes that need review; leave review and merge to the maintainer.
- Before staging or pushing, verify `.gitignore` and review the exact diff,
  generated files and outgoing commits for private material.
- Keep private plans, reports, audit evidence, raw provider data, local paths,
  `.env` files and credentials outside Git. Ignore rules do not untrack files.
- Verify the destination remote and branch. Use the configured author. Preserve
  unrelated changes and shared history; do not force-push or reset them.

## Checks

Use the existing virtual environment. Run focused tests for the change, or run
the full offline check when its broader coverage is relevant:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B scripts/check_offline.py
```

Keep setup and usage instructions in the README accurate when behavior changes.
