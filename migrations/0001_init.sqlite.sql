-- ReproKit schema — SQLite variant.
-- Same tables and columns as migrations/0001_init.sql, with Postgres-only
-- features (text[], bigserial, timestamptz, jsonb, plpgsql, RLS) mapped to
-- SQLite equivalents. Production always uses the Postgres migration.

create table if not exists reports (
    id              text primary key,
    source_url      text,
    source_owner    text,
    source_repo     text,
    source_number   integer,
    markdown        text        not null,
    verdict         text        not null check (verdict in ('rerunnable', 'not_rerunnable')),
    fields_present  integer     not null check (fields_present between 0 and 11),
    missing_fields  text        not null default '[]',   -- JSON array
    redactions      integer     not null default 0,
    pasted_input    integer     not null default 0,
    created_at      text        not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expires_at      text        not null
);

create index if not exists reports_created_at_idx on reports (created_at desc);
create index if not exists reports_source_repo_idx on reports (source_owner, source_repo);
create index if not exists reports_expires_at_idx on reports (expires_at);

create table if not exists analytics_events (
    id          integer primary key autoincrement,
    event       text        not null check (event in (
                                'report_started',
                                'report_completed',
                                'report_rerunnable',
                                'report_shared',
                                'issue_fetch_failed',
                                'report_copied'
                            )),
    properties  text        not null default '{}',       -- JSON object
    created_at  text        not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

create index if not exists analytics_events_event_idx on analytics_events (event, created_at desc);
