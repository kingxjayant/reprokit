"""The 11 required fields, in priority order.

Every field a report needs before a maintainer can attempt a reproduction.
Order matters: it drives the interview sequence and the gap-analysis output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Field(Enum):
    SYMPTOM = "symptom"
    ENVIRONMENT = "environment"
    RUNTIME_VERSION = "runtime_version"
    STEPS = "steps"
    EXPECTED = "expected"
    ACTUAL = "actual"
    ERROR_OUTPUT = "error_output"
    FREQUENCY = "frequency"
    NEGATIVE_CONTROL = "negative_control"
    MINIMAL_REPRO = "minimal_repro"
    LIMITS = "limits"


#: Human label + why it matters, used by the UI and the generated Markdown.
FIELD_META: dict[Field, dict[str, str]] = {
    Field.SYMPTOM: {
        "label": "One-sentence symptom",
        "why": "The thing that is actually broken, in one sentence.",
    },
    Field.ENVIRONMENT: {
        "label": "Environment (OS + version)",
        "why": "Half of all 'cannot reproduce' reports are an OS difference.",
    },
    Field.RUNTIME_VERSION: {
        "label": "Runtime / dependency version",
        "why": "Behaviour changes between versions; this is the most-requested detail.",
    },
    Field.STEPS: {
        "label": "Exact command or click path",
        "why": "'It breaks' is not a reproduction. We need the literal steps.",
    },
    Field.EXPECTED: {
        "label": "Expected result (literal)",
        "why": "'Should work' cannot be measured. We need a concrete value.",
    },
    Field.ACTUAL: {
        "label": "Actual result (literal)",
        "why": "What happened instead, in the reporter's own words.",
    },
    Field.ERROR_OUTPUT: {
        "label": "Error text / stack trace",
        "why": "The real text, not a summary of it.",
    },
    Field.FREQUENCY: {
        "label": "Frequency",
        "why": "Always vs 1-in-3 changes the entire diagnosis.",
    },
    Field.NEGATIVE_CONTROL: {
        "label": "What does *not* trigger it",
        "why": "The one answer that halves the search space. Almost nobody asks for it.",
    },
    Field.MINIMAL_REPRO: {
        "label": "Minimal code sample",
        "why": "The smallest thing that still fails.",
    },
    Field.LIMITS: {
        "label": "Limits of observation",
        "why": "What the reporter did *not* test that a maintainer might assume they did.",
    },
}


@dataclass(frozen=True)
class Question:
    """One interview step. Asks for exactly one missing field."""

    field: Field
    prompt: str
    placeholder: str
    input_mode: str = "text"  # text | multiline | log | steps | version


#: Q1..Q8 from the build spec, in priority order.
QUESTIONS: tuple[Question, ...] = (
    Question(
        field=Field.ENVIRONMENT,
        prompt=(
            "Which operating system and version are you on, and what version of "
            "the runtime/package? If you're not sure, run the install command for "
            "your platform and paste what it prints."
        ),
        placeholder="e.g. Ubuntu 24.04, Node 22.11.0, package 3.4.1",
        input_mode="version",
    ),
    Question(
        field=Field.RUNTIME_VERSION,
        prompt=(
            "What is the exact version of the package or runtime where the bug "
            "appears? Include the patch number if you can."
        ),
        placeholder="e.g. 3.4.1 (not 'latest')",
        input_mode="version",
    ),
    Question(
        field=Field.STEPS,
        prompt=(
            "Walk me through the exact clicks or commands, one per line, starting "
            "from a fresh launch. Be boring — I need the literal keystrokes, not "
            "the summary."
        ),
        placeholder="1. Run `npm i`\n2. Run `node server.js`\n3. POST /api/items with {}",
        input_mode="steps",
    ),
    Question(
        field=Field.ERROR_OUTPUT,
        prompt=(
            "Paste the exact error text or stack trace, as it appeared. Don't "
            "clean it up. Anything that looks like a token or password will be "
            "redacted before it is shown or stored."
        ),
        placeholder="Paste the raw error output here…",
        input_mode="log",
    ),
    Question(
        field=Field.ACTUAL,
        prompt=(
            "What actually happened? Use a concrete value — the wrong output, the "
            "exit code, the blank screen — not 'it failed'."
        ),
        placeholder="e.g. returns 500 with body `{\"error\":\"bad gateway\"}`",
        input_mode="text",
    ),
    Question(
        field=Field.EXPECTED,
        prompt=(
            "What did you expect to happen, in one sentence with a concrete value? "
            "e.g. 'the file is written to ./out and exit code 0', not 'it should work'."
        ),
        placeholder="e.g. 200 with the created item as JSON",
        input_mode="text",
    ),
    Question(
        field=Field.NEGATIVE_CONTROL,
        prompt=(
            "What does *not* trigger it? Same command on a different OS, a smaller "
            "input, a fresh config — anything where it works fine."
        ),
        placeholder="e.g. works on macOS 14 with the same version; fails only on Windows",
        input_mode="text",
    ),
    Question(
        field=Field.FREQUENCY,
        prompt=(
            "How often does it happen — every time, or a fraction of runs? If a "
            "fraction, roughly how many out of how many?"
        ),
        placeholder="e.g. 3 failures in 3 clean runs",
        input_mode="text",
    ),
    Question(
        field=Field.MINIMAL_REPRO,
        prompt=(
            "Trim your example down to the smallest thing that still fails. If you "
            "can't, say so and paste what you have."
        ),
        placeholder="Paste the smallest failing snippet…",
        input_mode="log",
    ),
    Question(
        field=Field.LIMITS,
        prompt=(
            "Anything you did *not* test that a maintainer might assume you tested?"
        ),
        placeholder="e.g. did not try Node 20, did not test with a fresh DB",
        input_mode="text",
    ),
)

#: Quick lookup: which question covers which field.
QUESTION_BY_FIELD: dict[Field, Question] = {q.field: q for q in QUESTIONS}

#: Fields the interview can collect. SYMPTOM is always taken from the report itself.
INTERVIEWABLE: tuple[Field, ...] = tuple(q.field for q in QUESTIONS)


@dataclass
class Evidence:
    """Collected evidence for one report.

    ``values`` holds only fields the reporter actually supplied. A field is
    *absent* rather than empty when the reporter pressed "Skip".
    """

    values: dict[Field, str] = field(default_factory=dict)
    skipped: set[Field] = field(default_factory=set)

    def has(self, f: Field) -> bool:
        v = self.values.get(f)
        return bool(v and v.strip())

    def missing(self) -> list[Field]:
        """Required fields still absent, in priority order."""
        order = [Field.SYMPTOM, *INTERVIEWABLE]
        out = []
        for f in order:
            if f in self.skipped or not self.has(f):
                out.append(f)
        return out

    def set(self, f: Field, value: str) -> None:
        value = (value or "").strip()
        if value:
            self.values[f] = value
            self.skipped.discard(f)

    def skip(self, f: Field) -> None:
        self.values.pop(f, None)
        self.skipped.add(f)


def required_fields() -> list[Field]:
    """Every field a rerunnable report needs, in priority order."""
    return [Field.SYMPTOM, *INTERVIEWABLE]
