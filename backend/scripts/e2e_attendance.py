"""Live E2E for the attendance request workflow on the configured DB.

Mints real access tokens (JWT_SECRET_KEY from .env) for the Evidence QA
company's users and drives the HTTP API:
  employee files leave -> PM approve = 403 -> SA approve -> days materialized
  employee files week_off -> PM approve = 403 -> SA approve -> week_off day
  overlap -> 409; GET /requests: PM/HR -> 403, employee -> own only.

Run with the API live on :8123:
    PYTHONPATH=. .venv/Scripts/python.exe scripts/e2e_attendance.py
"""
import asyncio
import json
import urllib.request
import urllib.error

from app.core.security import create_access_token

BASE = "http://127.0.0.1:8123/api/v1"
COMPANY = "f3d3b567-e937-4750-bdcb-5029bcdfc11e"

USERS = {
    "SA": ("00208341-1fce-4834-97dc-db5c17f05c16", "super_admin"),
    "PM": ("1eb4a6d5-6496-45e0-b4c5-2ecfe2960bcf", "property_manager"),
    "HR": ("430be9e6-2151-45ea-87a1-0058fcce674e", "human_resource"),
    "EMP": ("1ee41d7b-447d-4a93-a710-070e7c993eed", "employee"),
}

TOKENS = {
    k: create_access_token(user_id=u, company_id=COMPANY, role=r)
    for k, (u, r) in USERS.items()
}
# HR lives in a different company — token carries their real company_id
TOKENS["HR"] = create_access_token(
    user_id=USERS["HR"][0],
    company_id="935a88ab-d035-4967-b36c-b590f34c433f",
    role="human_resource",
)


def call(role: str, method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {TOKENS[role]}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), "-", name, extra)
    return cond


results = []

# -- 1. employee files a leave range (far-future dates, no real days) --
s, r = call("EMP", "POST", "/attendance/requests", {
    "from_date": "2027-03-10", "to_date": "2027-03-12",
    "request_type": "leave", "leave_type": "casual_leave",
    "reason": "E2E leave range",
})
results.append(check("EMP create leave range -> 200", s == 200, f"[{s}]"))
leave_uid = r["request_uid"] if s == 200 else None
results.append(check(
    "response carries request_type='leave'",
    s == 200 and r.get("request_type") == "leave",
))
results.append(check(
    "requested_days == 3 (inclusive)",
    s == 200 and r.get("requested_days") == 3,
))

# -- 2. PM approve -> 403; HR approve -> 403 --
s, _ = call("PM", "POST", f"/attendance/requests/{leave_uid}/approve", {})
results.append(check("PM approve -> 403", s == 403, f"[{s}]"))
s, _ = call("HR", "POST", f"/attendance/requests/{leave_uid}/approve", {})
results.append(check("HR approve -> 403", s == 403, f"[{s}]"))
s, _ = call("PM", "POST", f"/attendance/requests/{leave_uid}/reject", {})
results.append(check("PM reject -> 403", s == 403, f"[{s}]"))

# -- 3. SA approve -> 200, days materialize as 'leave' --
s, r = call("SA", "POST", f"/attendance/requests/{leave_uid}/approve",
            {"review_comment": "e2e ok"})
results.append(check("SA approve -> 200 approved",
                     s == 200 and r.get("status") == "approved", f"[{s}]"))
s, r = call("EMP", "GET", "/attendance/calendar?month=2027-03")
days = {d["date"]: d["status"] for d in (r or {}).get("days", [])} if s == 200 else {}
results.append(check(
    "calendar materialized leave days 10/11/12",
    s == 200 and all(days.get(f"2027-03-{d}") == "leave" for d in (10, 11, 12)),
    str(days),
))
reqs = (r or {}).get("requests", [])
results.append(check(
    "calendar payload includes the request (request_type field)",
    s == 200 and any(
        q.get("request_uid") == leave_uid and q.get("request_type") == "leave"
        for q in reqs
    ),
))

# -- 4. week_off: employee files, PM approve 403, SA approve 200 --
s, r = call("EMP", "POST", "/attendance/requests", {
    "from_date": "2027-04-05", "to_date": "2027-04-06",
    "request_type": "week_off",
})
wo_uid = r["request_uid"] if s == 200 else None
results.append(check("EMP create week_off -> 200", s == 200, f"[{s}]"))
s, _ = call("PM", "POST", f"/attendance/requests/{wo_uid}/approve", {})
results.append(check("PM approve week_off -> 403", s == 403, f"[{s}]"))
s, r = call("SA", "POST", f"/attendance/requests/{wo_uid}/approve", {})
results.append(check("SA approve week_off -> 200",
                     s == 200 and r.get("status") == "approved", f"[{s}]"))
s, r = call("EMP", "GET", "/attendance/calendar?month=2027-04")
days = {d["date"]: d["status"] for d in (r or {}).get("days", [])} if s == 200 else {}
results.append(check(
    "calendar materialized week_off days 05/06",
    s == 200 and days.get("2027-04-05") == "week_off"
    and days.get("2027-04-06") == "week_off",
    str(days),
))

# -- 5. overlap -> 409 --
s, r = call("EMP", "POST", "/attendance/requests", {
    "from_date": "2027-03-12", "to_date": "2027-03-15",
    "request_type": "leave", "leave_type": "sick_leave",
    "reason": "overlaps approved leave",
})
results.append(check("overlapping create -> 409", s == 409, f"[{s}] {r}"))

# -- 6. GET /requests RBAC --
s, r = call("PM", "GET", "/attendance/requests")
results.append(check("GET /requests as PM -> 403", s == 403, f"[{s}]"))
s, r = call("HR", "GET", "/attendance/requests")
results.append(check("GET /requests as HR -> 403", s == 403, f"[{s}]"))
s, r = call("SA", "GET", "/attendance/requests?status=pending")
results.append(check("GET /requests as SA -> 200 queue", s == 200, f"[{s}]"))
s, r = call("EMP", "GET", "/attendance/requests")
items = (r or {}).get("items", []) if s == 200 else []
results.append(check(
    "GET /requests as EMP -> 200 own only",
    s == 200 and all(
        i.get("employee_uid") == "9c7eb6e7-13c8-49f2-89eb-67a152589526"
        for i in items
    ),
    f"[{s}] n={len(items)}",
))
results.append(check(
    "EMP list contains both filed requests",
    leave_uid in [i["request_uid"] for i in items]
    and wo_uid in [i["request_uid"] for i in items],
))

# -- 7. employee cancel of a decided request -> 409 --
s, _ = call("EMP", "POST", f"/attendance/requests/{leave_uid}/cancel")
results.append(check("cancel approved -> 409", s == 409, f"[{s}]"))

# -- 8. cancel a pending request frees the range for re-file --
s, r = call("EMP", "POST", "/attendance/requests", {
    "from_date": "2027-05-01", "to_date": "2027-05-01",
    "request_type": "week_off",
})
pend_uid = r["request_uid"] if s == 200 else None
s, r = call("EMP", "POST", f"/attendance/requests/{pend_uid}/cancel")
results.append(check("cancel pending -> 200 cancelled",
                     s == 200 and r.get("status") == "cancelled", f"[{s}]"))
s, r = call("EMP", "POST", "/attendance/requests", {
    "from_date": "2027-05-01", "to_date": "2027-05-01",
    "request_type": "week_off",
})
results.append(check("re-file after cancel -> 200", s == 200, f"[{s}]"))
refile_uid = r["request_uid"] if s == 200 else None
s, r = call("SA", "POST", f"/attendance/requests/{refile_uid}/reject",
            {"review_comment": "e2e cleanup"})
results.append(check("SA reject -> 200", s == 200, f"[{s}]"))

# -- 9. workday lifecycle still works --
s, r = call("EMP", "GET", "/attendance/today")
results.append(check("GET /today -> 200", s == 200, f"[{s}] state={r and r.get('state')}"))

print()
print(f"{sum(results)}/{len(results)} checks passed")
if not all(results):
    raise SystemExit(1)
