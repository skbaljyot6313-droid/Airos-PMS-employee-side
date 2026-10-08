from app.main import app


def test_mobile_routes_are_registered():
    spec = app.openapi()
    routes = {
        (path, method.upper())
        for path, operations in spec["paths"].items()
        for method in operations
    }
    expected = {
        ("/api/v1/auth/login", "POST"),
        ("/api/v1/auth/refresh", "POST"),
        ("/api/v1/auth/logout", "POST"),
        ("/api/v1/auth/me", "GET"),
        ("/api/v1/auth/me", "PATCH"),
        ("/api/v1/tasks", "GET"),
        ("/api/v1/tasks/{task_id}", "GET"),
        ("/api/v1/tasks/{task_id}/start", "POST"),
        ("/api/v1/tasks/{task_id}/submit", "POST"),
        ("/api/v1/zones", "GET"),
        ("/api/v1/maintenance", "GET"),
        ("/api/v1/maintenance", "POST"),
        ("/api/v1/maintenance/eligible-locations", "GET"),
        ("/api/v1/maintenance/{ticket_id}", "GET"),
        ("/api/v1/maintenance/{ticket_id}/start", "POST"),
        ("/api/v1/maintenance/{ticket_id}/resolve", "POST"),
        ("/api/v1/media/uploads", "POST"),
        ("/api/v1/attendance/today", "GET"),
        ("/api/v1/attendance/start", "POST"),
        ("/api/v1/attendance/break", "POST"),
        ("/api/v1/attendance/resume", "POST"),
        ("/api/v1/attendance/end", "POST"),
        ("/api/v1/attendance/calendar", "GET"),
        ("/api/v1/attendance/requests", "GET"),
        ("/api/v1/attendance/requests", "POST"),
        ("/api/v1/attendance/requests/{request_uid}/cancel", "POST"),
        ("/api/v1/attendance/requests/{request_uid}/approve", "POST"),
        ("/api/v1/attendance/requests/{request_uid}/reject", "POST"),
        ("/api/v1/notifications", "GET"),
        ("/api/v1/notifications/unread-count", "GET"),
        ("/api/v1/notifications/{notification_uid}/read", "POST"),
        ("/api/v1/devices/register", "POST"),
        ("/api/v1/devices/unregister", "POST"),
        ("/api/v1/location/current", "GET"),
        ("/api/v1/location/current", "POST"),
        ("/api/v1/admin/live-locations", "GET"),
    }
    assert expected <= routes


def test_openapi_uses_v1_boundary():
    paths = app.openapi()["paths"]
    assert all(path.startswith("/api/v1/") or path in {"/health", "/health/db", "/ready"} for path in paths)
