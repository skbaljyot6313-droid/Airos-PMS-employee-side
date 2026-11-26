"""WorkCalendarService — scoped day-feed coverage."""

from datetime import datetime
import uuid

from app.models.attendance import AttendanceBreak, AttendanceDay, AttendanceRequest
from app.models.maintenance import MaintenanceTicket, MaintenanceTicketEvent
from app.models.task import Task, TaskHistoryEvent
from app.services.work_calendar import InvalidDateRange, WorkCalendarService


def ts(hour: int, minute: int = 0) -> datetime:
    # Naive UTC — the SQLite test dialect stores timezone-aware columns naive.
    return datetime(2026, 11, 26, hour, minute)


async def test_range_returns_attendance_work_and_history(session, seed):
    employee = seed["employee"]
    prop = seed["prop"]
    company = seed["company"]
    user = seed["emp_user"]
    day_key = "2026-11-26"

    workday = AttendanceDay(
        property_id=prop.id,
        employee_id=employee.id,
        employee_name=employee.name,
        attendance_date=day_key,
        status="present",
        started_at=ts(3, 30),  # 09:00 IST
        ended_at=ts(12, 30),   # 18:00 IST
        break_seconds=1800,
        work_seconds=30600,
    )
    workday.breaks.append(
        AttendanceBreak(
            started_at=ts(7, 30),
            ended_at=ts(8, 0),
            duration_seconds=1800,
        )
    )

    task = Task(
        property_id=prop.id,
        employee_id=employee.id,
        title="Clean Room 101",
        task_type="fixed",
        status="completed",
        due_date=day_key,
        scheduled_for=ts(3, 30),
        completed_at=ts(8, 0),
    )
    task.history.extend(
        [
            TaskHistoryEvent(type="allocated", at=ts(3, 0), actor_name="Admin"),
            TaskHistoryEvent(type="started", at=ts(3, 45), actor_name=employee.name),
            TaskHistoryEvent(type="completed", at=ts(8, 0), actor_name="Admin"),
        ]
    )
    outside = Task(
        property_id=prop.id,
        employee_id=employee.id,
        title="Tomorrow",
        due_date="2026-11-27",
        created_at=datetime(2026, 11, 25, 17, 0),  # 22:30 IST, before the range
    )

    ticket = MaintenanceTicket(
        ticket_number="MT-2026-00001",
        company_id=company.id,
        property_id=prop.id,
        room_id=seed["room"].id,
        room_number="101",
        reported_by_name="Front Desk",
        maintenance_type="plumbing",
        issue="Fix tap",
        priority="high",
        status="closed",
        assigned_to=employee.id,
        assigned_to_name=employee.name,
        due_date=day_key,
        resolved_at=ts(9, 0),
        closed_at=ts(10, 0),
    )
    ticket.events.extend(
        [
            MaintenanceTicketEvent(action="assigned", created_at=ts(3, 15)),
            MaintenanceTicketEvent(action="resolved", created_at=ts(9, 0)),
            MaintenanceTicketEvent(action="closed", created_at=ts(10, 0)),
        ]
    )

    request = AttendanceRequest(
        property_id=prop.id,
        employee_id=employee.id,
        employee_name=employee.name,
        from_date=day_key,
        to_date="2026-11-27",
        request_type="leave",
        leave_type="casual_leave",
        requested_days=2,
        status="pending",
    )
    session.add_all([workday, task, outside, ticket, request])
    await session.commit()

    out = await WorkCalendarService(session).range(user, day_key, day_key)

    assert out["date_from"] == day_key
    assert len(out["days"]) == 1
    attendance = out["days"][0]["attendance"]
    assert attendance["status"] == "present"
    assert attendance["started_at"] == ts(3, 30)
    assert attendance["breaks"] == [
        {
            "started_at": ts(7, 30),
            "ended_at": ts(8, 0),
            "duration_seconds": 1800,
        }
    ]
    assert [r["request_uid"] for r in out["requests"]] == [str(request.id)]
    assert [t["task_uid"] for t in out["tasks"]] == [str(task.id)]
    assert [h["type"] for h in out["tasks"][0]["history"]] == [
        "allocated",
        "started",
        "completed",
    ]
    assert [t["ticket_uid"] for t in out["maintenance"]] == [str(ticket.id)]
    assert [e["action"] for e in out["maintenance"][0]["events"]] == [
        "assigned",
        "resolved",
        "closed",
    ]


async def test_range_selects_activity_only_days_and_hides_other_people(
    session, seed,
):
    employee = seed["employee"]
    user = seed["emp_user"]
    prop = seed["prop"]
    day_key = "2026-11-26"

    task = Task(
        property_id=prop.id,
        employee_id=employee.id,
        title="Activity-only task",
        due_date="2026-11-30",
    )
    task.history.append(
        TaskHistoryEvent(type="started", at=ts(4, 0), actor_name=employee.name)
    )
    other = Task(
        property_id=prop.id,
        employee_id=uuid.uuid4(),
        title="Someone else's task",
        due_date=day_key,
    )
    session.add_all([task, other])
    await session.commit()

    out = await WorkCalendarService(session).range(user, day_key, day_key)
    assert [t["title"] for t in out["tasks"]] == ["Activity-only task"]
    assert out["days"][0]["attendance"]["state"] == "not_started"


async def test_unlinked_user_gets_an_empty_scoped_feed(session, seed):
    out = await WorkCalendarService(session).range(
        seed["hr"], "2026-11-26", "2026-11-27"
    )
    assert len(out["days"]) == 2
    assert out["tasks"] == []
    assert out["maintenance"] == []


async def test_rejects_bad_or_oversized_ranges(session, seed):
    svc = WorkCalendarService(session)
    for args in [
        ("2026-11-27", "2026-11-26"),
        ("2026-01-01", "2026-05-01"),
        ("bad", "2026-11-26"),
    ]:
        try:
            await svc.range(seed["emp_user"], *args)
        except InvalidDateRange:
            pass
        else:
            raise AssertionError(f"range accepted: {args}")
