# Provenance

Written for reviewers: what is original to this project, what is third-party, and
how AI assistance was used. Nothing here is hidden, because being caught hiding it
would be worse than disclosing it.

## Original work

Everything in `app/`, `templates/`, `tests/`, `migrations/` and `benchmark/` was
written for this project.

| Module | What it does |
|---|---|
| `app/fields.py` | The 11-field model, interview order, `Evidence` semantics (present / skipped / missing) |
| `app/artifacts.py` | All 10 field detectors, section-aware heading parsing, gap analysis, verdict logic |
| `app/redact.py` | 18 redaction rules, typed `[REDACTED:…]` markers, redaction counting, idempotency |
| `app/report.py` | Markdown artefact generator, nested-fence handling, mandatory disclaimer |
| `app/github.py` | Public issue fetch, URL parsing, typed error taxonomy |
| `app/db.py` | Storage abstraction, SQLite + Postgres backends, funnel metrics, property stripping |
| `app/main.py` | Routes, cookie-held interview state, permalinks |
| `migrations/*` | Schema, RLS deny-by-default, retention function |
| `templates/*` | All markup and CSS, hand-written, no CSS framework |

The visual design is original. There is no template, theme or UI kit.

## Third-party packages

| Package | Licence | Used for |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | HTTP routing, form parsing |
| [Starlette](https://github.com/encode/starlette) | BSD-3-Clause | ASGI toolkit underneath FastAPI |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | ASGI server |
| [Jinja2](https://github.com/pallets/jinja2) | BSD-3-Clause | Server-side templates |
| [httpx](https://github.com/encode/httpx) | BSD-3-Clause | GitHub API calls |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | Form encoding |
| [psycopg](https://github.com/psycopg/psycopg) | LGPL-3.0 | Postgres driver (production only) |
| [pytest](https://github.com/pytest-dev/pytest) | MIT | Tests (development only) |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT | Validation, via FastAPI |

No runtime dependency is GPL or AGPL. `psycopg` is LGPL-3.0 and is used unmodified
as a library.

## Services

| Service | Role | Notes |
|---|---|---|
| Supabase | Hosted PostgreSQL | Only redacted report content is stored. No Supabase client key is shipped to the browser; RLS is deny-by-default for all non-service roles. |
| GitHub REST API | Reading public issues | Read-only, public data only. Optional token carries no scopes. |

## Fonts and assets

None. No web fonts, no icon library, no analytics script, no CDN. The page is one
inline stylesheet and system fonts, so it renders identically offline and on a
slow connection.

## AI assistance

GitHub Copilot and an LLM assistant were used while writing this code, for
scaffolding, test-case drafting and review. Every file was read, run and
individually checked before being committed, and the behaviour described in
`README.md` is covered by a test that fails if the behaviour changes.

Where an LLM is *not* used, deliberately: the gap analysis. Deciding whether a
report contains a stack trace is a parsing problem that a regex solves deterministically,
for free, and in a way a reviewer can audit. `LLM_PROVIDER=none` is the default and
the system is fully functional in that mode.

## Data

No third-party dataset is bundled. The benchmark study collects only public issue
text from public repositories; identifying details are stripped before publication,
and the harness in `benchmark/` documents the method.

## Licence

MIT (see `LICENSE`). Copyright 2026 Jayant Kumar.
