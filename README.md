# ReproKit

**A vague bug report in, a reproduction a maintainer can actually rerun out.**

Live at [reprokit.tech](https://reprokit.tech) · MIT licensed · no accounts, no tracking, no repo access

---

## What it does

Paste a public GitHub issue. ReproKit scans it for the eleven things a maintainer
needs before they can attempt a reproduction, asks the reporter **only** for what
is missing, redacts anything secret server-side, and emits a structured Markdown
block that can be pasted straight back into the issue.

It then says, plainly, whether the report is rerunnable — and if it isn't, exactly
which fields are still absent.

## What it does not do

This matters more than the feature list, so it is at the top rather than the bottom.

- **It does not reproduce bugs.** No code execution, no sandbox, no bisect.
- **It does not guess root causes** or suggest fixes.
- **It does not read private repositories**, request repo access, or install a bot.
- **It does not post to GitHub on your behalf.** You copy the Markdown and post it.
- **It does not claim a report is complete when it isn't.** A skipped field stays
  listed as a gap. `test_skipped_field_stays_absent` enforces this.

Existing tools attack the maintainer's side of this problem (sandbox reproduction,
automatic test generation) or the format (issue templates). None of them fix the
actual failure: *the reporter does not know what evidence is missing, and nothing
tells them at the moment they are writing.* That gap is the whole product.

---

## The eleven fields

In interview priority order. Detection is deterministic — a regex decides whether a
stack trace exists, because that is auditable, free and faster than an LLM, and a
reviewer can read the code and check the logic.

| # | Field | Why it is not optional |
|---|---|---|
| 1 | Symptom | The thing that is actually broken, in one sentence |
| 2 | Environment (OS + version) | Half of all "cannot reproduce" is an OS difference |
| 3 | Runtime / dependency version | Behaviour changes between versions |
| 4 | Exact command or click path | "It breaks" is not a reproduction |
| 5 | Expected result, literal | "Should work" cannot be measured |
| 6 | Actual result, literal | What happened, in the reporter's words |
| 7 | Error text / stack trace | The real text, not a summary of it |
| 8 | Frequency | Always vs 1-in-3 changes the diagnosis |
| 9 | **What does not trigger it** | The one answer that halves the search space |
| 10 | Minimal reproduction | The smallest thing that still fails |
| 11 | Limits of observation | What the reporter did *not* test |

Field 9 is the differentiator. Every tool asks for steps; almost none ask what
*doesn't* reproduce the bug.

---

## Architecture

```
app/
  fields.py      the 11 fields, Q1–Q8 interview order, Evidence model
  artifacts.py   deterministic detectors + gap analysis + verdict
  redact.py      typed server-side secret redaction (18 rules)
  report.py      Markdown generator, mandatory disclaimer
  github.py      public issue fetch, typed errors
  db.py          storage: SQLite (dev/tests) + Postgres/Supabase (prod)
  main.py        FastAPI routes; server-rendered HTML, no build step
templates/       Jinja2, mobile-first, single stylesheet inline
migrations/
  0001_init.sql         Supabase / Postgres
  0001_init.sqlite.sql  mirror for local development
tests/           104 tests
benchmark/       the 10-issue study harness (results published when measured)
```

**Deliberate choices**

- **Server-rendered HTML, no SPA.** Loads instantly on a budget Android phone.
- **Interview state in an httpOnly cookie.** No accounts, no session table, nothing
  to leak.
- **Random 12-character report ids.** Never sequential, so permalinks cannot be
  enumerated.
- **Redaction at input *and* at render.** Two passes, because the render pass is the
  last place data can escape.
- **Analytics events are a closed set.** `report_started`, `report_completed`,
  `report_rerunnable` are separate rows, so a page visit can never be counted as a
  completed task. Properties are stripped of URLs, repo names and reporter input
  before storage.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # leave DATABASE_URL empty to use SQLite
make run                      # http://localhost:8000
make test                     # 104 tests
```

With no configuration at all it runs on SQLite and needs no network for the test
suite — every GitHub call in the tests is stubbed, so CI can never hit the API.

## Tests

```
104 passed
```

| File | Covers |
|---|---|
| `test_redact.py` (19) | tokens, private keys, JWT, URL credentials, home paths, emails, idempotency |
| `test_gap_analysis.py` (25) | every detector, vague-report rejection, skip semantics, gap ordering |
| `test_report.py` (12) | section completeness, mandatory disclaimer, nested fences, render-time redaction |
| `test_github.py` (17) | URL parsing, 404/429/500/oversize handling, no-auth-without-token |
| `test_db.py` (15) | roundtrip, retention, analytics separation, property stripping |
| `test_app.py` (17) | the whole stranger flow end to end |

Two tests exist purely to protect promises made on the landing page:

- `test_visits_are_not_counted_as_completions` — 5 landing-page views produce 0 completions.
- `test_benchmark_refuses_to_show_invented_numbers` — `/benchmark` shows an empty state
  until `benchmark/results.json` exists.

## Environment variables

See `.env.example`. Only two are required in production: `APP_BASE_URL` and
`DATABASE_URL`. `GITHUB_TOKEN` is optional (raises the rate limit from 60/hr to
5000/hr for public reads) and needs **no scopes**. No secret is ever sent to the
browser, and `.env` is the first entry in `.gitignore`.

## Licence

MIT. See `LICENSE`. Third-party components and their licences: `PROVENANCE.md`.
