"""Gap analysis: what a report already contains vs. what it still needs.

This is deliberately deterministic. An LLM is not required to decide whether a
report contains a stack trace — a regex does that better, faster and for free,
and a reviewer can read the code and check the logic. The optional LLM layer
(``app/llm.py``) is only allowed to *phrase* a follow-up question.

The rule for every detector: **be conservative.** A false negative (we ask for
something already present) is mildly annoying. A false positive (we tell the
reporter the field is present when it isn't) produces a report that claims to be
rerunnable and isn't — which breaks the product's only promise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .fields import Evidence, Field

# --------------------------------------------------------------------------- #
# patterns
# --------------------------------------------------------------------------- #

_OS = re.compile(
    r"\b(windows\s*(?:10|11|server)?|win\s*(?:10|11)|macos\s*[\d.]*|os\s*x\s*[\d.]*|"
    r"ubuntu\s*[\d.]*|debian\s*[\d.]*|fedora\s*[\d.]*|centos\s*[\d.]*|arch\s*linux|"
    r"alpine\s*[\d.]*|linux\s*mint|ios\s*[\d.]*|ipados\s*[\d.]*|android\s*[\d.]*|"
    r"wsl2?|raspbian)\b",
    re.IGNORECASE,
)

_RUNTIME = re.compile(
    r"\b(?:node|nodejs)\s*v?\d+\.\d+(?:\.\d+)?|"
    r"\bpython\s*3?\.\d+(?:\.\d+)?|"
    r"\bpypy\s*\d+\.\d+|"
    r"\bnpm\s*\d+\.\d+(?:\.\d+)?|"
    r"\bpnpm\s*\d+\.\d+|"
    r"\byarn\s*\d+\.\d+|"
    r"\bdeno\s*\d+\.\d+|"
    r"\bbun\s*\d+\.\d+|"
    r"\bgo\s*1\.\d+(?:\.\d+)?|"
    r"\brustc\s*\d+\.\d+(?:\.\d+)?|"
    r"\bjava\s*\d+(?:\.\d+)*|"
    r"\bopenjdk\s*\d+(?:\.\d+)*|"
    r"\bdotnet\s*\d+(?:\.\d+)*|"
    r"\bphp\s*\d+\.\d+(?:\.\d+)?|"
    r"\bruby\s*\d+\.\d+(?:\.\d+)?|"
    r"\bpostgres(?:ql)?\s*\d+(?:\.\d+)?|"
    r"\bmysql\s*\d+(?:\.\d+)?|"
    r"\bredis\s*\d+(?:\.\d+)?|"
    r"\b\d+\.\d+\.\d+\b",
    re.IGNORECASE,
)

# a bare version next to a package name, e.g. "react 18.2.0", "django==4.2.1"
_PKG_VERSION = re.compile(
    r"\b[a-z][a-z0-9._\-]{2,}\s*(?:==|@|v)\s*\d+\.\d+(?:\.\d+)?", re.IGNORECASE
)

_VERSION_FLAG = re.compile(r"--version\b|\bversion[:\s]", re.IGNORECASE)

_NUMBERED_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+\S", re.MULTILINE)

_FENCE = re.compile(r"```.*?```", re.DOTALL)

_ERROR_SIGNAL = re.compile(
    r"(traceback \(most recent call last\)|"
    r"^\s*at\s+\S+\s*\(.*:\d+:\d+\)|"
    r"\b(unhandled|fatal|panic:|segmentation fault|core dumped)\b|"
    r"\b[A-Z][A-Za-z]*(?:Error|Exception)\b|"
    r"\berror\b\s*[:\-]|"
    r"\bE\s{2,}\w|"  # pytest failure lines
    r"exit code\s*\d+|"
    r"status(?:\s*code)?\s*[:\s]\s*[45]\d\d)",
    re.IGNORECASE | re.MULTILINE,
)

_EXPECTED = re.compile(
    r"\b(expected|expecting|should|supposed to|ought to)\b", re.IGNORECASE
)

_ACTUAL = re.compile(
    r"\b(actual|actually|instead|but (?:it|i|we) (?:get|got|see|saw)|"
    r"gets?|returns?|threw|throws|shows?|displays?)\b",
    re.IGNORECASE,
)

_FREQUENCY = re.compile(
    r"\b(always|every time|each time|consistently|reliably|"
    r"sometimes|occasionally|intermittent(?:ly)?|random(?:ly)?|flaky|"
    r"\d+\s*(?:/|out of|of)\s*\d+\s*(?:runs?|times?|attempts?)?|"
    r"\d+\s*(?:failures?|errors?|crashes?)\s+(?:in|out of|/)\s*\d+|"
    r"\d+\s*(?:runs?|times?|attempts?)\b)",
    re.IGNORECASE,
)

_NEGATIVE_CONTROL = re.compile(
    r"\b(only\s+(?:happens?|occurs?|fails?|crashes?|on|when|with|if|in)|"
    r"works? (?:fine |ok |okay )?(?:on|with|in|when)|"
    r"does(?:n't| not) (?:happen|occur|reproduce|trigger)|"
    r"(?:not|cannot|can't|unable to) reproduce|no issues? (?:on|with)|"
    r"fails? only|reproduces? only|happens? only)\b",
    re.IGNORECASE,
)

_LIMITS = re.compile(
    r"\b(did ?n[o']?t test|have ?n[o']?t tried|not (?:yet )?tested|"
    r"untested|did ?n[o']?t try|haven't checked|not verified)\b",
    re.IGNORECASE,
)

_STEPS_HEADING = re.compile(
    r"\b(steps to reproduce|to reproduce|reproduction steps|how to reproduce|"
    r"steps|repro)\b",
    re.IGNORECASE,
)

_FILLER = {"it", "is", "was", "a", "the", "my", "pls", "please", "help", "keeps", "just", "still"}

_VAGUE = {
    "it broke",
    "broke",
    "broke.",
    "breaks",
    "failing",
    "wrong",
    "broken",
    "doesn't work",
    "does not work",
    "not working",
    "error",
    "failed",
    "fail",
    "bug",
    "issue",
    "crash",
    "crashes",
    "help",
    "nothing works",
    "not working",
    "doesnt work",
    "doesn't work.",
    "asdf",
    "idk",
}


# --------------------------------------------------------------------------- #
# result type
# --------------------------------------------------------------------------- #


@dataclass
class Detection:
    """A field found in the report body, with the snippet that satisfied it."""

    field: Field
    snippet: str


def _first_fence(text: str) -> str | None:
    m = _FENCE.search(text)
    return m.group(0) if m else None


def _line_matching(text: str, pattern: re.Pattern[str]) -> str | None:
    for line in text.splitlines():
        if pattern.search(line):
            stripped = line.strip()
            if 3 <= len(stripped) <= 300:
                return stripped
    return None


def _is_vague(value: str) -> bool:
    """A symptom is only useful if it names a behaviour, not a mood."""
    v = " ".join(value.strip().strip(".!").lower().split())
    if v in _VAGUE:
        return True
    words = [w for w in re.split(r"[^a-z0-9']+", v) if w]
    if len(words) < 3:
        return True
    # "it broke pls help" — a plea, not a symptom
    if all(w in _VAGUE or w in _FILLER for w in words):
        return True
    return False


# --------------------------------------------------------------------------- #
# the detectors
# --------------------------------------------------------------------------- #


def detect_symptom(title: str, body: str) -> str | None:
    """The title is the symptom unless it is useless."""
    candidate = (title or "").strip()
    if candidate and not _is_vague(candidate) and len(candidate) >= 8:
        return candidate
    for line in (body or "").splitlines():
        s = line.strip().strip("#").strip()
        if len(s) >= 12 and not _is_vague(s) and not s.lower().startswith(("os:", "version")):
            return s
    return None


def detect_environment(text: str) -> str | None:
    m = _OS.search(text)
    if m:
        line = _line_matching(text, _OS) or m.group(0)
        return line
    return None


def detect_runtime_version(text: str) -> str | None:
    m = _RUNTIME.search(text) or _PKG_VERSION.search(text)
    if m:
        line = _line_matching(text, _RUNTIME) or _line_matching(text, _PKG_VERSION)
        return line or m.group(0)
    return None


def detect_steps(text: str) -> str | None:
    heading = _STEPS_HEADING.search(text)
    items = _NUMBERED_ITEM.findall(text)
    if heading and items:
        # capture the block following the heading
        idx = heading.end()
        block = text[idx : idx + 600].strip()
        return block or "\n".join(items[:6])
    if len(items) >= 2:
        return "\n".join(l.strip() for l in text.splitlines() if _NUMBERED_ITEM.match(l))[:600]
    # a command inside a fence is a weaker but real signal
    fence = _first_fence(text)
    if fence and re.search(r"[$#>]\s*\w|^\s*(npm|npx|python|pip|go|cargo|node|docker)\b",
                           fence, re.MULTILINE):
        return fence.strip()[:600]
    return None


def detect_error_output(text: str) -> str | None:
    fence = _first_fence(text)
    if fence and _ERROR_SIGNAL.search(fence):
        return fence.strip()[:2000]
    line = _line_matching(text, _ERROR_SIGNAL)
    if line:
        # gather the following few lines, they are usually the trace
        lines = text.splitlines()
        try:
            start = lines.index(line)
        except ValueError:
            return line
        block = "\n".join(lines[start : start + 12]).strip()
        return block[:2000]
    return None


def _section_after(text: str, heading: re.Pattern[str], max_chars: int = 400) -> str | None:
    """Content following a heading line, up to the next heading."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        probe = line.strip().lstrip("#").strip().rstrip(":").strip()
        if not probe or not heading.fullmatch(probe):
            if not heading.search(line):
                continue
        body: list[str] = []
        for nxt in lines[i + 1 :]:
            if nxt.strip().startswith("#") or re.match(r"^\s*[A-Z][A-Za-z ]{2,20}:\s*$", nxt):
                break
            body.append(nxt)
            if sum(len(b) for b in body) > max_chars:
                break
        block = "\n".join(body).strip()
        if block:
            return block[:max_chars]
    return None


_EXPECTED_HEADING = re.compile(r"(?i)(expected(?:\s+(?:result|behaviou?r|outcome))?|expectation)")
_ACTUAL_HEADING = re.compile(r"(?i)(actual(?:\s+(?:result|behaviou?r|outcome))?|what happened|observed)")


def _first_meaningful_line(text: str, pattern: re.Pattern[str], min_len: int = 12) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) < min_len:
            continue
        if pattern.search(stripped):
            return stripped
    return None


def detect_expected(text: str) -> str | None:
    block = _section_after(text, _EXPECTED_HEADING)
    if block and not _is_vague(block):
        return block
    line = _first_meaningful_line(text, _EXPECTED)
    if line and not _is_vague(line):
        return line
    return None


def detect_actual(text: str) -> str | None:
    block = _section_after(text, _ACTUAL_HEADING)
    if block and not _is_vague(block):
        return block
    line = _first_meaningful_line(text, _ACTUAL)
    if line and not _is_vague(line):
        return line
    return None


def detect_frequency(text: str) -> str | None:
    m = _FREQUENCY.search(text)
    if m:
        line = _line_matching(text, _FREQUENCY)
        return line or m.group(0)
    return None


def detect_negative_control(text: str) -> str | None:
    m = _NEGATIVE_CONTROL.search(text)
    if m:
        line = _line_matching(text, _NEGATIVE_CONTROL)
        return line or m.group(0)
    return None


_CODE_SIGNAL = re.compile(
    r"[;{}()=\[\]]|\b(?:import|from|require|def|function|class|const|let|var|"
    r"return|async|await|print|console\.log|npm|npx|pip|node|curl)\b"
)


def _looks_like_code(fence: str) -> bool:
    inner = fence.strip().strip("`").strip()
    if len(inner) < 8:
        return False
    return bool(_CODE_SIGNAL.search(inner))


def detect_minimal_repro(text: str) -> str | None:
    """A repro is code, not the error dump we already claimed as error output.

    Short snippets count: a three-token reproduction is the best possible one.
    """
    for fence in _FENCE.findall(text):
        if _ERROR_SIGNAL.search(fence):
            continue
        if _looks_like_code(fence) or len(fence) > 40:
            return fence.strip()[:2000]
    return None


def detect_limits(text: str) -> str | None:
    line = _line_matching(text, _LIMITS)
    return line


DETECTORS = {
    Field.ENVIRONMENT: detect_environment,
    Field.RUNTIME_VERSION: detect_runtime_version,
    Field.STEPS: detect_steps,
    Field.EXPECTED: detect_expected,
    Field.ACTUAL: detect_actual,
    Field.ERROR_OUTPUT: detect_error_output,
    Field.FREQUENCY: detect_frequency,
    Field.NEGATIVE_CONTROL: detect_negative_control,
    Field.MINIMAL_REPRO: detect_minimal_repro,
    Field.LIMITS: detect_limits,
}


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #


def analyse(title: str, body: str) -> tuple[Evidence, dict[Field, str]]:
    """Run every detector over a report.

    Returns:
        evidence: the fields that are already present.
        found:    field -> snippet, for showing the reporter what we spotted.
    """
    text = f"{title}\n\n{body or ''}"
    evidence = Evidence()
    found: dict[Field, str] = {}

    symptom = detect_symptom(title, body)
    if symptom:
        evidence.set(Field.SYMPTOM, symptom)
        found[Field.SYMPTOM] = symptom

    for f, detector in DETECTORS.items():
        snippet = detector(text)
        if snippet:
            evidence.set(f, snippet)
            found[f] = snippet

    return evidence, found


def gaps(evidence: Evidence) -> list[Field]:
    """Fields still missing, in interview priority order."""
    return evidence.missing()


def verdict(evidence: Evidence) -> tuple[bool, list[Field]]:
    """``(rerunnable, missing_fields)``."""
    missing = gaps(evidence)
    return (len(missing) == 0, missing)


def next_question_field(evidence: Evidence, answered: set[Field]) -> Field | None:
    """The highest-priority field that is still missing and not yet asked."""
    for f in gaps(evidence):
        if f not in answered and f is not Field.SYMPTOM:
            return f
    return None
