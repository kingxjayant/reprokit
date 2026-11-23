"""End-to-end flow tests: the 90-second stranger path.

These drive the app exactly as a browser would, with the network stubbed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import github, main
from app.db import SQLiteStore

from tests.conftest import FakeResponse, patch_client

ISSUE_URL = "https://github.com/o/r/issues/1"

THIN_ISSUE = {
    "title": "Save button does nothing",
    "body": "When I click save nothing happens. Please fix.",
    "html_url": ISSUE_URL,
    "state": "open",
    "labels": [{"name": "bug"}],
    "comments": 2,
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "app.db")
    store.init_schema()
    main.configure(store=store)
    # never touch the real network
    patch_client(monkeypatch, github, lambda url, headers: FakeResponse(200, THIN_ISSUE))
    c = TestClient(main.app)
    c.store = store
    return c


# --------------------------------------------------------------------------- #
# basic pages
# --------------------------------------------------------------------------- #


def test_index_renders_with_no_login(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "GitHub issue URL" in r.text
    assert "No signup" in r.text


def test_healthz_leaks_no_secrets(client):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert "DATABASE_URL" not in str(body)
    assert "token" not in str(body).lower()


def test_benchmark_refuses_to_show_invented_numbers(client):
    r = client.get("/benchmark")
    assert r.status_code == 200
    assert "Study in progress" in r.text
    assert "No numbers are published" in r.text.replace("\n", " ")


# --------------------------------------------------------------------------- #
# intake
# --------------------------------------------------------------------------- #


def test_bad_url_is_rejected_with_guidance(client):
    r = client.post("/analyse", data={"issue_url": "https://example.com/x"})
    assert r.status_code == 400
    assert "doesn&#39;t look like a GitHub issue URL" in r.text or "look like a GitHub" in r.text


def test_issue_404_is_explained(client, monkeypatch):
    patch_client(monkeypatch, github, lambda url, headers: FakeResponse(404, {}))
    r = client.post("/analyse", data={"issue_url": ISSUE_URL})
    assert r.status_code == 404
    assert "private" in r.text.lower()


def test_empty_paste_is_rejected(client):
    r = client.post("/analyse", data={"issue_url": "", "title": "", "body": ""})
    assert r.status_code == 400


def test_thin_issue_goes_to_the_interview(client):
    r = client.post("/analyse", data={"issue_url": ISSUE_URL}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/interview"


def test_complete_pasted_report_skips_straight_to_the_report(client):
    body = """
Environment: Ubuntu 24.04, Node 22.11.0
Steps to reproduce
1. open app
2. click save
Expected: 200 and the row is saved
Actual: returns 500 with {"error":"bad gateway"}
Error output
```
TypeError: cannot read properties of undefined
    at save (a.js:1:1)
```
Frequency: 3 failures in 3 runs
Does not trigger when: works fine on macOS
Minimal reproduction
```js
save({});
```
Not tested: did not test with a fresh DB
"""
    r = client.post(
        "/analyse",
        data={"issue_url": "", "title": "Save returns 500 on empty payload", "body": body},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/report"


# --------------------------------------------------------------------------- #
# the interview
# --------------------------------------------------------------------------- #


def test_interview_shows_progress_and_a_skip_button(client):
    client.post("/analyse", data={"issue_url": ISSUE_URL})
    r = client.get("/interview")
    assert r.status_code == 200
    assert "answered" in r.text
    assert "Skip — I don&#39;t know" in r.text or "Skip" in r.text
    assert "Already found in the report" in r.text


def test_answering_advances_through_questions(client):
    client.post("/analyse", data={"issue_url": ISSUE_URL})
    seen = []
    for _ in range(12):
        r = client.get("/interview", follow_redirects=False)
        if r.status_code == 303:
            break
        seen.append(r.text)
        # answer whatever hidden field the page is asking for
        import re

        m = re.search(r'name="field" value="([a-z_]+)"', r.text)
        assert m, "question page must name the field it is asking for"
        client.post(
            "/interview",
            data={"field": m.group(1), "value": "a concrete answer"},
            follow_redirects=False,
        )
    assert len(seen) >= 5
    r = client.get("/report")
    assert r.status_code == 200
    assert "Reproduction report" in r.text


def test_skip_marks_field_absent_not_filled(client):
    client.post("/analyse", data={"issue_url": ISSUE_URL})
    r = client.get("/interview")
    import re

    m = re.search(r'name="field" value="([a-z_]+)"', r.text)
    field = m.group(1)
    client.post("/interview", data={"field": field, "skip": "1"}, follow_redirects=False)
    # the same question must not be offered again
    r2 = client.get("/interview")
    m2 = re.search(r'name="field" value="([a-z_]+)"', r2.text or "")
    assert m2 is None or m2.group(1) != field


def test_secrets_typed_into_an_answer_are_redacted(client):
    client.post("/analyse", data={"issue_url": ISSUE_URL})
    import re

    r = client.get("/interview")
    field = re.search(r'name="field" value="([a-z_]+)"', r.text).group(1)
    client.post(
        "/interview",
        data={"field": field, "value": "my token is ghp_abcdefghijklmnopqrstuvwxyz0123"},
        follow_redirects=False,
    )
    r = client.get("/report")
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123" not in r.text
    assert "[REDACTED:github_token]" in r.text


# --------------------------------------------------------------------------- #
# the report and its permalink
# --------------------------------------------------------------------------- #


def test_report_states_the_verdict_and_the_gaps(client):
    client.post("/analyse", data={"issue_url": ISSUE_URL})
    r = client.get("/report")
    assert "Not yet rerunnable" in r.text
    assert "Still missing" in r.text
    assert "does not claim the bug was reproduced" in r.text


def test_save_creates_a_permalink_and_the_permalink_expires_language(client):
    client.post("/analyse", data={"issue_url": ISSUE_URL})
    for _ in range(12):
        r = client.get("/interview", follow_redirects=False)
        if r.status_code == 303:
            break
        import re

        m = re.search(r'name="field" value="([a-z_]+)"', r.text)
        client.post("/interview", data={"field": m.group(1), "value": "answer"}, follow_redirects=False)

    r = client.post("/save", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/r/")
    rid = loc.split("/r/")[1]

    page = client.get(f"/r/{rid}")
    assert page.status_code == 200
    assert "Reproduction report" in page.text
    assert client.store.get_report(rid) is not None


def test_unknown_permalink_is_a_friendly_404(client):
    r = client.get("/r/doesnotexist")
    assert r.status_code == 404
    assert "isn&#39;t here" in r.text or "isn't here" in r.text


def test_report_page_offers_copy_and_another(client):
    client.post("/analyse", data={"issue_url": ISSUE_URL})
    r = client.get("/report")
    assert "Copy Markdown" in r.text
    assert "Start another report" in r.text


# --------------------------------------------------------------------------- #
# analytics contract
# --------------------------------------------------------------------------- #


def test_visits_are_not_counted_as_completions(client):
    for _ in range(5):
        client.get("/")
    f = client.store.funnel()
    assert f.started >= 5
    assert f.completed == 0
