# Deploying ReproKit

Target: **`reprokit.tech` serves the app itself.** No redirect, no holding page —
clause 2.6 of the fund's rules disqualifies a redirect, and an award requires the
primary site to stay on `.tech` for 24 months.

Stack: Vercel (app) + Supabase (Postgres) + `.tech` domain from get.tech.

---

## 0. What is already done

The application, tests, docs and migrations are complete in this repository. You
are deploying an existing build, not starting one:

```
104 tests passing · 22 commits · app/ templates/ migrations/ tests/ benchmark/
```

Nothing below requires changing application code.

---

## 1. Claim the domain first (free, ~5 minutes)

1. `education.github.com/pack` → sign in as `kingxjayant` → find **".tech Domains"** → **Get offer**.
   (Fallback redeem link: `education.github.com/pack/redeem/tech-student`.)
2. You land on **get.tech** with the student discount applied.
3. Search **`reprokit.tech`** → add to cart → checkout → **verify with GitHub**.
4. Price becomes **$0.00**. No card required for the sponsored year.

⚠️ Three traps, all confirmed by other students:
- The `.tech` offer is **separate** from the free Namecheap `.me` domain. Using one does not consume the other.
- New domains only — you cannot rename later, so pick carefully.
- If the Education page says *"Your explored offers failed to load"*, refresh, or use the redeem link above.

**Budget for one renewal** (~₹3,000–4,000 in year two). The fund does not reimburse
domain fees, and clause 9.3 means moving off `.tech` early can require repaying up
to 50% of a grant.

---

## 2. Supabase (database)

1. Create a project. **Choose the region closest to your users** — for India,
   `ap-south-1` (Mumbai) or `ap-southeast-1` (Singapore).
2. Save the database password somewhere safe.
3. **SQL Editor → New query** → paste the entire contents of
   [`migrations/0001_init.sql`](migrations/0001_init.sql) → **Run**.
   That creates `reports`, `analytics_events`, the `funnel_daily` view, the
   `delete_expired_reports()` function, and enables RLS in deny-by-default mode.
4. Optional but recommended — schedule retention:
   ```sql
   select cron.schedule('reprokit-retention', '0 3 * * *',
                        $$select delete_expired_reports()$$);
   ```
5. **Project Settings → Database → Connection string → URI**, and pick the
   **Connection pooling** string (port **6543**), not the direct one (5432).
   Serverless functions open many short-lived connections; the pooler is what
   stops you exhausting Postgres.

Your `DATABASE_URL` will look like:

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
```

**RLS note:** the app connects as the owner role and no Supabase key is shipped to
the browser, so there are no policies to write. If you ever add a browser-side
client, you must add policies first — the tables are deny-by-default by design.

---

## 3. Vercel (app)

1. **Import** the GitHub repository. Vercel reads `vercel.json`.
2. Framework preset: **Other / None**. Build command: **leave empty**. Output directory: **leave empty**.
3. Vercel detects `api/index.py`, which exposes the existing FastAPI app as a
   serverless function. All routes are rewritten to it.
4. Add the environment variables in §4 **before** the first deploy.
5. Deploy. Then **Settings → Domains → Add** `reprokit.tech` and `www.reprokit.tech`.
6. Accept the A/CNAME records Vercel shows you, and set them at get.tech's DNS panel.
   Because the domain is registered through get.tech, you can also just point the
   nameservers at Vercel and let it manage DNS.

### The caveat you should know about

This app keeps interview state in a **cookie**, so there is no shared session
storage — which is exactly why it survives a serverless platform. But note two
serverless realities:

- `reports/` permalinks require `DATABASE_URL` to be set. Without it the app falls
  back to SQLite, which is **ephemeral on Vercel** and will lose every report on
  cold start. Treat `DATABASE_URL` as mandatory in production, not optional.
- Cold starts add ~1s to the first request after idle. Acceptable for this app.

If you would rather avoid both: Render or Fly.io run the same repo on a
persistent container (`Procfile` is already there) with no cold starts. The
tradeoff is that free tiers sleep. Either is fine; Vercel is faster to set up.

---

## 4. Environment variables

Set these in **Vercel → Settings → Environment Variables** (Production *and* Preview).

| Variable | Required | Value |
|---|---|---|
| `APP_BASE_URL` | **yes** | `https://reprokit.tech` |
| `DATABASE_URL` | **yes** | Supabase **pooler** URI, port `6543`, `?sslmode=require` |
| `APP_ENV` | **yes** | `production` |
| `GITHUB_TOKEN` | recommended | Fine-grained token, **no scopes** — raises GitHub's limit from 60/hr to 5000/hr for public reads |
| `REPORT_RETENTION_DAYS` | optional | `90` |
| `LLM_PROVIDER` | optional | `none` — the app is fully functional without an LLM |

Also present in `.env.example` but **not read by v1**, because there is no auth and
no client-side database access: `SESSION_SECRET`, `SUPABASE_URL`,
`SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`. Setting them does nothing.
Do not paste a **service role key** into Vercel or any browser code — it bypasses RLS.

---

## 5. Post-deploy verification (do all of this before telling anyone it's live)

```bash
# 1. It is the app, not a redirect to somewhere else
curl -sI https://reprokit.tech | head -5          # expect 200, no 301 to another host
curl -s  https://reprokit.tech/healthz            # expect {"ok":true,...,"database":"postgres"}

# 2. The database survived the trip
#    (if this says "database":"sqlite", DATABASE_URL is not set — fix it now)

# 3. A real end-to-end run on a real issue
#    open https://reprokit.tech, paste a real "needs reproduction" issue URL,
#    answer two questions, confirm the report renders and /r/<id> works.
```

Then, in Supabase, confirm rows are landing:

```sql
select event, count(*) from analytics_events group by event;
select id, verdict, fields_present, created_at from reports order by created_at desc limit 5;
```

**Do not** point the marketing page (`reprokit-landing.html`) at the domain until
the benchmark has run — it claims measured numbers and links to `/app`, neither of
which is true yet. Ship the app's own pages now; swap the landing page in on 26–27 Nov.

---

## 6. The 90-second stranger test (the actual acceptance criterion)

Hand a phone to someone who has not seen the product and say nothing. Watch.
If they stall anywhere, that stall is the next commit — not a new feature.

- [ ] First useful screen in under 2 seconds on mobile data
- [ ] Paste a URL → gaps listed → questions → report, unassisted
- [ ] The "Skip — I don't know" button is findable without explanation
- [ ] A secret pasted into an answer shows `[REDACTED:…]`, with a count
- [ ] The verdict badge is believable when it says "not yet rerunnable"
- [ ] Copy button works on Android Chrome
- [ ] No page in the app contains the words "coming soon"
