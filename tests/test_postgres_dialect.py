"""Regression tests for the Postgres placeholder dialect.

A real bug shipped and was caught against a live Supabase instance: the inherited
`Store` methods were written with SQLite's ``?`` placeholders, so on Postgres
every read failed with::

    psycopg.ProgrammingError: the query has 0 placeholders but 1 parameters were passed

The unit tests all passed, because they only ever exercised SQLite. These tests
drive the *same* inherited methods through a Postgres-shaped store and fail if a
bare ``?`` reaches the driver again.
"""

from __future__ import annotations

import pytest

from app.db import PostgresStore, Store


class RecordingPostgresStore(Store):
    """Mimics psycopg strictly enough to catch a wrong placeholder.

    psycopg counts ``%s`` placeholders and rejects a query whose placeholder
    count does not match the parameter count. SQLite's ``?`` is not recognised,
    which is exactly how the bug surfaced.
    """

    placeholder = "%s"
    json_cast = "::jsonb"

    def __init__(self):
        super().__init__(retention_days=90)
        self.statements: list[str] = []
        self._reports: dict[str, tuple] = {}
        self._events: list[tuple[str, str]] = []

    def _check(self, sql: str, params: tuple) -> None:
        self.statements.append(sql)
        assert "?" not in sql, f"SQLite placeholder leaked into Postgres SQL: {sql!r}"
        expected = sql.count("%s")
        assert expected == len(params), (
            f"placeholder count mismatch: {expected} placeholders, "
            f"{len(params)} params in {sql!r}"
        )

    def _execute(self, sql: str, params: tuple = ()) -> None:
        self._check(sql, params)
        if "insert into analytics_events" in sql:
            self._events.append((params[0], params[1]))
        elif "delete from reports" in sql:
            self._reports.pop(params[0], None)
        elif "delete from analytics_events" in sql:
            self._events.clear()

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        self._check(sql, params)
        if "from reports where id" in sql:
            row = self._reports.get(params[0])
            return [row] if row else []
        if "group by event" in sql:
            seen: dict[str, int] = {}
            for e, _ in self._events:
                seen[e] = seen.get(e, 0) + 1
            return list(seen.items())
        if "count(*) from reports" in sql:
            return [(len(self._reports),)]
        return []

    def _seed(self, rid: str) -> None:
        self._reports[rid] = (
            rid, "md", "rerunnable", 11, ("{}"), 0, None, False, "2026-12-01T00:00:00+00:00",
        )


def test_postgres_store_declares_its_dialect():
    assert PostgresStore.placeholder == "%s"
    assert PostgresStore.json_cast == "::jsonb"


def test_sqlite_store_declares_its_dialect():
    assert Store.placeholder == "?"


def test_track_uses_percent_s_and_casts_json():
    s = RecordingPostgresStore()
    s.track("report_started", {"mode": "url"})
    sql = s.statements[-1]
    assert "%s" in sql
    assert "::jsonb" in sql


def test_get_report_rewrites_to_percent_s():
    s = RecordingPostgresStore()
    s._seed("abc123")
    got = s.get_report("abc123")
    assert got is not None
    assert got.id == "abc123"
    assert got.verdict == "rerunnable"


def test_funnel_rewrites_to_percent_s():
    s = RecordingPostgresStore()
    s.track("report_started")
    s.track("report_completed")
    f = s.funnel()
    assert (f.started, f.completed) == (1, 1)


def test_purge_and_count_rewrite_to_percent_s():
    s = RecordingPostgresStore()
    assert s.count_reports() == 0
    s.purge_expired()


def test_save_report_uses_percent_s_on_postgres():
    """PostgresStore overrides save_report; make sure it does not use '?' either."""
    captured: dict = {}

    class Probe(PostgresStore):
        def __init__(self):
            Store.__init__(self, retention_days=90)
            self.placeholder = "%s"
            self.json_cast = "::jsonb"

        def _execute(self, sql, params=()):
            captured["sql"] = sql
            captured["params"] = params
            assert "?" not in sql
            assert sql.count("%s") == len(params)

    p = Probe()
    p.save_report(
        markdown="x",
        verdict="rerunnable",
        fields_present=11,
        missing_fields=[],
        redactions=0,
    )
    assert captured["sql"], "save_report did not execute anything"


@pytest.mark.parametrize(
    "method", ["track", "funnel", "purge_expired", "count_reports"]
)
def test_no_inherited_method_emits_a_sqlite_placeholder(method):
    s = RecordingPostgresStore()
    s._seed("x1")
    if method == "track":
        s.track("report_copied")
    elif method == "funnel":
        s.funnel()
    elif method == "purge_expired":
        s.purge_expired()
    else:
        s.count_reports()
    for sql in s.statements:
        assert "?" not in sql, sql
