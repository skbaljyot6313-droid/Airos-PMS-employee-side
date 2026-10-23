#!/usr/bin/env python3
"""Summarize Airco PMS employee-api access-log stage timings.

Reads exported Railway log lines from a file argument or stdin, parses
the AccessLogMiddleware line:

    method=GET path=/api/v1/x status=200 duration_ms=420 \
        db=380/12x6 redis=9x2 ext=0 user=<uuid> company=<uuid>

    db={exec_ms}/{query_ms}x{count}   redis={ms}x{ops}   ext={ms}
    pw={ms}  — pool wait, appended at the END of the line after
    company= (pool-wait is also emitted as the X-PoolWait-ms response
    header). Older exports lack it -> column shows "-".

Output: one table row per route — count, p50/p95 of total ms, mean
db_count, mean db_exec_ms, p95 pool_wait, mean redis_ms, and
db_exec_ms / db_count as "per-query RTT". Flags: *SLOW* when per-query
RTT > 150 ms, *POOLWAIT* when p95 pw > 500 ms.

Output: one table row per route — count, p50/p95 of total ms, mean
db_count, mean db_exec_ms, mean pool_wait, mean redis_ms, and
db_exec_ms / db_count as "per-query RTT". Rows with per-query RTT
> 150 ms are flagged SLOW.

Usage:
    railway logs --service employee-api > api.log
    python backend/scripts/perf/summarize_logs.py api.log
    railway logs --service employee-api | python backend/scripts/perf/summarize_logs.py
"""
import argparse
import re
import sys
from collections import defaultdict

_LINE = re.compile(
    r"method=(?P<method>[A-Z]+)\s+"
    r"path=(?P<path>\S+)\s+"
    r"status=(?P<status>\d+)\s+"
    r"duration_ms=(?P<total>[\d.]+)"
    r"(?:\s+db=(?P<db_exec>[\d.]+)/(?P<db_query>[\d.]+)x(?P<db_count>[\d.]+))?"
    r"(?:\s+redis=(?P<redis_ms>[\d.]+)x(?P<redis_ops>[\d.]+))?"
    r"(?:\s+ext=(?P<ext_ms>[\d.]+))?",
)
# pw= lives at the END of the line (after company=) — independent of the
# stage tuple, so search the whole line rather than extend _LINE.
_PW = re.compile(r"\b(?:pw|poolwait|pool_wait)=([\d.]+)")

_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_NUMSEG = re.compile(r"/\d+(?=/|$)")
# hex blob ids without dashes (uuid hex in paths)
_HEXSEG = re.compile(r"/[0-9a-f]{16,}(?=/|$)")

SLOW_RTT_MS = 150.0
POOLWAIT_P95_MS = 500.0


def route_key(method: str, path: str) -> str:
    """Collapse path params so /tasks/{uuid} aggregates into one row."""
    p = _UUID.sub("{id}", path)
    p = _HEXSEG.sub("/{id}", p)
    p = _NUMSEG.sub("/{id}", p)
    return f"{method} {p}"


def pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", nargs="?", help="log file (default: stdin)")
    ap.add_argument("--min-count", type=int, default=2,
                    help="hide routes with fewer than N samples")
    args = ap.parse_args()

    rows = defaultdict(lambda: {
        "total": [], "db_exec": [], "db_query": [], "db_count": [],
        "redis": [], "ext": [], "pw": [],
        "errors": 0,
    })

    fh = open(args.file, encoding="utf-8", errors="replace") \
        if args.file else sys.stdin
    n_lines = 0
    with fh:
        for line in fh:
            n_lines += 1
            m = _LINE.search(line)
            if m is None:
                continue
            g = m.groupdict()
            r = rows[route_key(g["method"], g["path"])]
            r["total"].append(float(g["total"]))
            if int(g["status"]) >= 500:
                r["errors"] += 1
            if g["db_exec"] is not None:
                r["db_exec"].append(float(g["db_exec"]))
                r["db_query"].append(float(g["db_query"]))
                r["db_count"].append(float(g["db_count"]))
            if g["redis_ms"] is not None:
                r["redis"].append(float(g["redis_ms"]))
            if g["ext_ms"] is not None:
                r["ext"].append(float(g["ext_ms"]))
            pw_m = _PW.search(line)
            if pw_m is not None:
                r["pw"].append(float(pw_m.group(1)))

    if not rows:
        print("No access-log lines matched.", file=sys.stderr)
        return 1

    def mean(v):
        return sum(v) / len(v) if v else 0.0

    table = []
    for route, r in rows.items():
        n = len(r["total"])
        if n < args.min_count:
            continue
        db_n = mean(r["db_count"])
        db_exec = mean(r["db_exec"])
        rtt = db_exec / db_n if db_n > 0 else None
        table.append((
            route, n,
            pct(sorted(r["total"]), 0.50),
            pct(sorted(r["total"]), 0.95),
            db_n, db_exec,
            pct(sorted(r["pw"]), 0.95) if r["pw"] else None,
            mean(r["redis"]),
            rtt,
            r["errors"],
        ))
    table.sort(key=lambda t: -t[5])  # busiest DB work first

    hdr = (
        f"{'route':<48} {'n':>5} {'p50':>6} {'p95':>7} "
        f"{'dbN':>4} {'dbEx':>6} {'pw95':>6} {'red':>5} "
        f"{'ms/q':>6} {'5xx':>4}"
    )
    print(hdr)
    print("-" * len(hdr))
    for (route, n, p50, p95, dbc, dbe, pw, red, rtt, errs) in table:
        flags = []
        if (rtt or 0) > SLOW_RTT_MS:
            flags.append("SLOW")
        if (pw or 0) > POOLWAIT_P95_MS:
            flags.append("POOLWAIT")
        flag = " *" + " ".join(flags) + "*" if flags else ""
        print(
            f"{route:<48.48} {n:>5} {p50:>6.0f} {p95:>7.0f} "
            f"{dbc:>4.1f} {dbe:>6.0f} "
            f"{('%6.0f' % pw) if pw is not None else '     -'} "
            f"{red:>5.0f} "
            f"{('%6.0f' % rtt) if rtt is not None else '     -'}"
            f" {errs:>4}{flag}"
        )

    print(
        f"\nparsed {n_lines} lines, {sum(len(r['total']) for r in rows.values())} "
        f"requests, {len(table)} routes (min-count={args.min_count})"
    )
    print(f"*SLOW* = avg db_exec_ms / db_count > {SLOW_RTT_MS:.0f} ms "
          "(cross-region RTT signature)")
    print(f"*POOLWAIT* = p95 pool wait > {POOLWAIT_P95_MS:.0f} ms "
          "(contended pool or connection churn - includes event-loop "
          "delay, read as an upper bound)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
