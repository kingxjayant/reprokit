-- ReproKit schema, migration 0001
-- Target: Supabase (PostgreSQL 15+) — also valid on local SQLite via app/db.py
--
-- Privacy rules baked into this schema:
--   * Only redacted report content is stored. Raw pasted text is never persisted.
--   * No accounts, no emails, no IP addresses, no user identifiers.
--   * Reports expire (REPORT_RETENTION_DAYS, default 90) and are deletable.

-- --------------------------------------------------------------------------
-- reports: one row per generated reproduction report (public permalink /r/<id>)
-- --------------------------------------------------------------------------
create table if not exists reports (
    -- nanoid-style public identifier, 12 chars. Never a sequential integer:
    -- a sequential id would let anyone enumerate every report ever generated.
    id              text primary key,

    -- provenance of the source issue, if one was supplied
    source_url      text,
    source_owner    text,
    source_repo     text,
    source_number   integer,

    -- the generated artefact
    markdown        text        not null,

    -- denormalised verdict, so the permalink page can render without re-parsing
    verdict         text        not null check (verdict in ('rerunnable', 'not_rerunnable')),
    fields_present  smallint    not null check (fields_present between 0 and 11),
    missing_fields  text[]      not null default '{}',

    -- count of secrets removed server-side; shown in the UI, useful evidence
    redactions      integer     not null default 0,

    -- free-text mode: no GitHub URL, reporter pasted the report by hand
    pasted_input    boolean     not null default false,

    created_at      timestamptz not null default now(),
    -- retention: reports are deletable and expire
    expires_at      timestamptz not null
);

create index if not exists reports_created_at_idx on reports (created_at desc);
create index if not exists reports_source_repo_idx on reports (source_owner, source_repo);
create index if not exists reports_expires_at_idx on reports (expires_at);

comment on table reports is
    'Redacted reproduction reports. Contains no raw logs, no credentials, no user identifiers.';

-- --------------------------------------------------------------------------
-- analytics_events: counters kept separately, as the fund's guidance requires.
-- report_started / report_completed / report_rerunnable are distinct rows,
-- so a page visit is never mistaken for a completed task.
-- --------------------------------------------------------------------------
create table if not exists analytics_events (
    id          bigserial   primary key,
    event       text        not null check (event in (
                                'report_started',
                                'report_completed',
                                'report_rerunnable',
                                'report_shared',
                                'issue_fetch_failed',
                                'report_copied'
                            )),
    -- coarse properties only: never a URL, never free text from the reporter
    properties  jsonb       not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

create index if not exists analytics_events_event_idx on analytics_events (event, created_at desc);

comment on table analytics_events is
    'Anonymous counters. properties must never contain issue URLs, repo names, or reporter input.';

-- --------------------------------------------------------------------------
-- convenience view: the three funnel stages side by side
-- --------------------------------------------------------------------------
create or replace view funnel_daily as
select
    date_trunc('day', created_at)::date                as day,
    count(*) filter (where event = 'report_started')   as started,
    count(*) filter (where event = 'report_completed') as completed,
    count(*) filter (where event = 'report_rerunnable') as rerunnable
from analytics_events
group by 1
order by 1 desc;

-- --------------------------------------------------------------------------
-- retention job. On Supabase, schedule with pg_cron (enabled by default):
--   select cron.schedule('reprokit-retention', '0 3 * * *',
--                        $$select delete_expired_reports()$$);
-- --------------------------------------------------------------------------
create or replace function delete_expired_reports() returns integer as $$
declare
    removed integer;
begin
    delete from reports where expires_at < now();
    get diagnostics removed = row_count;
    return removed;
end;
$$ language plpgsql security definer;

-- --------------------------------------------------------------------------
-- Row Level Security: the app talks to Postgres as its owner (service role /
-- direct connection). No anon key is ever shipped to the browser, so RLS is
-- deny-by-default for anything else.
-- --------------------------------------------------------------------------
alter table reports          enable row level security;
alter table analytics_events enable row level security;

-- No policies are created on purpose: only the service role can read/write.
