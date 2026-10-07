"""Shared test fixtures — in-memory SQLite session + seeded property graph.

These tests exercise the service layer directly (TaskService,
MaintenanceService, OccupancyService, StructureService,
ResourceStateService) — the same code paths the HTTP routes call, minus
the FastAPI plumbing.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.company import Company
from app.models.employee import Employee
from app.models.property import Property
from app.models.structure import Bed, Dorm, Room, Washroom, WashroomFixture
from app.models.user import User, UserRole
from app.services.structure import StructureService


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def seed(session):
    """A company + property + one user per role + a resource of each kind."""
    company = Company(
        company_name="Acme", brand_name="Acme", address="1 Main St",
        pin_code="10001", email="ops@acme.test", phone_number="555-0000",
    )
    session.add(company)
    await session.flush()
    prop = Property(
        company_id=company.id, name="HQ", code="HQ1", location="Loc",
        city="City", state="ST", manager_name="M", manager_email="m@x.test",
    )
    session.add(prop)
    await session.flush()

    def make_user(role: UserRole, tag: str, employee_id=None) -> User:
        u = User(
            company_id=company.id, property_id=prop.id,
            name=f"{tag} User", email=f"{tag}@acme.test",
            username=tag, password_hash="x", role=role,
            employee_id=employee_id,
        )
        session.add(u)
        return u

    employee = Employee(
        company_id=company.id, property_id=prop.id, name="Worker One",
        email="worker@acme.test", status="active",
    )
    session.add(employee)
    await session.flush()

    admin = make_user(UserRole.SUPER_ADMIN, "admin")
    pm = make_user(UserRole.PROPERTY_MANAGER, "pm")
    hr = make_user(UserRole.HUMAN_RESOURCE, "hr")
    emp_user = make_user(UserRole.EMPLOYEE, "emp", employee_id=employee.id)
    emp_user2 = make_user(UserRole.EMPLOYEE, "emp2")

    room = Room(property_id=prop.id, room_number="101", type="Deluxe")
    dorm = Dorm(
        property_id=prop.id, name="Dorm A", dorm_type="male",
        washroom="attached",
    )
    session.add_all([room, dorm])
    await session.flush()
    bed = Bed(dorm_id=dorm.id, property_id=prop.id, bed_number="Bed 01")
    session.add(bed)
    washroom = Washroom(
        property_id=prop.id, name="W-01", washroom_type="unisex",
    )
    session.add(washroom)
    await session.flush()
    fixture = WashroomFixture(
        property_id=prop.id, washroom_id=washroom.id,
        fixture_type="sink", fixture_number=1,
    )
    session.add(fixture)
    await session.commit()

    return {
        "company": company, "prop": prop, "admin": admin, "pm": pm,
        "hr": hr, "emp_user": emp_user, "emp_user2": emp_user2,
        "employee": employee, "room": room, "dorm": dorm, "bed": bed,
        "washroom": washroom, "fixture": fixture,
    }


@pytest.fixture
def stub_tasks(monkeypatch):
    """Neutralize work-allocation + automation so tests isolate resource
    state. Returns the recorded cleaning-task-generation calls."""
    calls: list[dict] = []

    async def fake_generate(self, user, prop, action, rooms, beds):
        calls.append({
            "action": action,
            "rooms": [r.room_number for r in rooms],
            "beds": [b.bed_number for b in beds],
        })
        return []

    async def fake_automation(self, user, property_id, trigger, zone_id=None):
        return None

    monkeypatch.setattr(
        StructureService, "_generate_cleaning_tasks", fake_generate
    )
    monkeypatch.setattr(
        StructureService, "_fire_automation", fake_automation
    )
    return calls


def new_id() -> uuid.UUID:
    return uuid.uuid4()
