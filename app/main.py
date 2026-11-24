"""ReproKit web app.

Single service, server-rendered HTML, no build step, no client-side database
access. Deliberately boring so it can be read end-to-end by a reviewer.

Flow:
    GET  /                  intake (URL or manual paste)
    POST /analyse           gap scan -> interview or straight to the report
    POST /interview         one question at a time, Q1..Q8
    GET  /report            the generated report (session-scoped, not stored)
    GET  /r/<id>            public permalink to a stored report
    POST /save              persist the current report, return its permalink
    GET  /benchmark         measured study (empty until it is measured)
    GET  /healthz           liveness, no secrets in the payload
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import artifacts, github, report as report_mod
from .db import (
    VERDICT_NOT_RERUNNABLE,
    VERDICT_RERUNNABLE,
    Store,
    get_store,
    new_id,
)
from .env import ROOT, get_config
from .fields import (
    FIELD_META,
    INTERVIEWABLE,
    QUESTION_BY_FIELD,
    Evidence,
    Field,
)
from .redact import redact, redact_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reprokit")

CONFIG = get_config()

# Module-level state, injected in tests via configure()
_store: Store | None = None
_templates: Jinja2Templates | None = None


def configure(store: Store | None = None, templates_dir: Path | None = None) -> None:
    """Wire dependencies. Called at import for production, and by tests.

    On a serverless platform (Vercel) the process can be recycled between
    requests, so startup work is idempotent and cheap: schema creation uses
    ``CREATE TABLE IF NOT EXISTS`` and a connection is opened per instance.
    """
    global _store, _templates
    _store = store or get_store(CONFIG.database_url, CONFIG.retention_days)
    _templates = Jinja2Templates(directory=str(templates_dir or ROOT / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure()
    log.info("reprokit starting: env=%s db=%s", CONFIG.app_env,
             "postgres" if CONFIG.use_postgres else "sqlite")
    yield


def templates() -> Jinja2Templates:
    if _templates is None:
        configure()
    assert _templates is not None
    return _templates


def store() -> Store:
    if _store is None:
        configure()
    assert _store is not None
    return _store


app = FastAPI(title="ReproKit", docs_url=None, redoc_url=None, lifespan=lifespan)





# --------------------------------------------------------------------------- #
# session helpers — the interview state lives in a signed cookie
# --------------------------------------------------------------------------- #


def load_evidence(request: Request) -> tuple[Evidence, dict]:
    raw = request.cookies.get("rk_state")
    if not raw:
        return Evidence(), {}
    try:
        data = json.loads(raw)
    except ValueError:
        return Evidence(), {}
    ev = Evidence()
    for k, v in (data.get("values") or {}).items():
        try:
            ev.set(Field(k), v)
        except ValueError:
            continue
    for k in data.get("skipped") or []:
        try:
            ev.skip(Field(k))
        except ValueError:
            continue
    return ev, data.get("found") or {}


def save_evidence(response, evidence: Evidence, found: dict) -> None:
    payload = json.dumps(
        {
            "values": {f.value: v for f, v in evidence.values.items()},
            "skipped": [f.value for f in evidence.skipped],
            "found": {k: v for k, v in found.items()},
        }
    )
    response.set_cookie(
        "rk_state",
        payload,
        max_age=60 * 60 * 3,
        httponly=True,
        samesite="lax",
        secure=CONFIG.is_prod,
    )


def clear_state(response) -> None:
    response.delete_cookie("rk_state")


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "env": CONFIG.app_env,
            "database": "postgres" if CONFIG.use_postgres else "sqlite",
            "version": "1.0.0",
        }
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    resp = templates().TemplateResponse(
        request, "index.html", {"issue_url": "", "error": None}
    )
    store().track("report_started", {"stage": "intake_view"})
    return resp


@app.post("/analyse", response_class=HTMLResponse)
def analyse(
    request: Request,
    issue_url: str = Form(""),
    title: str = Form(""),
    body: str = Form(""),
) -> HTMLResponse:
    """Scan an issue (by URL or pasted) and start the interview."""
    issue_url = (issue_url or "").strip()
    pasted = not issue_url

    if issue_url:
        if not github.looks_like_issue_url(issue_url):
            return templates().TemplateResponse(
                request,
                "index.html",
                {
                    "issue_url": issue_url,
                    "error": "That doesn't look like a GitHub issue URL. "
                    "It should look like https://github.com/owner/repo/issues/123 "
                    "— or paste the report by hand below.",
                },
                status_code=400,
            )
        try:
            issue = github.fetch_issue(issue_url, CONFIG.github_token)
        except github.IssueError as exc:
            store().track("issue_fetch_failed", {"status": exc.status})
            return templates().TemplateResponse(
                request,
                "index.html",
                {"issue_url": issue_url, "error": exc.message},
                status_code=exc.status,
            )
        title, body = issue.title, issue.body
        source = {
            "url": issue.url,
            "owner": issue.owner,
            "repo": issue.repo,
            "number": issue.number,
        }
    else:
        title = (title or "").strip()
        body = (body or "").strip()
        if not title and not body:
            return templates().TemplateResponse(
                request,
                "index.html",
                {
                    "issue_url": "",
                    "error": "Paste an issue URL, or a title and body, so there's something to scan.",
                },
                status_code=400,
            )
        source = {"url": None, "owner": None, "repo": None, "number": None}

    # every byte that will be stored or displayed goes through redaction first
    safe_title, hits_title = redact(title)
    safe_body, hits_body = redact(body)
    redactions = redact_summary(hits_title) + redact_summary(hits_body)

    evidence, found = artifacts.analyse(safe_title, safe_body)
    found_payload = {f.value: v for f, v in found.items()}

    if artifacts.gaps(evidence):
        resp = RedirectResponse("/interview", status_code=303)
    else:
        resp = RedirectResponse("/report", status_code=303)

    save_evidence(resp, evidence, found_payload)
    resp.set_cookie(
        "rk_src",
        json.dumps({**source, "pasted": pasted, "redactions": redactions}),
        max_age=60 * 60 * 3,
        httponly=True,
        samesite="lax",
        secure=CONFIG.is_prod,
    )
    store().track(
        "report_started",
        {"mode": "paste" if pasted else "url", "initial_gaps": len(artifacts.gaps(evidence))},
    )
    return resp


@app.get("/interview", response_class=HTMLResponse)
def interview_get(request: Request) -> HTMLResponse:
    evidence, found = load_evidence(request)
    answered = set(evidence.skipped)
    nxt = artifacts.next_question_field(evidence, answered)
    if nxt is None:
        return RedirectResponse("/report", status_code=303)
    return _render_question(request, evidence, found, nxt)


def _render_question(request: Request, evidence: Evidence, found: dict, field: Field):
    question = QUESTION_BY_FIELD[field]
    total = len(INTERVIEWABLE)
    answered_count = sum(1 for f in INTERVIEWABLE if evidence.has(f) or f in evidence.skipped)
    missing = artifacts.gaps(evidence)
    found_labels = [
        (FIELD_META[Field(k)]["label"], (v[:70] + "…") if len(v) > 70 else v)
        for k, v in found.items()
        if k in {f.value for f in Field}  # skip bookkeeping keys such as _redactions
    ]
    return templates().TemplateResponse(
        request,
        "interview.html",
        {
            "step": min(answered_count + 1, total),
            "total": total,
            "pct": int(100 * answered_count / total),
            "missing_count": len(missing),
            "field": field.value,
            "prompt": question.prompt,
            "placeholder": question.placeholder,
            "mode": question.input_mode,
            "index": len(evidence.values),
            "found_labels": found_labels,
        },
    )


@app.post("/interview")
def interview_post(
    request: Request,
    field: str = Form(...),
    value: str = Form(""),
    skip: str = Form(""),
) -> RedirectResponse:
    evidence, found = load_evidence(request)
    try:
        f = Field(field)
    except ValueError:
        return RedirectResponse("/interview", status_code=303)

    if skip:
        evidence.skip(f)
    else:
        safe, hits = redact(value)
        if redact_summary(hits):
            found["_redactions"] = (found.get("_redactions", 0) or 0) + redact_summary(hits)
        if safe.strip():
            evidence.set(f, safe)
        else:
            evidence.skip(f)

    resp = RedirectResponse("/interview", status_code=303)
    save_evidence(resp, evidence, found)
    return resp


@app.get("/report", response_class=HTMLResponse)
def report_view(request: Request) -> HTMLResponse:
    evidence, found = load_evidence(request)
    return _render_report(request, evidence, found, permalink=None)


def _render_report(request: Request, evidence: Evidence, found: dict,
                   permalink: str | None, rid: str | None = None) -> HTMLResponse:
    rerunnable, missing = artifacts.verdict(evidence)
    src = {}
    try:
        src = json.loads(request.cookies.get("rk_src") or "{}")
    except ValueError:
        src = {}

    permalink = permalink or (
        f"{CONFIG.base_url}/r/{rid}" if rid else None
    )
    md = report_mod.render_markdown(
        evidence,
        source_url=src.get("url"),
        permalink=permalink,
    )
    s = report_mod.stats(evidence)

    # Redactions can happen twice: while analysing the issue text, and every
    # time an answer is submitted in the interview. Both must be counted, or
    # the counter silently reports 0 for the most common case.
    total_redactions = int(src.get("redactions") or 0) + int(
        found.get("_redactions") or 0
    )

    if rid is None:
        store().track("report_completed", {"rerunnable": rerunnable, "present": s["present"]})
        if rerunnable:
            store().track("report_rerunnable", {"present": s["present"]})

    return templates().TemplateResponse(
        request,
        "report.html",
        {
            "markdown": md,
            "rerunnable": rerunnable,
            "missing": [(FIELD_META[f]["label"], FIELD_META[f]["why"]) for f in missing],
            "stats": s,
            "redactions": total_redactions,
            "permalink": permalink,
            "expires_human": f"after {CONFIG.retention_days} days",
        },
    )


@app.post("/save")
def save_report(request: Request) -> RedirectResponse:
    """Persist the current report and redirect to its permalink."""
    evidence, found = load_evidence(request)
    rerunnable, missing = artifacts.verdict(evidence)
    try:
        src = json.loads(request.cookies.get("rk_src") or "{}")
    except ValueError:
        src = {}

    # Mint the id before rendering so the copyable block can link to its own
    # permalink. An agent consuming the report needs the canonical URL inside
    # the artefact itself, not only in the browser address bar.
    rid = new_id()
    permalink = f"{CONFIG.base_url}/r/{rid}"
    md = report_mod.render_markdown(
        evidence, source_url=src.get("url"), permalink=permalink
    )
    s = report_mod.stats(evidence)
    saved_id = store().save_report(
        markdown=md,
        verdict=VERDICT_RERUNNABLE if rerunnable else VERDICT_NOT_RERUNNABLE,
        fields_present=s["present"],
        missing_fields=[f.value for f in missing],
        redactions=int(src.get("redactions") or 0)
        + int(found.get("_redactions") or 0),
        source_url=src.get("url"),
        source_owner=src.get("owner"),
        source_repo=src.get("repo"),
        source_number=src.get("number"),
        pasted_input=bool(src.get("pasted")),
        rid=rid,
    )
    assert saved_id == rid
    store().track("report_shared", {"rerunnable": rerunnable})
    resp = RedirectResponse(f"/r/{rid}", status_code=303)
    clear_state(resp)
    return resp


@app.get("/r/{rid}", response_class=HTMLResponse)
def permalink(request: Request, rid: str) -> HTMLResponse:
    stored = store().get_report(rid)
    if stored is None:
        return templates().TemplateResponse(
            request,
            "404.html",
            {"retention_days": CONFIG.retention_days},
            status_code=404,
        )
    missing_labels = []
    for name in stored.missing_fields:
        try:
            meta = FIELD_META[Field(name)]
        except (ValueError, KeyError):
            continue
        missing_labels.append((meta["label"], meta["why"]))

    return templates().TemplateResponse(
        request,
        "report.html",
        {
            "markdown": stored.markdown,
            "rerunnable": stored.verdict == VERDICT_RERUNNABLE,
            "missing": missing_labels,
            "stats": {
                "present": stored.fields_present,
                "total": 11,
                "missing": 11 - stored.fields_present,
            },
            "redactions": stored.redactions,
            "permalink": f"{CONFIG.base_url}/r/{stored.id}",
            "expires_human": stored.created_at.strftime("%d %b %Y"),
        },
    )


@app.get("/benchmark", response_class=HTMLResponse)
def benchmark(request: Request) -> HTMLResponse:
    """Published study. Empty until it is measured — never estimated."""
    data_file = ROOT / "benchmark" / "results.json"
    ctx: dict = {"has_results": False}
    if data_file.exists():
        try:
            data = json.loads(data_file.read_text(encoding="utf-8"))
            ctx = {
                "has_results": True,
                "median_original": data.get("median_original", "—"),
                "median_reprokit": data.get("median_reprokit", "—"),
                "abandoned": data.get("abandoned", "—"),
                "rows": data.get("rows", []),
            }
        except ValueError:
            ctx = {"has_results": False}
    return templates().TemplateResponse(request, "benchmark.html", ctx)


@app.exception_handler(404)
def not_found(request: Request, exc) -> HTMLResponse:
    return templates().TemplateResponse(
        request, "404.html", {"retention_days": CONFIG.retention_days}, status_code=404
    )
