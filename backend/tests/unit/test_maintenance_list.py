"""Maintenance LIST slimming — summary serializer + photo_count via
with_expression inside the list query (no N+1, no collection loads)."""

from app.models.maintenance import (
    MaintenanceTicket,
    MaintenanceTicketAttachment,
)
from app.schemas.maintenance import ticket_out, ticket_summary_out
from app.services.maintenance import MaintenanceService


async def _ticket(session, seed, photos=0, resolution_photos=0):
    t = MaintenanceTicket(
        ticket_number="MT-T-1", company_id=seed["company"].id,
        property_id=seed["prop"].id, room_id=seed["room"].id,
        room_number=seed["room"].room_number,
        reported_by=seed["emp_user"].id, reported_by_name="W",
        maintenance_type="plumbing", issue="Leak", priority="medium",
        status="open", assigned_to=seed["employee"].id,
        assigned_to_name="W",
    )
    session.add(t)
    await session.flush()
    for i in range(photos):
        session.add(MaintenanceTicketAttachment(
            ticket_id=t.id, url=f"/u/i{i}", kind="issue", attempt=1,
        ))
    for i in range(resolution_photos):
        session.add(MaintenanceTicketAttachment(
            ticket_id=t.id, url=f"/u/r{i}", kind="resolution", attempt=1,
        ))
    await session.commit()
    return t


async def test_list_summary_shape_and_photo_count(session, seed):
    t = await _ticket(session, seed, photos=2, resolution_photos=1)
    calls = {"n": 0}
    orig = session.execute

    async def wrapped(*a, **kw):
        calls["n"] += 1
        return await orig(*a, **kw)

    session.execute = wrapped
    try:
        rows = await MaintenanceService(session).list_tickets(
            seed["emp_user"])
        items = [
            ticket_summary_out(x, photo_count=c) for x, c in rows
        ]
    finally:
        session.execute = orig

    # 1 list query total — with_expression puts the count INSIDE it.
    assert calls["n"] == 1
    assert len(items) == 1
    item = items[0]
    assert item["ticket_uid"] == str(t.id)
    assert item["events"] == [] and item["attachments"] == []
    # issue-kind only — resolution photo is not counted
    assert item["photo_count"] == 2


async def test_detail_shape_unchanged(session, seed):
    t = await _ticket(session, seed, photos=1)
    rows = await MaintenanceService(session).list_tickets(
        seed["emp_user"])
    # ticket_out on a non-eager instance lazy-loads per row — that is the
    # documented detail path; the list route uses ticket_summary_out.
    out = ticket_out(
        (await MaintenanceService(session)._get_ticket(
            seed["emp_user"], t.id))
    )
    assert len(out["attachments"]) == 1
    assert rows is not None


async def test_summary_never_lazy_loads(session, seed):
    """Serializing a summary on an unloaded instance must not trigger a
    relationship load — the count comes from the query, not the ORM."""
    t = await _ticket(session, seed, photos=1)
    session.expunge_all()
    from sqlalchemy import select
    fresh = (await session.execute(
        select(MaintenanceTicket).where(MaintenanceTicket.id == t.id)
    )).scalar_one()
    calls = {"n": 0}
    orig = session.execute

    async def wrapped(*a, **kw):
        calls["n"] += 1
        return await orig(*a, **kw)

    session.execute = wrapped
    try:
        out = ticket_summary_out(fresh)
    finally:
        session.execute = orig
    assert calls["n"] == 0
    assert out["photo_count"] is None  # caller-supplied; not ORM-derived
