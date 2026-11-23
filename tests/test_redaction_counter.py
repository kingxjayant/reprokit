"""The redaction counter must count redactions from *both* phases.

Bug this guards against (found against the live deployment, 2026-11-23):
`POST /interview` redacted secrets correctly and stored the count in the state
cookie under `_redactions`, but `/report` and `/save` only read `rk_src`
(a count of redactions made while analysing the issue). So a reporter who
pasted a token into an interview answer — the most likely place for it — saw
no counter and the database recorded `redactions = 0`, even though the stored
Markdown correctly contained `[REDACTED:...]` markers.

These tests fail against the pre-fix code.
"""

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWX012345"


@pytest.fixture()
def client():
    return TestClient(app)


def _next_field(html: str) -> str | None:
    m = re.search(r'name="field" value="([a-z_]+)"', html)
    return m.group(1) if m else None


def _start(client, body: str = "minimal pasted report body") -> None:
    """Seed state through the free-text fallback (no network needed)."""
    r = client.post(
        "/analyse",
        data={"issue_url": "", "title": "Save returns 500 on empty payload", "body": body},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.status_code


def _state(client) -> dict:
    """Decode the rk_state cookie (http.cookies quotes non-ASCII separators)."""
    raw = client.cookies.get("rk_state")
    assert raw, "no state cookie"
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    raw = raw.replace("\\054", ",").replace('\\"', '"')
    return json.loads(raw)


def _answer_one_secret(client, how_many: int = 1) -> list[str]:
    answered = []
    for _ in range(how_many):
        field = _next_field(client.get("/interview").text)
        if field is None:
            break
        client.post(
            "/interview",
            data={"field": field, "value": f"token {TOKEN} leaked while running"},
        )
        answered.append(field)
    return answered


def test_state_cookie_records_interview_redactions(client):
    _start(client)
    answered = _answer_one_secret(client, 1)
    assert answered, "interview produced no question"

    state = _state(client)
    assert state["found"]["_redactions"] >= 1, (
        "interview redaction was not recorded in the state cookie"
    )


def test_report_page_shows_counter_for_interview_redactions(client):
    _start(client)
    _answer_one_secret(client, 1)

    html = client.get("/report").text
    assert "REDACTED:github_token" in html, "marker missing from report body"
    m = re.search(r'<p class="redactions">\s*(\d+) secret', html)
    assert m, "no redaction counter rendered on /report"
    assert int(m.group(1)) >= 1, "counter rendered but reported zero"


def test_counter_accumulates_across_answers(client):
    _start(client)
    answered = _answer_one_secret(client, 3)
    assert len(answered) >= 2

    state = _state(client)
    assert state["found"]["_redactions"] >= 2, "counter did not accumulate"


def test_save_persists_redaction_count(client):
    _start(client)
    _answer_one_secret(client, 1)

    resp = client.post("/save", follow_redirects=False)
    assert resp.status_code == 303, resp.status_code
    rid = resp.headers["location"].rsplit("/", 1)[-1]

    stored = client.get(f"/r/{rid}").text
    m = re.search(r'<p class="redactions">\s*(\d+) secret', stored)
    assert m, "permalink page lost the redaction counter"
    assert int(m.group(1)) >= 1, "permalink reported zero redactions after save"


def test_bookkeeping_key_never_leaks_into_page(client):
    _start(client)
    _answer_one_secret(client, 1)
    html = client.get("/interview").text + client.get("/report").text
    assert "_redactions" not in html


def test_nothing_secret_is_ever_stored(client):
    _start(client)
    _answer_one_secret(client, 2)
    resp = client.post("/save", follow_redirects=False)
    assert resp.status_code == 303, resp.status_code
    rid = resp.headers["location"].rsplit("/", 1)[-1]

    for page in ("/report", f"/r/{rid}"):
        assert TOKEN not in client.get(page).text, f"raw token survived on {page}"
