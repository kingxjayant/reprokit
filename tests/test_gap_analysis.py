"""Tests for the 11-field parser and gap analysis.

The contract these tests protect: a field is only reported present when a
maintainer could actually act on it. False positives break the product's
only promise.
"""

from __future__ import annotations

import pytest

from app.artifacts import (
    analyse,
    detect_error_output,
    detect_environment,
    detect_frequency,
    detect_minimal_repro,
    detect_negative_control,
    detect_runtime_version,
    detect_steps,
    gaps,
    verdict,
)
from app.fields import Evidence, Field

GOOD_BODY = """
### Environment
Ubuntu 24.04, Node 22.11.0, package 3.4.1

### Steps to reproduce
1. Run `npm install`
2. Run `node server.js`
3. POST to /api/items with an empty body

### Expected
200 with the created item as JSON

### Actual
returns 500 with body {"error":"bad gateway"}

### Error output
```
TypeError: Cannot read properties of undefined (reading 'id')
    at createItem (/home/dev/app/src/items.js:42:11)
```

### Frequency
3 failures in 3 clean runs

### Does not trigger when
works fine on macOS 14 with the same version

### Minimal reproduction
```js
const { createItem } = require('./src/items');
createItem({});
```

### Not tested
did not test with Node 20
"""

BAD_BODY = "it broke pls help"


# --------------------------------------------------------------------------- #
# individual detectors
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "Ubuntu 24.04 on a laptop",
        "Windows 11, nothing else",
        "happens on macOS 14.2",
        "running in WSL2",
        "Android 14 device",
    ],
)
def test_environment_detected(text):
    assert detect_environment(text)


def test_environment_absent_when_not_mentioned():
    assert detect_environment("the button does nothing") is None


@pytest.mark.parametrize(
    "text",
    [
        "node 22.11.0 is installed",
        "python 3.12.1",
        "go 1.23.0",
        "django==4.2.1",
        "react 18.2.0",
    ],
)
def test_runtime_version_detected(text):
    assert detect_runtime_version(text)


def test_steps_need_more_than_prose():
    prose = "I clicked the button and then it broke in the settings page somewhere."
    assert detect_steps(prose) is None


def test_steps_detected_from_numbered_list():
    text = "Steps to reproduce\n1. Open the app\n2. Click save\n3. Observe the crash"
    assert detect_steps(text) is not None


def test_error_output_requires_a_real_signal():
    assert detect_error_output("it says error somewhere") is None
    assert detect_error_output("```\nTypeError: x is undefined\n  at f (a.js:1:1)\n```")


def test_frequency_detected():
    assert detect_frequency("3 failures in 3 clean runs")
    assert detect_frequency("happens every time")
    assert detect_frequency("intermittent, maybe 2 out of 10")


def test_negative_control_detected():
    assert detect_negative_control("works fine on macOS with the same version")
    assert detect_negative_control("only happens on Windows")


def test_negative_control_absent_by_default():
    assert detect_negative_control("it crashes when I click save") is None


def test_minimal_repro_does_not_claim_the_error_dump():
    # the only fence is the error output; minimal repro must stay absent
    body = "```\nTraceback (most recent call last):\n  File x.py, line 3\nValueError\n```"
    assert detect_minimal_repro(body) is None


# --------------------------------------------------------------------------- #
# whole-report analysis
# --------------------------------------------------------------------------- #


def test_good_report_is_rerunnable():
    evidence, found = analyse("createItem crashes on empty body", GOOD_BODY)
    ok, missing = verdict(evidence)
    assert ok is True, f"unexpected gaps: {missing}"
    assert Field.NEGATIVE_CONTROL in found
    assert len(found) == 11


def test_bad_report_is_not_rerunnable_and_scores_zero_silently():
    evidence, found = analyse("bug", BAD_BODY)
    ok, missing = verdict(evidence)
    assert ok is False
    assert Field.SYMPTOM in missing
    assert Field.NEGATIVE_CONTROL in missing
    assert len(missing) >= 9


def test_gap_order_follows_interview_priority():
    evidence, _ = analyse("app crashes", "The app crashes when saving.")
    order = gaps(evidence)
    assert order.index(Field.ENVIRONMENT) < order.index(Field.FREQUENCY)


def test_skipped_field_stays_absent():
    evidence, _ = analyse("createItem crashes on empty body", GOOD_BODY)
    assert verdict(evidence)[0] is True
    evidence.skip(Field.NEGATIVE_CONTROL)
    ok, missing = verdict(evidence)
    assert ok is False
    assert Field.NEGATIVE_CONTROL in missing


def test_skipping_then_answering_restores_the_field():
    evidence = Evidence()
    evidence.skip(Field.FREQUENCY)
    assert Field.FREQUENCY in evidence.missing()
    evidence.set(Field.FREQUENCY, "always")
    assert Field.FREQUENCY not in evidence.missing()


def test_vague_title_is_not_accepted_as_a_symptom():
    evidence, _ = analyse("doesn't work", "nothing works")
    assert Field.SYMPTOM in evidence.missing()


def test_whitespace_is_not_evidence():
    evidence = Evidence()
    evidence.set(Field.FREQUENCY, "   \n  ")
    assert Field.FREQUENCY in evidence.missing()
