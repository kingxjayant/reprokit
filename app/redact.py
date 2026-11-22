"""Server-side secret redaction.

Runs on every piece of reporter-supplied text **before** it is stored, rendered
or included in a generated report. Redactions are typed — ``[REDACTED:github_token]``
rather than a silent deletion — so a maintainer can see that something was
removed and what kind of thing it was.

Design notes:
* Patterns are deliberately conservative: a redaction is cheap, a leaked
  credential is not.
* Every rule is a named :class:`Rule` so tests can target them individually.
* No network calls, no external deps. Pure regex, fast enough to run twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    replacement: str


def _r(name: str, pattern: str, replacement: str) -> Rule:
    return Rule(name, re.compile(pattern), replacement)


#: Order matters: specific token shapes first, generic assignments last.
RULES: tuple[Rule, ...] = (
    # --- private keys and certs: redact the whole block ---
    Rule(
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"
            r".*?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED:private_key]",
    ),
    # --- provider-shaped tokens ---
    _r("github_token", r"\bgh[pousr]_[A-Za-z0-9]{16,}\b", "[REDACTED:github_token]"),
    _r(
        "github_fine_grained",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
        "[REDACTED:github_token]",
    ),
    _r("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "[REDACTED:aws_access_key]"),
    _r(
        "aws_secret_key",
        r"(?i)\baws_secret_access_key\s*[=:]\s*\S+",
        "aws_secret_access_key=[REDACTED:aws_secret_key]",
    ),
    _r("slack_token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "[REDACTED:slack_token]"),
    _r("stripe_key", r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b", "[REDACTED:stripe_key]"),
    _r("google_api_key", r"\bAIza[0-9A-Za-z_\-]{35}\b", "[REDACTED:google_api_key]"),
    _r(
        "supabase_key",
        r"\beyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}",
        "[REDACTED:supabase_key]",
    ),
    _r("openai_key", r"\bsk-[A-Za-z0-9]{20,}\b", "[REDACTED:openai_key]"),
    _r("npm_token", r"\bnpm_[A-Za-z0-9]{30,}\b", "[REDACTED:npm_token]"),
    _r("jwt", r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b", "[REDACTED:jwt]"),
    _r(
        "url_credentials",
        r"\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@",
        r"\1[REDACTED:url_credentials]@",
    ),
    _r(
        "bearer_token",
        r"(?i)\b(bearer)\s+[A-Za-z0-9._\-+/=]{12,}",
        r"\1 [REDACTED:bearer_token]",
    ),
    # --- generic key=value / key: value assignments ---
    _r(
        "assigned_secret",
        r"(?i)([A-Za-z0-9_.\-]*(?:api[_-]?key|apikey|api[_-]?secret|access[_-]?token|"
        r"auth[_-]?token|client[_-]?secret|refresh[_-]?token|secret[_-]?key|password|"
        r"passwd|pwd|token|secret))\s*[=:]\s*(['\"]?)([^\s'\"&,;]{6,})\2",
        r"\1=[REDACTED:assigned_secret]",
    ),
    # --- host paths leak usernames (and sometimes client names) ---
    _r(
        "unix_home_path",
        r"(?<![\w/])/(?:home|Users)/([A-Za-z0-9._\-]+)",
        "/home/[REDACTED:username]",
    ),
    _r(
        "windows_home_path",
        r"[A-Za-z]:\\\\?Users\\\\?([A-Za-z0-9._\-]+)",
        r"C:\\Users\\[REDACTED:username]",
    ),
    # --- email addresses ---
    _r(
        "email",
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        "[REDACTED:email]",
    ),
)


def redact(text: str) -> tuple[str, list[tuple[str, int]]]:
    """Redact secrets from ``text``.

    Returns the cleaned text and a list of ``(rule_name, count)`` for every rule
    that fired, so the UI can show a redaction counter.
    """
    if not text:
        return "", []
    hits: list[tuple[str, int]] = []
    out = text
    for rule in RULES:
        out, n = rule.pattern.subn(rule.replacement, out)
        if n:
            hits.append((rule.name, n))
    return out, hits


def redact_summary(hits: list[tuple[str, int]]) -> int:
    """Total number of individual redactions performed."""
    return sum(n for _, n in hits)


def rule_names() -> list[str]:
    """Every rule name, for tests and docs."""
    return [r.name for r in RULES]
