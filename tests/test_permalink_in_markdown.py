"""The stored report must contain its own permalink.

Bug this guards against (found against the live deployment, 2026-11-24):
`POST /save` rendered the Markdown *before* calling `store().save_report()`,
and the store minted the report id internally — so the caller could never pass
a permalink to the renderer. The result was a saved report whose copyable
Markdown block had no link back to itself. The browser address bar showed
`/r/<id>`, but the artefact a maintainer or an agent copies out of it had no
canonical URL, which defeats the point of publishing a permalink.

These tests fail against the pre-fix code.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def _save(client) -> tuple[str, str]:
    client.post(
        "/analyse",
        data={"issue_url": "", "title": "Save returns 500 on empty payload", "body": "some body"},
        follow_redirects=False,
    )
    resp = client.post("/save", follow_redirects=False)
    assert resp.status_code == 303, resp.status_code
    rid = resp.headers["location"].rsplit("/", 1)[-1]
    return rid, client.get(f"/r/{rid}").text


def test_saved_markdown_links_to_its_own_permalink(client):
    rid, html = _save(client)
    # the Markdown block is rendered inside <pre>; the link must be there
    assert f"/r/{rid}" in html, "permalink missing from the saved report page"
    assert re.search(r"\[Permalink\]\(https?://[^)]*/r/" + rid + r"\)", html), (
        "the copyable Markdown block must carry a [Permalink](...) footer line"
    )


def test_permalink_uses_the_configured_base_url(client):
    """The footer must use APP_BASE_URL, not whatever host the request arrived on."""
    from app.env import get_config

    rid, html = _save(client)
    expected = get_config().base_url.rstrip("/")
    m = re.search(r"\[Permalink\]\((https?://[^)]*)/r/" + rid + r"\)", html)
    assert m, "no footer permalink"
    assert m.group(1) == expected, f"expected {expected}, got {m.group(1)}"


def test_the_stored_row_and_the_url_agree(client):
    """The id in the footer must be the id the store actually saved."""
    rid, html = _save(client)
    assert client.get(f"/r/{rid}").status_code == 200
    assert f"/r/{rid}" in html


def test_save_still_works_without_an_explicit_id(client):
    """rid is optional: anything else calling save_report keeps working."""
    from app.db import get_store

    store = get_store()
    rid = store.save_report(
        markdown="# report",
        verdict="not_rerunnable",
        fields_present=3,
        missing_fields=["steps"],
        redactions=0,
    )
    assert rid and store.get_report(rid) is not None
