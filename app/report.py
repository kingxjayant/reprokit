"""Generate the copy-pasteable reproduction report.

The output shape is fixed by the build spec (§5). Two invariants:

1. Every value is redacted again here. Redaction already happened at input,
   but this function is the last place data can leak, so it re-checks.
2. The closing disclaimer is never omitted. It is what makes the artefact
   honest: a report is evidence, not a claim that the bug was reproduced.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .fields import Evidence, Field
from .redact import redact

DISCLAIMER = (
    "This report does not claim the bug was reproduced. It contains the evidence "
    "a maintainer needs to attempt a reproduction, generated with ReproKit."
)

#: Fields that render as fenced blocks rather than inline text.
FENCED = {Field.ERROR_OUTPUT, Field.MINIMAL_REPRO}


def _clean(value: str) -> str:
    """Final-pass redaction + whitespace normalisation."""
    safe, _ = redact(value or "")
    return safe.strip()


def _inline(value: str) -> str:
    return " ".join(_clean(value).split())


def _fence(value: str, lang: str = "") -> str:
    body = _clean(value)
    # a fence inside a fence breaks Markdown; use a longer fence
    ticks = "````" if "```" in body else "```"
    return f"{ticks}{lang}\n{body}\n{ticks}"


def _steps(value: str) -> str:
    body = _clean(value)
    lines = [l.rstrip() for l in body.splitlines() if l.strip()]
    if not lines:
        return "_not provided_"
    already_numbered = all(
        l.lstrip().startswith(tuple("0123456789-*")) for l in lines
    )
    if already_numbered:
        return "\n".join(lines)
    return "\n".join(f"{i}. {l.lstrip('-* ').strip()}" for i, l in enumerate(lines, 1))


def _value_or_absent(evidence: Evidence, f: Field, fallback: str = "_not provided_") -> str:
    if not evidence.has(f):
        return fallback
    v = evidence.values[f]
    if f is Field.STEPS:
        return _steps(v)
    if f in FENCED:
        return _fence(v)
    return _inline(v)


def render_markdown(
    evidence: Evidence,
    *,
    source_url: str | None = None,
    permalink: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    """Render the reproduction block a reporter pastes into the issue."""
    generated_at = generated_at or datetime.now(timezone.utc)
    missing = evidence.missing()
    rerunnable = not missing

    env_bits = []
    for f in (Field.ENVIRONMENT, Field.RUNTIME_VERSION):
        if evidence.has(f):
            env_bits.append(_inline(evidence.values[f]))
    environment = " · ".join(env_bits) if env_bits else "_not provided_"

    parts: list[str] = ["## Reproduction report", ""]

    parts += [
        f"**Symptom:** {_inline(evidence.values.get(Field.SYMPTOM, '')) or '_not provided_'}",
        "",
        f"**Environment:** {environment}",
        "",
        "**Steps:**",
        _value_or_absent(evidence, Field.STEPS),
        "",
        f"**Expected:** {_value_or_absent(evidence, Field.EXPECTED)}",
        "",
        f"**Actual:** {_value_or_absent(evidence, Field.ACTUAL)}",
        "",
    ]

    if evidence.has(Field.ERROR_OUTPUT):
        parts += [
            "<details><summary>Error output</summary>",
            "",
            _fence(evidence.values[Field.ERROR_OUTPUT]),
            "",
            "</details>",
            "",
        ]

    parts += [f"**Frequency:** {_value_or_absent(evidence, Field.FREQUENCY)}", ""]

    if evidence.has(Field.NEGATIVE_CONTROL):
        parts += [
            f"**Does not trigger when:** {_inline(evidence.values[Field.NEGATIVE_CONTROL])}",
            "",
        ]

    if evidence.has(Field.MINIMAL_REPRO):
        parts += [
            "<details><summary>Minimal reproduction</summary>",
            "",
            _fence(evidence.values[Field.MINIMAL_REPRO]),
            "",
            "</details>",
            "",
        ]

    if evidence.has(Field.LIMITS):
        parts += [f"**Not tested:** {_inline(evidence.values[Field.LIMITS])}", ""]

    if missing:
        from .fields import FIELD_META

        labels = ", ".join(FIELD_META[f]["label"] for f in missing)
        parts += [f"> **Evidence gaps remaining:** {labels}.", ""]
    else:
        parts += ["> **Evidence gaps remaining:** none.", ""]

    parts += ["---", f"*{DISCLAIMER}*"]

    footer_bits = []
    if source_url:
        footer_bits.append(f"[Source issue]({source_url})")
    if permalink:
        footer_bits.append(f"[Permalink]({permalink})")
    footer_bits.append(generated_at.strftime("%Y-%m-%d %H:%M UTC"))
    parts += ["", "*" + " · ".join(footer_bits) + "*"]

    return "\n".join(parts)


def render_text(evidence: Evidence) -> str:
    """Plain-text variant, for people who paste into a terminal or an email."""
    md = render_markdown(evidence)
    out = []
    for line in md.splitlines():
        if line.startswith("# "):
            out.append(line[2:].upper())
        elif line.startswith("## "):
            out.append(line[3:].upper())
        else:
            out.append(line.replace("**", "").replace("_not provided_", "not provided"))
    return "\n".join(out)


def stats(evidence: Evidence) -> dict[str, int]:
    """Counts for the verdict badge and analytics."""
    total = 11
    present = total - len(evidence.missing())
    return {"present": present, "total": total, "missing": total - present}
