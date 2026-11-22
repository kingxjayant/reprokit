"""Tests for the Markdown reproduction report."""

from __future__ import annotations

from datetime import datetime, timezone

from app.artifacts import analyse
from app.fields import Evidence, Field
from app.report import DISCLAIMER, render_markdown, render_text, stats

from tests.test_gap_analysis import BAD_BODY, GOOD_BODY

FIXED_TIME = datetime(2026, 12, 1, 9, 30, tzinfo=timezone.utc)


def test_full_report_contains_every_section():
    evidence, _ = analyse("createItem crashes on empty body", GOOD_BODY)
    md = render_markdown(evidence, generated_at=FIXED_TIME)
    for heading in [
        "**Symptom:**",
        "**Environment:**",
        "**Steps:**",
        "**Expected:**",
        "**Actual:**",
        "**Frequency:**",
        "**Does not trigger when:**",
        "**Not tested:**",
        "Error output",
        "Minimal reproduction",
    ]:
        assert heading in md, heading


def test_report_always_ends_with_the_disclaimer():
    for body in (GOOD_BODY, BAD_BODY):
        evidence, _ = analyse("title here", body)
        md = render_markdown(evidence, generated_at=FIXED_TIME)
        assert DISCLAIMER in md
        assert "does not claim the bug was reproduced" in md


def test_gaps_are_listed_when_evidence_is_missing():
    evidence, _ = analyse("app crashes", "it crashed once")
    md = render_markdown(evidence, generated_at=FIXED_TIME)
    assert "Evidence gaps remaining:** none" not in md
    assert "Negative control" in md or "What does *not* trigger it" in md


def test_no_gap_line_when_complete():
    evidence, _ = analyse("createItem crashes on empty body", GOOD_BODY)
    md = render_markdown(evidence, generated_at=FIXED_TIME)
    assert "Evidence gaps remaining:** none" in md


def test_secrets_are_redacted_at_render_time_too():
    evidence = Evidence()
    evidence.set(Field.SYMPTOM, "login fails")
    evidence.set(Field.ERROR_OUTPUT, "token ghp_abcdefghijklmnopqrstuvwxyz0123 rejected")
    md = render_markdown(evidence, generated_at=FIXED_TIME)
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123" not in md
    assert "[REDACTED:github_token]" in md


def test_permalink_and_source_are_included():
    evidence, _ = analyse("t", "x")
    md = render_markdown(
        evidence,
        source_url="https://github.com/o/r/issues/1",
        permalink="https://reprokit.tech/r/abc123",
        generated_at=FIXED_TIME,
    )
    assert "https://github.com/o/r/issues/1" in md
    assert "https://reprokit.tech/r/abc123" in md
    assert "2026-12-01 09:30 UTC" in md


def test_steps_are_numbered_when_the_reporter_did_not_number_them():
    evidence = Evidence()
    evidence.set(Field.STEPS, "open the app\nclick save\nsee the crash")
    md = render_markdown(evidence, generated_at=FIXED_TIME)
    assert "1. open the app" in md
    assert "3. see the crash" in md


def test_already_numbered_steps_are_left_alone():
    evidence = Evidence()
    evidence.set(Field.STEPS, "1. open the app\n2. click save")
    md = render_markdown(evidence, generated_at=FIXED_TIME)
    assert "1. 1. open" not in md
    assert "1. open the app" in md


def test_nested_fences_do_not_break_markdown():
    evidence = Evidence()
    evidence.set(Field.SYMPTOM, "x y z")
    evidence.set(Field.ERROR_OUTPUT, "```js\nboom()\n```")
    md = render_markdown(evidence, generated_at=FIXED_TIME)
    assert "````" in md  # outer fence lengthened


def test_absent_fields_render_as_not_provided_not_blank():
    evidence = Evidence()
    evidence.set(Field.SYMPTOM, "save button does nothing on submit")
    md = render_markdown(evidence, generated_at=FIXED_TIME)
    assert "_not provided_" in md


def test_stats_counts_present_fields():
    evidence, _ = analyse("createItem crashes on empty body", GOOD_BODY)
    s = stats(evidence)
    assert s["total"] == 11
    assert s["present"] == 11
    assert s["missing"] == 0


def test_render_text_has_no_markdown_syntax():
    evidence, _ = analyse("createItem crashes on empty body", GOOD_BODY)
    txt = render_text(evidence)
    assert "**" not in txt
    assert "REPRODUCTION REPORT" in txt
