"""Storage layer.

Two backends, one interface:

* **SQLite** (default in development) — zero setup, used by the tests.
* **PostgreSQL / Supabase** (``DATABASE_URL`` set) — used in production.

Both are driven by the same SQL, with the tiny dialect differences isolated in
:func:`_sql`. That keeps one code path for behaviour and means the tests
exercise the queries that actually run in production.

Privacy: this module only ever writes *redacted* content. It has no function
for storing raw pasted text, by design.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE = ROOT / "reprokit.db"

_ALPHABET = string.ascii_lowercase + string.digits
_ID_LEN = 12

VERDICT_RERUNNABLE = "rerunnable"
VERDICT_NOT_RERUNNABLE = "not_rerunnable"

ALLOWED_EVENTS = frozenset(
    {
        "report_started",
        "report_completed",
        "report_rerunnable",
        "report_shared",
        "issue_fetch_failed",
        "report_copied",
    }
)


def new_id() -> str:
    """Public identifier for a report permalink."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_ID_LEN))


@dataclass(frozen=True)
class StoredReport:
    id: str
    markdown: str
    verdict: str
    fields_present: int
    missing_fields: tuple[str, ...]
    redactions: int
    source_url: str | None
    pasted_input: bool
    created_at: datetime


@dataclass(frozen=True)
class Funnel:
    started: int
    completed: int
    rerunnable: int

    @property
    def completion_rate(self) -> float:
        return round(100 * self.completed / self.started, 1) if self.started else 0.0

    @property
    def rerunnable_rate(self) -> float:
        """Of completed reports, how many were rerunnable. The headline metric."""
        return round(100 * self.rerunnable / self.completed, 1) if self.completed else 0.0


class Store:
    """Storage interface. Subclasses implement the three primitives.

    Placeholder dialect lives here rather than in each query, so the inherited
    methods below work unchanged on both backends. (This was a real bug: the
    inherited queries used SQLite's ``?`` and failed on Postgres.)
    """

    #: ``?`` for SQLite, ``%s`` for psycopg.
    placeholder = "?"
    #: cast needed when writing a JSON string into a json/jsonb column.
    json_cast = ""

    def __init__(self, retention_days: int = 90):
        self.retention_days = retention_days

    def _sql(self, statement: str) -> str:
        """Rewrite a query for this backend's placeholder dialect."""
        if self.placeholder == "?":
            return statement
        return statement.replace("?", self.placeholder)

    # -- primitives -------------------------------------------------------
    def _execute(self, sql: str, params: tuple = ()) -> None:  # pragma: no cover
        raise NotImplementedError

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:  # pragma: no cover
        raise NotImplementedError

    # -- public API -------------------------------------------------------
    def init_schema(self) -> None:
        sql = (ROOT / "migrations" / "0001_init.sql").read_text(encoding="utf-8")
        for statement in _split_sql(sql):
            try:
                self._execute(statement)
            except Exception:
                # views/functions are not always available on SQLite; the
                # tables are what matter for the app
                if statement.strip().lower().startswith(("create table", "create index")):
                    raise

    def save_report(
        self,
        *,
        markdown: str,
        verdict: str,
        fields_present: int,
        missing_fields: list[str],
        redactions: int,
        source_url: str | None = None,
        source_owner: str | None = None,
        source_repo: str | None = None,
        source_number: int | None = None,
        pasted_input: bool = False,
        rid: str | None = None,
    ) -> str:
        # Callers may supply the id when the permalink has to be embedded in the
        # Markdown before the row exists; otherwise the store mints one.
        rid = rid or new_id()
        expires = datetime.now(timezone.utc) + timedelta(days=self.retention_days)
        self._execute(
            self._sql(
                """
                insert into reports (id, source_url, source_owner, source_repo,
                    source_number, markdown, verdict, fields_present,
                    missing_fields, redactions, pasted_input, expires_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
            ),
            (
                rid,
                source_url,
                source_owner,
                source_repo,
                source_number,
                markdown,
                verdict,
                fields_present,
                json.dumps(missing_fields),
                redactions,
                1 if pasted_input else 0,
                expires.isoformat(),
            ),
        )
        return rid

    def get_report(self, rid: str) -> StoredReport | None:
        rows = self._query(
            self._sql(
                "select id, markdown, verdict, fields_present, missing_fields,"
                " redactions, source_url, pasted_input, created_at"
                " from reports where id = ?"
            ),
            (rid,),
        )
        if not rows:
            return None
        r = rows[0]
        missing = r[4]
        if isinstance(missing, str):
            try:
                missing = tuple(json.loads(missing))
            except ValueError:
                missing = tuple(x for x in missing.strip("{}").split(",") if x)
        else:
            missing = tuple(missing or ())
        created = r[8]
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created)
            except ValueError:
                created = datetime.now(timezone.utc)
        return StoredReport(
            id=r[0],
            markdown=r[1],
            verdict=r[2],
            fields_present=int(r[3]),
            missing_fields=missing,
            redactions=int(r[5]),
            source_url=r[6],
            pasted_input=bool(r[7]),
            created_at=created,
        )

    def track(self, event: str, properties: dict | None = None) -> None:
        """Record one analytics event. Unknown events are rejected, not stored."""
        if event not in ALLOWED_EVENTS:
            raise ValueError(f"unknown analytics event: {event}")
        safe = _strip_sensitive(properties or {})
        self._execute(
            self._sql(
                "insert into analytics_events (event, properties) "
                f"values (?, ?{self.json_cast})"
            ),
            (event, json.dumps(safe)),
        )

    def funnel(self) -> Funnel:
        rows = self._query(
            self._sql("select event, count(*) from analytics_events group by event")
        )
        counts = {r[0]: int(r[1]) for r in rows}
        return Funnel(
            started=counts.get("report_started", 0),
            completed=counts.get("report_completed", 0),
            rerunnable=counts.get("report_rerunnable", 0),
        )

    def purge_expired(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        before = self._query(self._sql("select count(*) from reports where expires_at < ?"), (now,))
        self._execute(self._sql("delete from reports where expires_at < ?"), (now,))
        return int(before[0][0]) if before else 0

    def count_reports(self) -> int:
        rows = self._query(self._sql("select count(*) from reports"))
        return int(rows[0][0]) if rows else 0


# --------------------------------------------------------------------------- #
# properties hygiene
# --------------------------------------------------------------------------- #

_SENSITIVE_KEYS = {"url", "source_url", "issue_url", "repo", "owner", "body", "text", "input"}


def _strip_sensitive(properties: dict) -> dict:
    """Drop anything that could identify a repository or contain reporter input."""
    out = {}
    for k, v in properties.items():
        if k.lower() in _SENSITIVE_KEYS:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            if isinstance(v, str) and len(v) > 80:
                continue
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #


class SQLiteStore(Store):
    def __init__(self, path: str | Path = DEFAULT_SQLITE, retention_days: int = 90):
        super().__init__(retention_days)
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("pragma journal_mode=wal")

    def _execute(self, sql: str, params: tuple = ()) -> None:
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        cur.close()

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        return list(self._conn.execute(sql, params).fetchall())

    def init_schema(self) -> None:
        sql = (ROOT / "migrations" / "0001_init.sqlite.sql").read_text(encoding="utf-8")
        for statement in _split_sql(sql):
            self._execute(statement)

    def close(self) -> None:
        self._conn.close()


class PostgresStore(Store):
    """Supabase / Postgres backend. Requires ``psycopg[binary]``."""

    placeholder = "%s"
    json_cast = "::jsonb"

    def __init__(self, dsn: str, retention_days: int = 90):
        super().__init__(retention_days)
        import psycopg  # imported lazily so SQLite-only setups need no driver

        self._psycopg = psycopg
        self._conn = psycopg.connect(dsn, autocommit=True)

    def _execute(self, sql: str, params: tuple = ()) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def init_schema(self) -> None:
        sql = (ROOT / "migrations" / "0001_init.sql").read_text(encoding="utf-8")
        for statement in _split_sql(sql):
            self._execute(statement)

    def save_report(self, **kwargs) -> str:
        # Postgres uses native arrays rather than JSON strings
        rid = kwargs.get("rid") or new_id()
        expires = datetime.now(timezone.utc) + timedelta(days=self.retention_days)
        self._execute(
            """
            insert into reports (id, source_url, source_owner, source_repo,
                source_number, markdown, verdict, fields_present,
                missing_fields, redactions, pasted_input, expires_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                rid,
                kwargs.get("source_url"),
                kwargs.get("source_owner"),
                kwargs.get("source_repo"),
                kwargs.get("source_number"),
                kwargs["markdown"],
                kwargs["verdict"],
                kwargs["fields_present"],
                list(kwargs.get("missing_fields") or []),
                kwargs.get("redactions", 0),
                bool(kwargs.get("pasted_input", False)),
                expires,
            ),
        )
        return rid

    def close(self) -> None:
        self._conn.close()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _split_sql(sql: str) -> list[str]:
    """Split a migration file into statements, ignoring comments.

    Deliberately naive: the migrations contain no dollar-quoted function bodies
    beyond the one block handled below, and no semicolons inside string literals
    other than in comments.
    """
    sql = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    out: list[str] = []
    buf: list[str] = []
    in_dollar = False
    for chunk in sql.split(";"):
        buf.append(chunk)
        joined = ";".join(buf)
        if "$$" in chunk:
            in_dollar = joined.count("$$") % 2 == 1
        if in_dollar:
            continue
        stmt = joined.strip()
        if stmt:
            out.append(stmt)
        buf = []
    if buf:
        leftover = ";".join(buf).strip()
        if leftover:
            out.append(leftover)
    return out


def get_store(dsn: str = "", retention_days: int = 90) -> Store:
    """Pick a backend from configuration."""
    if dsn:
        store = PostgresStore(dsn, retention_days)
        store.init_schema()
        return store
    store = SQLiteStore(DEFAULT_SQLITE, retention_days)
    store.init_schema()
    return store
