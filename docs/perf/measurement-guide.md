# Measurement guide — logs + RTT probe

Two read-only tools under `scripts/perf/` to quantify the API's latency
profile. Neither touches application state: one parses exported logs,
the other sends `SELECT 1` / `PING` only.

## 1. Exporting Railway logs

The access log emits one line per request:

```
method=GET path=/api/v1/tasks status=200 duration_ms=421 \
    db=380/12x6 redis=9x2 ext=0 user=<uuid> company=<uuid>
```

Field reference (from `app/core/middleware.py` + `metrics.py`):

| Field | Meaning |
|---|---|
| `duration_ms` | total request wall time (ms) |
| `db=E/QxN` | `E` = wall ms inside `session.execute()` (all queries incl. network + acquisition), `Q` = pure cursor ms (engine listeners), `N` = statement count |
| `redis=MxO` | `M` = total Redis wall ms, `O` = round trips (pipeline = 1) |
| `ext=T` | external HTTP ms (push providers etc.) |

**Pool wait is NOT in the log line** — it is emitted as the
`X-PoolWait-ms` response header (first-`execute()` entry → first
cursor-execute gap; an upper bound that includes event-loop delay).
The summarizer accepts an optional `pw=`/`poolwait=` token if the line
ever carries one, and shows `—` otherwise. As a rough proxy for "non-
cursor overhead per request", eyeball `db_exec − db_query`.

Export options:

```bash
# Railway CLI — tail or dump recent logs to a file
railway logs --service employee-api > api.log
railway logs --service employee-api | python scripts/perf/summarize_logs.py

# Dashboard: Observability → select the service → export/copy the
# window you need into a file, then:
python scripts/perf/summarize_logs.py api.log
```

Railway's log retention is short; export a busy window (morning check-
ins, shift changes) rather than idle hours.

## 2. Reading the summary table

```
route                       n    p50    p95  dbN   dbEx  poolW   red   ms/q  5xx
GET /api/v1/tasks          120    900   2100  6.0   1800      -    12   300 *SLOW*    0
```

- **ms/q** = `mean(db_exec) / mean(db_count)` — the implied per-statement
  RTT. `>150 ms` is flagged `*SLOW*`: on a healthy same-region link a
  `SELECT 1` round trip is single-digit ms; >150 ms per query is the
  cross-region signature this overhaul targets.
- `dbN` high + `ms/q` low → N+1 problem (reduce queries, Phase-2 style).
- `dbN` normal + `ms/q` high → network/RTT problem (region placement,
  Phase-5 decision).
- `p95` ≫ `p50` with modest `dbEx` → queueing/cold-pool or jitter — check
  `poolW` via response headers on staging.
- `red` high relative to `dbN=0` routes → Redis is the remote hop.

## 3. Running the RTT probe

Run it from the runtime environment (same egress as the API), NOT from
a laptop — local measurements say nothing about the deployed path.

```bash
# inside a Railway shell against the service's env
railway shell --service employee-api
cd backend  # venv with asyncpg + redis already in requirements
python ../scripts/perf/rtt_probe.py

# compare direct vs pooler DSNs side-by-side
python ../scripts/perf/rtt_probe.py \
    --dsn "$DATABASE_URL" --pooler-dsn "$POOLER_DATABASE_URL"
```

Output:

```
Postgres (DATABASE_URL (direct)):
  SELECT 1 reused conn x50           n= 50  min=  280.4  p50=  410.1  p95=  690.2  max=  812.0 ms
  SELECT 1 fresh conn  x10 (incl. connect)  n= 10  min=  950.2  p50= 1300.0  ...
Redis:
  PING reused client   x50           n= 50  min=   95.0  p50=  120.3  ...
```

## 4. Interpreting per-query time

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
