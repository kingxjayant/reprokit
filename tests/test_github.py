"""Tests for GitHub issue URL parsing and fetching (network is stubbed)."""

from __future__ import annotations

import httpx
import pytest

from app import github

from tests.conftest import FakeResponse, patch_client

VALID = "https://github.com/psf/requests/issues/6543"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Fail loudly if any test makes a real HTTP call."""

    class Exploding(httpx.Client):
        def get(self, *a, **k):  # pragma: no cover
            raise AssertionError("test attempted a real network call")

    monkeypatch.setattr(github.httpx, "Client", Exploding)


def test_parse_valid_url():
    p = github.parse_issue_url(VALID)
    assert (p.owner, p.repo, p.number) == ("psf", "requests", 6543)
    assert p.canonical_url == VALID


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/o/r/pull/12",
        "https://gitlab.com/o/r/issues/1",
        "github.com/o/r/issues/1",
        "https://github.com/o/r/issues/",
        "not a url",
        "",
    ],
)
def test_parse_rejects_invalid_urls(url):
    with pytest.raises(github.BadURLError):
        github.parse_issue_url(url)


def test_parse_accepts_query_string_and_anchor():
    p = github.parse_issue_url(VALID + "?foo=bar#issuecomment-1")
    assert p.number == 6543


def test_fetch_success(monkeypatch):
    payload = {
        "title": "createItem crashes",
        "body": "steps...",
        "html_url": VALID,
        "state": "open",
        "labels": [{"name": "bug"}],
        "comments": 3,
    }
    patch_client(monkeypatch, github, lambda url, headers: FakeResponse(200, payload))
    issue = github.fetch_issue(VALID)
    assert issue.title == "createItem crashes"
    assert issue.labels == ("bug",)
    assert issue.comments == 3


def test_fetch_sends_no_auth_header_without_token(monkeypatch):
    seen = {}

    def handler(url, headers):
        seen.update(headers)
        return FakeResponse(200, {"title": "t", "body": "b", "html_url": VALID})

    patch_client(monkeypatch, github, handler)
    github.fetch_issue(VALID)
    assert "Authorization" not in seen


def test_fetch_sends_bearer_token_when_configured(monkeypatch):
    seen = {}

    def handler(url, headers):
        seen.update(headers)
        return FakeResponse(200, {"title": "t", "body": "b", "html_url": VALID})

    patch_client(monkeypatch, github, handler)
    github.fetch_issue(VALID, token="ghp_test")
    assert seen["Authorization"] == "Bearer ghp_test"


def test_fetch_404(monkeypatch):
    patch_client(monkeypatch, github, lambda url, headers: FakeResponse(404, {}))
    with pytest.raises(github.NotFoundError):
        github.fetch_issue(VALID)


def test_fetch_rate_limited(monkeypatch):
    patch_client(
        monkeypatch,
        github,
        lambda url, headers: FakeResponse(429, {}, headers={"x-ratelimit-remaining": "0"}),
    )
    with pytest.raises(github.RateLimitError):
        github.fetch_issue(VALID)


def test_fetch_500(monkeypatch):
    patch_client(monkeypatch, github, lambda url, headers: FakeResponse(500, {}))
    with pytest.raises(github.UpstreamError):
        github.fetch_issue(VALID)


def test_fetch_oversized_body_rejected(monkeypatch):
    payload = {"title": "t", "body": "x" * 70_000, "html_url": VALID}
    patch_client(monkeypatch, github, lambda url, headers: FakeResponse(200, payload))
    with pytest.raises(github.TooLargeError):
        github.fetch_issue(VALID)


def test_empty_body_is_tolerated(monkeypatch):
    payload = {"title": "t", "html_url": VALID}
    patch_client(monkeypatch, github, lambda url, headers: FakeResponse(200, payload))
    issue = github.fetch_issue(VALID)
    assert issue.body == ""


def test_looks_like_issue_url():
    assert github.looks_like_issue_url(VALID)
    assert not github.looks_like_issue_url("hello")
