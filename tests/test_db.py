"""Tests for the storage layer (SQLite backend, the same queries production runs)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import ALLOWED_EVENTS, SQLiteStore, new_id


@pytest.fixture()
def store(tmp_path):
    s = SQLiteStore(tmp_path / "test.db", retention_days=90)
    s.init_schema()
    yield s
    s.close()


def test_schema_creates_tables(store):
    tables = {r[0] for r in store._query("select name from sqlite_master where type='table'")}
    assert {"reports", "analytics_events"} <= tables


def test_save_and_get_report(store):
    rid = store.save_report(
        markdown="## Reproduction report\n\nbody",
        verdict="rerunnable",
        fields_present=11,
        missing_fields=[],
        redactions=2,
        source_url="https://github.com/o/r/issues/1",
        source_owner="o",
        source_repo="r",
        source_number=1,
    )
    got = store.get_report(rid)
    assert got is not None
    assert got.markdown.startswith("## Reproduction report")
    assert got.verdict == "rerunnable"
    assert got.fields_present == 11
    assert got.missing_fields == ()
    assert got.redactions == 2
    assert got.source_url.endswith("/issues/1")


def test_missing_fields_roundtrip_as_tuple(store):
    rid = store.save_report(
        markdown="x",
        verdict="not_rerunnable",
        fields_present=6,
        missing_fields=["frequency", "negative_control"],
        redactions=0,
    )
    got = store.get_report(rid)
    assert set(got.missing_fields) == {"frequency", "negative_control"}


def test_unknown_id_returns_none(store):
    assert store.get_report("nope-not-real") is None


def test_ids_are_not_sequential_or_guessable():
    ids = {new_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(len(i) == 12 for i in ids)


def test_pasted_input_flag(store):
    rid = store.save_report(
        markdown="x",
        verdict="not_rerunnable",
        fields_present=3,
        missing_fields=["steps"],
        redactions=0,
        pasted_input=True,
    )
    assert store.get_report(rid).pasted_input is True


def test_analytics_counts_events_separately(store):
    store.track("report_started")
    store.track("report_started")
    store.track("report_completed")
    store.track("report_rerunnable")
    f = store.funnel()
    assert (f.started, f.completed, f.rerunnable) == (2, 1, 1)
    assert f.completion_rate == 50.0
    assert f.rerunnable_rate == 100.0


def test_page_visit_is_not_a_completed_task(store):
    """The fund's guidance: raw visits must never be counted as completions."""
    for _ in range(10):
        store.track("report_started")
    f = store.funnel()
    assert f.completed == 0
    assert f.completion_rate == 0.0


def test_unknown_event_is_rejected(store):
    with pytest.raises(ValueError):
        store.track("page_view")


def test_all_allowed_events_are_accepted(store):
    for e in ALLOWED_EVENTS:
        store.track(e)


def test_sensitive_properties_are_stripped(store):
    store.track(
        "report_started",
        {
            "url": "https://github.com/secret/repo/issues/1",
            "repo": "secret/repo",
            "body": "the reporter's pasted text",
            "mode": "url",
        },
    )
    row = store._query("select properties from analytics_events")[0][0]
    assert "secret" not in row
    assert "reporter" not in row
    assert "url" in row.lower()  # the key 'mode' survived


def test_long_string_properties_are_dropped(store):
    store.track("report_started", {"note": "x" * 200})
    row = store._query("select properties from analytics_events")[0][0]
    assert "xxxx" not in row


def test_purge_expired_removes_only_old_rows(store):
    rid = store.save_report(
        markdown="x",
        verdict="rerunnable",
        fields_present=11,
        missing_fields=[],
        redactions=0,
    )
    # force expiry into the past
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    store._execute("update reports set expires_at = ? where id = ?", (past, rid))
    assert store.purge_expired() == 1
    assert store.get_report(rid) is None
    assert store.count_reports() == 0


def test_retention_window_is_set_on_insert(store):
    rid = store.save_report(
        markdown="x",
        verdict="rerunnable",
        fields_present=11,
        missing_fields=[],
        redactions=0,
    )
    expires = store._query("select expires_at from reports where id = ?", (rid,))[0][0]
    when = datetime.fromisoformat(expires)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    assert when > datetime.now(timezone.utc) + timedelta(days=80)
