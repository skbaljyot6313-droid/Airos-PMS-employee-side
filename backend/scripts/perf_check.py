"""Throwaway-volume EXPLAIN ANALYZE for the attendance query shapes.

Builds a `perf_test` schema with copies of attendance_days /
attendance_requests / properties, fills ~1.5M day rows and ~1M request
rows via generate_series, ANALYZEs, runs the production query shapes,
then drops the schema. Real tables are never touched.

Run: .venv/Scripts/python.exe scripts/perf_check.py
"""
import asyncio

import asyncpg
from sqlalchemy.engine import make_url

from app.core.config import settings

N_EMP = 5000        # fake employees
DAYS_PER_EMP = 300  # ~1.5M attendance_days
REQS_PER_EMP = 200  # ~1M attendance_requests

SETUP = f"""
CREATE SCHEMA IF NOT EXISTS perf_test;
DROP TABLE IF EXISTS perf_test.attendance_days;
DROP TABLE IF EXISTS perf_test.attendance_requests;
DROP TABLE IF EXISTS perf_test.properties;

CREATE TABLE perf_test.properties (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL
);
CREATE INDEX p_props_company ON perf_test.properties (company_id);
INSERT INTO perf_test.properties
SELECT gen_random_uuid(), (ARRAY['f3d3b567-e937-4750-bdcb-5029bcdfc11e',
       '58888380-17df-4062-ab93-cf25f6eea280',
       '935a88ab-d035-4967-b36c-b590f34c433f',
       '35a060cf-ad58-458e-8372-d7ed5a22db23',
       'b30eb3ee-5bf0-4a4e-9416-06232df49e14']::uuid[])[1 + (g % 5)]
FROM generate_series(1, 50) g;

CREATE TABLE perf_test.attendance_days (
    id uuid DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL,
    employee_id uuid NOT NULL,
    employee_name text NOT NULL DEFAULT 'X',
    attendance_date varchar(10) NOT NULL,
    status varchar(16) NOT NULL,
    started_at timestamptz,
    ended_at timestamptz,
    break_seconds int NOT NULL DEFAULT 0,
    work_seconds int
);
CREATE UNIQUE INDEX p_uq_emp_date
    ON perf_test.attendance_days (employee_id, attendance_date);
CREATE INDEX p_open_session
    ON perf_test.attendance_days (employee_id)
    WHERE status = 'present' AND ended_at IS NULL;
CREATE INDEX p_prop_date
    ON perf_test.attendance_days (property_id, attendance_date);

INSERT INTO perf_test.attendance_days
    (property_id, employee_id, employee_name, attendance_date, status,
     started_at, ended_at, break_seconds, work_seconds)
SELECT
    (SELECT id FROM perf_test.properties ORDER BY (e % 50) LIMIT 1),
    -- deterministic pseudo-uuid per fake employee
    ('00000000-0000-4000-8000-' || lpad(to_hex(e), 12, '0'))::uuid,
    'Emp ' || e,
    to_char(date '2025-01-01' + (d % 300), 'YYYY-MM-DD'),
    'present',
    now() - interval '10 hours', now() - interval '1 hour',
    600, 28000
FROM generate_series(1, {N_EMP}) e
CROSS JOIN generate_series(1, {DAYS_PER_EMP}) d;

CREATE TABLE perf_test.attendance_requests (
    id uuid DEFAULT gen_random_uuid(),
    property_id uuid NOT NULL,
    employee_id uuid NOT NULL,
    employee_name text NOT NULL DEFAULT 'X',
    from_date varchar(10) NOT NULL,
    to_date varchar(10) NOT NULL,
    request_type varchar(16) NOT NULL,
    leave_type varchar(32),
    reason text,
    requested_days int NOT NULL,
    status varchar(16) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    leave_range daterange GENERATED ALWAYS AS
        (public.att_leave_range(from_date, to_date)) STORED
);
CREATE INDEX p_rq_emp_status
    ON perf_test.attendance_requests (employee_id, status);
CREATE INDEX p_rq_prop_from
    ON perf_test.attendance_requests (property_id, from_date);
CREATE INDEX p_rq_prop_to
    ON perf_test.attendance_requests (property_id, to_date);
CREATE INDEX p_rq_gist
    ON perf_test.attendance_requests USING gist (employee_id, leave_range)
    WHERE status IN ('pending', 'approved');

-- ~90% decided history, ~10% open (pending/approved) — realistic mix
INSERT INTO perf_test.attendance_requests
    (property_id, employee_id, employee_name, from_date, to_date,
     request_type, leave_type, requested_days, status, created_at)
SELECT
    (SELECT id FROM perf_test.properties ORDER BY (e % 50) LIMIT 1),
    ('00000000-0000-4000-8000-' || lpad(to_hex(e), 12, '0'))::uuid,
    'Emp ' || e,
    to_char(date '2024-01-01' + ((r * 3) % 700), 'YYYY-MM-DD'),
    to_char(date '2024-01-01' + ((r * 3) % 700) + 2, 'YYYY-MM-DD'),
    CASE WHEN r % 4 = 0 THEN 'week_off' ELSE 'leave' END,
    CASE WHEN r % 4 = 0 THEN NULL ELSE 'casual_leave' END,
    3,
    CASE WHEN r % 10 = 0 THEN 'pending'
         WHEN r % 10 = 1 THEN 'approved'
         WHEN r % 10 = 2 THEN 'cancelled'
         ELSE 'rejected' END,
    now() - (r || ' minutes')::interval
FROM generate_series(1, {N_EMP}) e
CROSS JOIN generate_series(1, {REQS_PER_EMP}) r;

ANALYZE perf_test.attendance_days;
ANALYZE perf_test.attendance_requests;
ANALYZE perf_test.properties;
"""

# Pick the fake employee who owns the most rows: employee 42
EMP = "00000000-0000-4000-8000-00000000002a"
PROP_SQL = (
    "SELECT id FROM perf_test.properties ORDER BY (42 % 50) LIMIT 1"
)
COMP = "f3d3b567-e937-4750-bdcb-5029bcdfc11e"


def queries(prop: str) -> list[tuple[str, str]]:
    return [
        ("today: get_day (emp+date)",
         f"SELECT * FROM perf_test.attendance_days "
         f"WHERE employee_id='{EMP}' AND attendance_date='2025-06-15'"),
        ("today: open_request_on lexical",
         f"SELECT * FROM perf_test.attendance_requests "
         f"WHERE employee_id='{EMP}' AND from_date<='2025-06-15' "
         f"AND to_date>='2025-06-15' "
         f"AND status IN ('pending','approved')"),
        ("today: open_request_on GiST",
         f"SELECT * FROM perf_test.attendance_requests "
         f"WHERE employee_id='{EMP}' "
         f"AND leave_range && public.att_leave_range('2025-06-15','2025-06-15') "
         f"AND status IN ('pending','approved')"),
        ("calendar: month days range",
         f"SELECT * FROM perf_test.attendance_days "
         f"WHERE employee_id='{EMP}' AND attendance_date>='2025-06-01' "
         f"AND attendance_date<='2025-06-30' ORDER BY attendance_date"),
        ("calendar: month requests overlap lexical",
         f"SELECT * FROM perf_test.attendance_requests "
         f"WHERE employee_id='{EMP}' AND from_date<='2025-06-30' "
         f"AND to_date>='2025-06-01' AND status IN "
         f"('pending','approved','rejected','cancelled') "
         f"ORDER BY from_date, created_at"),
        ("calendar: month requests overlap GiST",
         f"SELECT * FROM perf_test.attendance_requests "
         f"WHERE employee_id='{EMP}' AND leave_range && "
         f"public.att_leave_range('2025-06-01','2025-06-30') AND status IN "
         f"('pending','approved','rejected','cancelled') "
         f"ORDER BY from_date, created_at"),
        ("create: overlap check lexical",
         f"SELECT * FROM perf_test.attendance_requests "
         f"WHERE employee_id='{EMP}' AND from_date<='2026-02-10' "
         f"AND to_date>='2026-02-01' AND status IN ('pending','approved')"),
        ("create: overlap check GiST",
         f"SELECT * FROM perf_test.attendance_requests "
         f"WHERE employee_id='{EMP}' AND leave_range && "
         f"public.att_leave_range('2026-02-01','2026-02-10') "
         f"AND status IN ('pending','approved')"),
        ("queue: property+status",
         f"SELECT r.* FROM perf_test.attendance_requests r "
         f"WHERE r.property_id='{prop}' AND r.status='pending' "
         f"ORDER BY r.created_at DESC"),
        ("queue: company scope (SA join)",
         f"SELECT r.* FROM perf_test.attendance_requests r "
         f"JOIN perf_test.properties p ON r.property_id=p.id "
         f"WHERE p.company_id='{COMP}' AND r.status='pending' "
         f"ORDER BY r.created_at DESC"),
        ("queue: property+date cover",
         f"SELECT r.* FROM perf_test.attendance_requests r "
         f"WHERE r.property_id='{prop}' AND r.from_date<='2025-06-15' "
         f"AND r.to_date>='2025-06-15' ORDER BY r.created_at DESC"),
        ("open-session lookup",
         f"SELECT * FROM perf_test.attendance_days "
         f"WHERE employee_id='{EMP}' AND status='present' "
         f"AND ended_at IS NULL"),
    ]


async def main() -> None:
    url = make_url(settings.database_url)
    conn = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username,
        password=url.password, database=url.database,
    )
    try:
        print("building perf_test schema (this takes ~30-60s)...")
        await conn.execute(SETUP)
        d = await conn.fetchval("SELECT count(*) FROM perf_test.attendance_days")
        r = await conn.fetchval("SELECT count(*) FROM perf_test.attendance_requests")
        print(f"attendance_days={d}  attendance_requests={r}")
        prop = await conn.fetchval(PROP_SQL)
        print("prop for queue queries:", prop)
        for name, q in queries(str(prop)):
            print("=" * 24, name)
            for row in await conn.fetch("EXPLAIN (ANALYZE, COSTS OFF) " + q):
                print("  ", row["QUERY PLAN"])
    finally:
        await conn.execute("DROP SCHEMA IF EXISTS perf_test CASCADE")
        print("perf_test schema dropped.")
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
