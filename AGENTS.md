# Style-XⅠ working rules

## Implementation

- Check the existing architecture, dependency versions, README and relevant primary
  docs before making technical choices. Reuse working code, the current Python
  environment and locked dependencies where they fit. Keep changes small, focused
  and maintainable. Preserve existing project guidance, task scope and unrelated work.
- Verify the task's acceptance criteria and relevant regressions before pushing.
  Add tests with behavior changes when they provide useful coverage.
- Use isolated worktrees when concurrent changes could interfere.

## Instruction discovery

- Check the active instruction chain from the directories used to launch build and
  collection work. Follow the README and workflow working directories.
- Check for `AGENTS.override.md` and nested instructions. A same-directory override
  replaces `AGENTS.md`; verify that it also carries the applicable project rules.
  Keep machine-specific launch paths and discovery evidence outside Git.

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

- Write public docs, issues, commit messages, PR descriptions, review comments and
  code comments in the maintainer's developer voice: concise, direct, relaxed and
  practical, with a little dry humour where it fits.
- Describe actual behavior and useful instructions. Keep chat references, internal
  milestone labels, assistant commentary and phrases like "as requested by owner"
  out of public text.
- Preserve the Style-XⅠ spelling in user-facing copy; use ASCII technical names.

## Issues and scope

- Confirm the target GitHub repository and check open and closed issues for
  duplicates before filing. Open one issue before starting an independently
  actionable bug fix or feature worth tracking.
- Describe observed behavior or the current gap, expected behavior, impact and how
  to verify the change. Include a safe reproduction, failing test or public code
  or docs reference where relevant.
- Verify separately discovered problems before filing them. Keep separate fixes
  out of the current PR. Skip speculative or duplicate issues and minor cleanup
  that belongs in the current PR. Keep private-only findings in private records.

## Git and review

- Make small, atomic commits and push each tested increment on a feature branch.
  Open focused PRs for changes that need review; leave review and merge to the
  maintainer. Use `Closes #<issue-number>` only when the PR fully resolves the issue.
  Link follow-up issues without a closing keyword.
- Before staging, verify `.gitignore` and inspect the proposed files, exact diff
  and generated files for private material. Review the staged diff and outgoing
  commits before pushing. Ignore rules do not untrack files.
- Keep private wording, plans, private Markdown, reports, audit evidence, raw
  provider data, sensitive documents, local paths, `.env` files, keys and credentials
  outside Git and public GitHub discussions.
- Verify the destination remote and branch. Use the configured author. Preserve
  unrelated changes and shared history; do not force-push or reset them.

## Handoff

- Report what changed, what was verified, what is still pending and any blocker.
  Include the relevant commit, PR, CI and issue URLs. Share private evidence
  locations only in the private handoff.
- For collection work, include the latest ledger totals, requests used, remaining
  targets and holds. Use recorded state; do not infer missing counts or spend
  requests just to produce a handoff.

## Checks

Use the existing virtual environment. Run focused tests for the change, or run
the full offline check when its broader coverage is relevant:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B scripts/check_offline.py
```

Keep setup and usage instructions in the README accurate when behavior changes.
