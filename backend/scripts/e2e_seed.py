"""E2E seed — adds clearly-marked test fixtures to the shared Supabase DB.

Reuses the existing tenant (company 'airco@gmail.com', property PROP-001,
employee 'airco.hk.1@gmail.com' + its EMPLOYEE user) and ADDS:
  - employee 'E2E Emp B'  + EMPLOYEE user 'E2E Emp B' (linked)
  - SUPER_ADMIN user 'E2E Admin' (known password for real /auth/login)

All created passwords: E2eTest!Pass123  (argon2 via app.core.security)
Safe to re-run (idempotent on fixed UUIDs / emails).
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

EMP_B_ID = uuid.UUID("e2e00000-0000-4000-8000-0000000000b1")
USER_B_ID = uuid.UUID("e2e00000-0000-4000-8000-0000000000b2")
USER_SA_ID = uuid.UUID("e2e00000-0000-4000-8000-0000000000ff")

PASSWORD = "E2eTest!Pass123"


async def main() -> None:
    async with AsyncSessionLocal() as s:
        company = (await s.execute(select(Company))).scalars().first()
        prop = (await s.execute(select(Property))).scalars().first()
        assert company and prop, "expected existing tenant rows"
        print(f"tenant: company={company.id} property={prop.id}")

        pw = hash_password(PASSWORD)

        if not await s.get(Employee, EMP_B_ID):
            s.add(Employee(
                id=EMP_B_ID, company_id=company.id, property_id=prop.id,
                name="E2E Emp B", email="e2e.emp.b@test.local",
                username="e2e_emp_b", status="Active",
            ))
            print("created employee E2E Emp B", EMP_B_ID)

        for uid, name, email, uname, role, emp_id in (
            (USER_B_ID, "E2E Emp B", "e2e.emp.b@test.local", "e2e_emp_b",
             UserRole.EMPLOYEE, EMP_B_ID),
            (USER_SA_ID, "E2E Admin", "e2e.admin@test.local", "e2e_admin",
             UserRole.SUPER_ADMIN, None),
        ):
            if not await s.get(User, uid):
                s.add(User(
                    id=uid, company_id=company.id, name=name, email=email,
                    username=uname, password_hash=pw, role=role,
                    employee_id=emp_id, property_id=prop.id,
                ))
                print("created user", name, uid)

        await s.commit()

        # Echo final fixture map
        for row in (await s.execute(select(User))).scalars().all():
            print(f"USER {row.id} role={row.role.value} email={row.email} "
                  f"employee_id={row.employee_id}")


if __name__ == "__main__":
    asyncio.run(main())
