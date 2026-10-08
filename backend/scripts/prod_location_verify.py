"""Production location-API verification — runs the real chain against
the deployed Railway backend:

    login -> /location/start -> /location/current -> /admin/live-locations
    -> /admin/location-history -> duplicate + delayed-ordering checks

Prints PASS/FAIL per step; never prints the service key. Employee coords
in output only for the synthetic test employee.
"""
import asyncio
import json
import os
import sys

import httpx

BASE = "https://employee-api-production-c0e3.up.railway.app/api/v1"
LOGIN_ID = os.environ.get("LOC_VERIFY_LOGIN", "locverify@demo.local")
PASSWORD = os.environ.get("LOC_VERIFY_PASSWORD")
EMP_ID = "de100000-0000-4000-8000-0000000000e1"
PROP_ID = "de100000-0000-4000-8000-0000000000d1"

if not PASSWORD:
    raise SystemExit("set LOC_VERIFY_PASSWORD")


def service_key() -> str:
    """LOCATION_SERVICE_API_KEY — env var wins, .env fallback."""
    v = os.environ.get("LOCATION_SERVICE_API_KEY")
    if v:
        return v
    for line in open(os.path.join(os.path.dirname(__file__), "..", ".env")):
        k, _, v = line.strip().partition("=")
        if k == "LOCATION_SERVICE_API_KEY":
            return v
    return ""


def show(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


async def main() -> int:
    results = []
    async with httpx.AsyncClient(base_url=BASE, timeout=20) as c:
        # --- login ---
        r = await c.post("/auth/login", json={
            "identifier": LOGIN_ID, "password": PASSWORD})
        ok = r.status_code == 200
        show("login employee", ok, r.status_code)
        if not ok:
            print(r.text[:300]); return 1
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # --- session start ---
        r = await c.post("/location/start", headers=auth, json={})
        ok = r.status_code == 200
        show("POST /location/start", ok, r.status_code)
        if not ok:
            print(r.text[:300]); return 1
        sid = r.json()["tracking_session_id"]
        print("     session:", sid)

        # --- ingest ---
        fix = {
            "latitude": 19.0760, "longitude": 72.8777,
            "accuracy": 8.5, "accuracy_m": 8.5,
            "altitude_m": 12.4, "speed_mps": 1.2, "bearing_deg": 184.5,
            "captured_at": "2026-10-08T10:30:00Z",
            "tracking_session_id": sid, "sequence_number": 1,
            "source": "fused",
        }
        r = await c.post("/location/current", headers=auth, json=fix)
        ok = r.status_code == 200 and r.json().get("accepted") is True
        show("POST /location/current", ok, f"{r.status_code} {r.text[:120]}")

        # --- admin live read via X-Location-Service-Key ---
        sk = service_key()
        svc = {"X-Location-Service-Key": sk}
        r = await c.get("/admin/live-locations", headers=svc,
                        params={"employee_id": EMP_ID})
        ok = r.status_code == 200
        show("GET /admin/live-locations (X-Location-Service-Key)", ok,
             r.status_code)
        if ok:
            locs = r.json()["locations"]
            entry = next((e for e in locs
                          if e["employee_id"] == EMP_ID), None)
            show("employee entry present", entry is not None)
            if entry:
                ok = (abs(entry["latitude"] - 19.0760) < 1e-6
                      and abs(entry["longitude"] - 72.8777) < 1e-6
                      and entry["is_stale"] is False
                      and entry.get("tracking_session_id") == sid)
                show("live entry fields match", ok,
                     json.dumps({k: entry[k] for k in
                                 ("latitude", "longitude", "accuracy_m",
                                  "speed_mps", "bearing_deg", "quality",
                                  "is_stale", "tracking_session_id")}))

        # --- filters ---
        r = await c.get("/admin/live-locations", headers=svc)
        show("filter: all employees", r.status_code == 200,
             f"{r.status_code} n={len(r.json().get('locations', []))}")
        r = await c.get("/admin/live-locations", headers=svc,
                        params={"property_id": PROP_ID})
        show("filter: property_id", r.status_code == 200
             and any(e["employee_id"] == EMP_ID
                     for e in r.json()["locations"]),
             f"{r.status_code} n={len(r.json().get('locations', []))}")
        r = await c.get("/admin/live-locations", headers=svc,
                        params={"is_active": True})
        show("filter: is_active=true", r.status_code == 200)

        # --- duplicate ingest (same session+seq) ---
        r = await c.post("/location/current", headers=auth, json=fix)
        ok = r.status_code == 200 and r.json().get("duplicate") is True
        show("duplicate ingest acks duplicate=true", ok, r.text[:120])

        # --- older delayed fix must not clobber live position ---
        older = dict(fix)
        older.update(sequence_number=2, latitude=18.9, longitude=72.0,
                     captured_at="2026-10-08T08:00:00Z")
        r = await c.post("/location/current", headers=auth, json=older)
        show("older fix accepted", r.status_code == 200, r.status_code)
        r = await c.get("/admin/live-locations", headers=svc,
                        params={"employee_id": EMP_ID})
        locs = r.json().get("locations", [])
        if locs:
            e = locs[0]
            ok = abs(e["latitude"] - 19.0760) < 1e-6
            show("live hash kept fresher fix", ok, f"lat={e['latitude']}")
        else:
            show("live hash kept fresher fix", False,
                 f"no entry ({r.status_code})")

        # --- history ---
        r = await c.get(f"/admin/location-history/{EMP_ID}", headers=svc,
                        params={"from": "2026-10-08T00:00:00Z",
                                "to": "2026-10-09T00:00:00Z"})
        ok = r.status_code == 200
        show("GET /admin/location-history", ok, r.status_code)
        if ok:
            body = r.json()
            ok = (body["total_points"] == 2
                  and [p["sequence_number"]
                       for p in body["points"]] == [2, 1]
                  and body["downsampled"] is False)
            show("history ordering + count", ok,
                 f"total={body['total_points']} seqs="
                 f"{[p['sequence_number'] for p in body['points']]}")
            # session filter
            r = await c.get(
                f"/admin/location-history/{EMP_ID}", headers=svc,
                params={"from": "2026-10-08T00:00:00Z",
                        "to": "2026-10-09T00:00:00Z",
                        "tracking_session_id": sid})
            ok = r.status_code == 200 and r.json()["total_points"] == 2
            show("history session filter", ok)
            r = await c.get(
                f"/admin/location-history/{EMP_ID}", headers=svc,
                params={"from": "2026-10-08T00:00:00Z",
                        "to": "2026-10-09T00:00:00Z",
                        "tracking_session_id":
                            "00000000-0000-0000-0000-000000000000"})
            ok = r.status_code == 200 and r.json()["total_points"] == 0
            show("history wrong-session -> empty", ok)
            # range cap (32 days > 31)
            r = await c.get(
                f"/admin/location-history/{EMP_ID}", headers=svc,
                params={"from": "2026-09-01T00:00:00Z",
                        "to": "2026-10-08T12:00:00Z"})
            show("history >31d range rejected", r.status_code == 400,
                 r.status_code)
            # inverted range
            r = await c.get(
                f"/admin/location-history/{EMP_ID}", headers=svc,
                params={"from": "2026-10-09T00:00:00Z",
                        "to": "2026-10-08T00:00:00Z"})
            show("history inverted range rejected",
                 r.status_code == 400, r.status_code)

        # --- security negatives ---
        r = await c.get("/admin/live-locations")
        show("admin: no auth -> 401", r.status_code == 401, r.status_code)
        r = await c.get("/admin/live-locations", headers=auth)
        show("admin: employee JWT -> 401", r.status_code == 401,
             r.status_code)
        r = await c.get("/admin/live-locations",
                        headers={"X-Location-Service-Key": "wrong-key"})
        show("admin: bad service key -> 401", r.status_code == 401,
             r.status_code)

        # --- session stop + post-stop rejection ---
        r = await c.post("/location/stop", headers=auth,
                         json={"tracking_session_id": sid})
        show("POST /location/stop", r.status_code == 200
             and r.json().get("stopped") is True, r.status_code)
        late = dict(fix); late["sequence_number"] = 99
        r = await c.post("/location/current", headers=auth, json=late)
        ok = (r.status_code == 400 and r.json().get("error", {})
              .get("code") == "INVALID_TRACKING_SESSION")
        show("post-stop ingest rejected", ok, r.status_code)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
