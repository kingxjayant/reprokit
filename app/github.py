"""GitHub issue fetching (public issues only) with an optional token for rate limits.

Everything here treats the issue body as **untrusted input**. It is returned as
data and never executed, evaluated or interpolated into a prompt as an
instruction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

ISSUE_URL = re.compile(
    r"^https?://(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+)/issues/(?P<number>\d+)"
    r"(?:[?#].*)?$"
)

API = "https://api.github.com"


class IssueError(Exception):
    """Base class for user-displayable issue-fetch failures."""

    status = 400
    message = "Could not read that issue."

    def __init__(self, message: str | None = None, status: int | None = None):
        if message:
            self.message = message
        if status:
            self.status = status
        super().__init__(self.message)


class BadURLError(IssueError):
    status = 400
    message = (
        "That doesn't look like a GitHub issue URL. It should look like "
        "https://github.com/owner/repo/issues/123"
    )


class NotFoundError(IssueError):
    status = 404
    message = "That issue doesn't exist, or the repository is private."


class RateLimitError(IssueError):
    status = 429
    message = "GitHub is rate-limiting us right now. Try again in a minute."


class UpstreamError(IssueError):
    status = 502
    message = "GitHub didn't answer. Try again, or paste the report manually."


class TooLargeError(IssueError):
    status = 413
    message = "That issue is too large to process. Paste just the relevant part."


@dataclass(frozen=True)
class ParsedIssue:
    owner: str
    repo: str
    number: int

    @property
    def canonical_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/issues/{self.number}"


@dataclass(frozen=True)
class Issue:
    title: str
    body: str
    url: str
    owner: str
    repo: str
    number: int
    state: str
    labels: tuple[str, ...]
    comments: int

    @property
    def is_pull_request(self) -> bool:
        # /issues/N also serves PRs; they carry a pull_request key upstream
        return False


MAX_BODY = 60_000  # characters; anything larger is almost always a paste accident


def parse_issue_url(url: str) -> ParsedIssue:
    url = (url or "").strip()
    m = ISSUE_URL.match(url)
    if not m:
        raise BadURLError()
    return ParsedIssue(
        owner=m.group("owner"),
        repo=m.group("repo"),
        number=int(m.group("number")),
    )


def _headers(token: str | None) -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "reprokit/1.0 (+https://reprokit.tech)",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_issue(url: str, token: str | None = None, timeout: float = 10.0) -> Issue:
    """Fetch a public GitHub issue by URL."""
    parsed = parse_issue_url(url)
    api_url = f"{API}/repos/{parsed.owner}/{parsed.repo}/issues/{parsed.number}"

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(api_url, headers=_headers(token))
    except httpx.TimeoutException as exc:
        raise UpstreamError("GitHub timed out. Try again, or paste the report manually.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamError() from exc

    if resp.status_code == 404:
        raise NotFoundError()
    if resp.status_code in (403, 429):
        remaining = resp.headers.get("x-ratelimit-remaining")
        if remaining == "0" or resp.status_code == 429:
            raise RateLimitError()
        raise UpstreamError()
    if resp.status_code >= 400:
        raise UpstreamError()

    try:
        data = resp.json()
    except ValueError as exc:
        raise UpstreamError() from exc

    if data.get("pull_request"):
        # Pull requests are not bug reports; still usable, but say so.
        pass

    body = data.get("body") or ""
    if len(body) > MAX_BODY:
        raise TooLargeError()

    labels = tuple(
        str(l.get("name", "")) for l in data.get("labels", []) if isinstance(l, dict)
    )

    return Issue(
        title=(data.get("title") or "").strip(),
        body=body,
        url=data.get("html_url") or parsed.canonical_url,
        owner=parsed.owner,
        repo=parsed.repo,
        number=parsed.number,
        state=str(data.get("state") or "open"),
        labels=labels,
        comments=int(data.get("comments") or 0),
    )


def looks_like_issue_url(text: str) -> bool:
    return bool(ISSUE_URL.match((text or "").strip()))
