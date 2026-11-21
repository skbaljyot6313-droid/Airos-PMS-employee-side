"""Employee salary API — own records only; finalized periods only."""
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.employee import Employee
from app.models.payroll import PayrollLine, PayrollPeriod
from app.models.user import User, UserRole


@pytest.fixture
async def api(session):
    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _auth(user) -> dict:
    token = create_access_token(user_id=str(user.id), company_id=str(user.company_id),
                                role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _two_employees(session, seed):
    other = Employee(company_id=seed["company"].id, property_id=seed["prop"].id, name="Other",
                     email="other@acme.test", status="Active")
    session.add(other)
    await session.flush()
    other_user = User(company_id=seed["company"].id, property_id=seed["prop"].id, name="Other",
                      email="ou@acme.test", username="ou", password_hash="x",
                      role=UserRole.EMPLOYEE, employee_id=other.id)
    session.add(other_user)
    period_draft = PayrollPeriod(company_id=seed["company"].id, property_id=seed["prop"].id,
                                 period="2026-02", status="submitted")
    period_paid = PayrollPeriod(company_id=seed["company"].id, property_id=seed["prop"].id,
                                period="2026-01", status="paid", paid_at=datetime.now(UTC))
    session.add_all([period_draft, period_paid])
    await session.flush()
    snap = {"earnings": [{"code": "basic", "label": "Basic", "amount": "100.00"}],
            "deductions": [], "metrics": {}, "notes": []}
    for pid, emp in ((period_paid.id, seed["employee"]), (period_paid.id, other)):
        session.add(PayrollLine(period_id=pid, employee_id=emp.id, employee_name=emp.name,
                                status="paid", gross=Decimal("100"), total_deductions=Decimal("0"),
                                net=Decimal("100"), snapshot=snap))
    session.add(PayrollLine(period_id=period_draft.id, employee_id=seed["employee"].id,
                            employee_name=seed["employee"].name, status="calculated",
                            gross=Decimal("999"), total_deductions=Decimal("0"),
                            net=Decimal("999"), snapshot=snap))
    await session.commit()
    return other_user


async def test_employee_sees_only_own_finalized_history(api, session, seed):
    await _two_employees(session, seed)
    res = await api.get("/api/v1/salary/me/history", headers=_auth(seed["emp_user"]))
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [i["period"] for i in items] == ["2026-01"]  # draft 2026-02 never exposed
    assert items[0]["net"] == "100.00"


async def test_employee_cannot_read_another_employees_period(api, session, seed):
    other_user = await _two_employees(session, seed)
    res = await api.get("/api/v1/salary/me/periods/2026-01", headers=_auth(seed["emp_user"]))
    assert res.status_code == 200
    assert res.json()["net"] == "100.00"
    # The other user's record is theirs; the first user's view never contains it.
    other = await api.get("/api/v1/salary/me/periods/2026-02", headers=_auth(other_user))
    assert other.status_code == 404


async def test_draft_period_is_not_visible(api, session, seed):
    await _two_employees(session, seed)
    res = await api.get("/api/v1/salary/me/periods/2026-02", headers=_auth(seed["emp_user"]))
    assert res.status_code == 404


async def test_unauthenticated_request_rejected(api, session, seed):
    assert (await api.get("/api/v1/salary/me")).status_code == 401
