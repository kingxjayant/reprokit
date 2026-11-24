# Benchmark harness

The 10-issue study described in the build spec. **Nothing here is filled in
until the study actually runs** — the site's `/benchmark` page reads
`results.json` and shows an empty state while it is missing.

## Plan

- 10 public issues from 3 mid-size repositories, each where a maintainer asked
  for more information (`needs reproduction`, `needs more info`,
  `cannot reproduce`, `please provide`).
- Two conditions per issue: the original report, and a ReproKit report.
  Identifying details stripped from both.
- 3 raters, timed, order randomised.
- Task: "Can you reproduce this from what's written? If yes, start now. If no,
  say what you'd ask for."
- Cap at 8 minutes; unresolved counts as *abandoned as unfollowable*.

## Output shape (`results.json`)

```json
{
  "run_at": "2026-11-26",
  "raters": 3,
  "median_original": "6m40s",
  "median_reprokit": "2m10s",
  "abandoned": "3 of 10 → 0 of 10",
  "rows": [
    {"label": "repo-a #1841", "original": "6m40s", "reprokit": "2m10s", "outcome": "reproduced"}
  ]
}
```

Report failures as failures. If ReproKit does worse on an issue, it stays in.
