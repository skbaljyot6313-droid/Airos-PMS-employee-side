"""Demo seed for the local Docker stack — creates a full tenant from
scratch (unlike e2e_seed.py, which expects an existing Supabase tenant).

Creates, all idempotent on fixed UUIDs:
  - company 'Demo Co' + property 'DEMO-001'
  - employee 'Demo Employee' + linked EMPLOYEE user
  - SUPER_ADMIN user 'Demo Admin'

Logins (identifier = email or username):
  admin@demo.local / Demo!Pass123     (super_admin)
  employee@demo.local / Demo!Pass123  (employee)

Run inside compose:  docker compose --profile seed run --rm seed
or locally:          python -m scripts.seed_demo
"""

import asyncio
import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.security import hash_password
from app.models.company import Company
from app.models.employee import Employee
from app.models.property import Property
from app.models.user import User, UserRole

COMPANY_ID = uuid.UUID("de000000-0000-4000-8000-0000000000c0")
PROP_ID = uuid.UUID("de000000-0000-4000-8000-0000000000d0")
EMP_ID = uuid.UUID("de000000-0000-4000-8000-0000000000e1")
USER_EMP_ID = uuid.UUID("de000000-0000-4000-8000-0000000000e2")
USER_ADMIN_ID = uuid.UUID("de000000-0000-4000-8000-0000000000a1")

PASSWORD = "Demo!Pass123"


async def main() -> None:
    async with AsyncSessionLocal() as s:
        company = await s.get(Company, COMPANY_ID)
        if company is None:
            company = Company(
                id=COMPANY_ID, company_name="Demo Co", brand_name="Demo",
                address="1 Demo St", pin_code="10001", email="ops@demo.local",
                phone_number="555-0100",
            )
            s.add(company)
            await s.flush()
            print(f"created company Demo Co ({COMPANY_ID})")

        prop = await s.get(Property, PROP_ID)
        if prop is None:
            prop = Property(
                id=PROP_ID, company_id=company.id, name="Demo Property",
                code="DEMO-001", location="Demo Loc", city="Demo City",
                state="DS", manager_name="Demo Admin",
                manager_email="admin@demo.local",
            )
            s.add(prop)
            await s.flush()
            print(f"created property Demo Property ({PROP_ID})")

        employee = await s.get(Employee, EMP_ID)
        if employee is None:
            employee = Employee(
                id=EMP_ID, company_id=company.id, property_id=prop.id,
                name="Demo Employee", email="employee@demo.local",
                username="demo_employee", status="Active",
                job_title="Housekeeping",
            )
            s.add(employee)
            await s.flush()
            print(f"created employee Demo Employee ({EMP_ID})")

        pw = hash_password(PASSWORD)
        for uid, name, email, uname, role, emp_id in (
            (USER_ADMIN_ID, "Demo Admin", "admin@demo.local",
             "demo_admin", UserRole.SUPER_ADMIN, None),
            (USER_EMP_ID, "Demo Employee", "employee@demo.local",
             "demo_employee", UserRole.EMPLOYEE, EMP_ID),
        ):
            if not await s.get(User, uid):
                s.add(User(
                    id=uid, company_id=company.id, name=name, email=email,
                    username=uname, password_hash=pw, role=role,
                    employee_id=emp_id, property_id=prop.id,
                ))
                print(f"created user {name} ({uid}) role={role.value}")

        await s.commit()
        print("\nLogins:  admin@demo.local | employee@demo.local  "
              f"(password: {PASSWORD})")


if __name__ == "__main__":
    asyncio.run(main())
