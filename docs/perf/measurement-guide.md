# Measurement guide — logs + RTT probe

Two read-only tools under `backend/scripts/perf/` (inside the deployed
image) to quantify the API's latency profile. Neither touches
application state: one parses exported logs, the other sends
`SELECT 1` / `PING` only.

## 1. Exporting Railway logs

The access log emits one line per request:

```
method=GET path=/api/v1/tasks status=200 duration_ms=421 \
    db=380/12x6 redis=9x2 ext=0 user=<uuid> company=<uuid> pw=14
```

Field reference (from `app/core/middleware.py` + `metrics.py`):

| Field | Meaning |
|---|---|
| `duration_ms` | total request wall time (ms) |
| `db=E/QxN` | `E` = wall ms inside `session.execute()` (all queries incl. network + acquisition), `Q` = pure cursor ms (engine listeners), `N` = statement count |
| `redis=MxO` | `M` = total Redis wall ms, `O` = round trips (pipeline = 1) |
| `ext=T` | external HTTP ms (push providers etc.) |
| `pw=P` | pool wait — first `execute()` entry → first cursor-execute gap (ms). **Appended at end of line** so older parsers still work; absent in exports from before this change (summarizer shows `—`). Also emitted as the `X-PoolWait-ms` response header. Upper bound — includes event-loop delay. |

Export options:

```bash
# Railway CLI — dump recent logs to a file
railway logs --service employee-api > api.log
railway logs --service employee-api | python backend/scripts/perf/summarize_logs.py

# Dashboard: Observability → select the service → export/copy the
# window you need into a file, then:
python backend/scripts/perf/summarize_logs.py api.log
```

Railway's log retention is short; export a busy window (morning check-
ins, shift changes) rather than idle hours.

## 2. Reading the summary table

```
route                       n    p50    p95  dbN   dbEx   pw95   red   ms/q  5xx
GET /api/v1/tasks          120    900   2100  6.0   1800    720    12   300 *SLOW POOLWAIT*    0
```

- **ms/q** = `mean(db_exec) / mean(db_count)` — the implied per-statement
  RTT. `>150 ms` is flagged `*SLOW*`: on a healthy same-region link a
  `SELECT 1` round trip is single-digit ms; >150 ms per query is the
  cross-region signature this overhaul targets.
- **pw95** = p95 pool wait. `>500 ms` is flagged `*POOLWAIT*` — the pool
  is contended or connections churn (too-small pool, cold starts, or
  pooler transaction-mode churn). Upper bound — includes event-loop
  delay; corroborate with `dbEx − dbN×(probe p50)`.
- `dbN` high + `ms/q` low → N+1 problem (reduce queries).
- `dbN` normal + `ms/q` high → network/RTT problem (region placement).
- `p95` ≫ `p50` with modest `dbEx` → queueing/cold-pool or jitter —
  check `pw95`.
- `red` high relative to `dbN=0` routes → Redis is the remote hop.

## 3. Running the RTT probe

**Important**: `railway shell` and `railway run` execute **on your local
machine** with the service's env vars — they measure laptop→DB latency
over your ISP/VPN, NOT Railway→DB. The probe must run **inside the
deployed container**:

```bash
railway ssh --service employee-api
# (or: Railway dashboard → service → "Shell" / "Terminal" tab)
```

Inside the container (WORKDIR is `/app`):

```bash
python scripts/perf/rtt_probe.py                      # DATABASE_URL + REDIS_URL
python scripts/perf/rtt_probe.py --dsn "$DATABASE_URL" \
    --pooler-dsn "$POOLER_DATABASE_URL"                # if a pooler URL exists
```

The probe is **read-only**: it sends `SELECT 1` (Postgres) and `PING`
(Redis) — nothing else. No writes, no migrations, no load beyond ~60
single-row round trips.

Output:

```
Postgres (DATABASE_URL (direct)):
  SELECT 1 reused conn x50           n= 50  min=  280.4  p50=  410.1  p95=  690.2  max=  812.0 ms
  SELECT 1 fresh conn  x10 (incl. connect)  n= 10  min=  950.2  p50= 1300.0  ...
Redis:
  PING reused client   x50           n= 50  min=   95.0  p50=  120.3  ...
```

## 4. Railway region vs Supabase region — checklist

Record both before interpreting probe numbers:

- [ ] **Railway service region**: dashboard → `employee-api` service →
      Settings → *Region* (e.g. `us-west2`, `asia-southeast1`). Railway
      does not always show the region in the service view — check the
      project's *Settings → Environments → Deploy region*, or the
      `railway.json`/service config in the dashboard.
- [ ] **Supabase project region**: Supabase dashboard → project →
      Settings → *General → Region* (e.g. `Southeast Asia (Singapore)`
      = `ap-southeast-1`).
- [ ] **Which DSN is in use**: Railway service → Variables →
      `DATABASE_URL` host — `db.<ref>.supabase.co` = direct,
      `aws-0-<region>.pooler.supabase.com` = Supavisor pooler (note the
      region in the pooler hostname — it may differ from the DB region).
- [ ] **Redis location**: Redis provider's dashboard (Upstash/Railway
      plugin) — record the region similarly.
- [ ] Cross-check: `SELECT 1` p50 roughly equal to the inter-region
      latency between the two dashboards' regions → confirms the path
      is network-bound.

## 5. Interpreting per-query time

| Reused-conn `SELECT 1` p50 | What it implies |
|---|---|
| < 10 ms | Same region/AZ — DB network is healthy; optimize query COUNT and plans |
| 10–50 ms | Same region, different zone, or a light pooler hop — acceptable; consolidation still helps |
| 50–150 ms | Cross-region or a loaded pooler — `/bootstrap` consolidation pays off directly |
| 150–700 ms | Cross-ocean (the historical Singapore→DB signature) — region placement is THE fix; no amount of query tuning closes it |
| fresh − reused ≫ 300 ms | Connection setup dominates — a warm pool matters; transaction-pooler misconfig (prepared-statement churn) shows here too |

Sanity check: per-query `ms/q` in the log table should be within ~2× of
the probe's reused-conn p50 (queries do real work). A much higher `ms/q`
means the statements themselves are expensive — look at plans, not the
network.

## 6. Results template — paste back

```
## Regions
- Railway employee-api region:
- Supabase DB region:
- DATABASE_URL kind: direct | pooler (<hostname>)
- Redis provider + region:

## RTT probe (inside railway ssh container)
Postgres direct:   reused p50=__ p95=__ | fresh p50=__ p95=__
Postgres pooler:   reused p50=__ p95=__ | fresh p50=__ p95=__  (skip if none)
Redis:             reused p50=__ p95=__ | fresh p50=__ p95=__

## Log summary (window: ____ to ____, ~__h, N requests)
route                          n    p50   p95  dbN  dbEx  pw95  red  ms/q  flags
GET /api/v1/auth/me
GET /api/v1/bootstrap
GET /api/v1/zones
GET /api/v1/tasks
GET /api/v1/maintenance
GET /api/v1/maintenance/eligible-locations
GET /api/v1/notifications
POST /api/v1/location/current
```
