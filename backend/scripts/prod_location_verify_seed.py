"""Idempotent test-employee seed for production location verification.

Creates a dedicated tenant chain — company 'LocVerify', property
'LOC-VERIFY', employee 'Location Verify', EMPLOYEE user
'locverify@demo.local' — on fixed UUIDs. Raw GPS never touches Postgres;
these are only the identity rows the API needs.

The password comes from LOC_VERIFY_PASSWORD (never hardcoded); when the
user already exists its password is re-set so rotation works.

Run: LOC_VERIFY_PASSWORD=... python -m scripts.prod_location_verify_seed
"""
import asyncio
import os
import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.company import Company
from app.models.employee import Employee
from app.models.property import Property
from app.models.user import User, UserRole

COMPANY_ID = uuid.UUID("de100000-0000-4000-8000-0000000000c1")
PROP_ID = uuid.UUID("de100000-0000-4000-8000-0000000000d1")
EMP_ID = uuid.UUID("de100000-0000-4000-8000-0000000000e1")
USER_ID = uuid.UUID("de100000-0000-4000-8000-0000000000e2")
LOGIN = "locverify@demo.local"
PASSWORD = os.environ.get("LOC_VERIFY_PASSWORD")
if not PASSWORD:
    raise SystemExit("set LOC_VERIFY_PASSWORD")


async def main() -> None:
    async with AsyncSessionLocal() as s:
        if await s.get(Company, COMPANY_ID) is None:
            s.add(Company(
                id=COMPANY_ID, company_name="LocVerify", brand_name="LocVerify",
                address="1 Verify St", pin_code="400001",
                email="ops@locverify.local", phone_number="555-0199",
            ))
            await s.flush()
        if await s.get(Property, PROP_ID) is None:
            s.add(Property(
                id=PROP_ID, company_id=COMPANY_ID, name="Verify Property",
                code="LOC-VERIFY", location="Verify", city="Mumbai",
                state="MH", manager_name="Verifier",
                manager_email="ops@locverify.local",
            ))
            await s.flush()
        if await s.get(Employee, EMP_ID) is None:
            s.add(Employee(
                id=EMP_ID, company_id=COMPANY_ID, property_id=PROP_ID,
                name="Location Verify", email=LOGIN, status="active",
            ))
            await s.flush()
        user = (await s.execute(
            select(User).where(User.email == LOGIN))).scalar_one_or_none()
        if user is not None:
            # Re-set the password — lets ops rotate the test login.
            user.password_hash = hash_password(PASSWORD)
        else:
            s.add(User(
                id=USER_ID, company_id=COMPANY_ID, property_id=PROP_ID,
                employee_id=EMP_ID, name="Location Verify", email=LOGIN,
                username="locverify", password_hash=hash_password(PASSWORD),
                role=UserRole.EMPLOYEE,
            ))
        await s.commit()
    print("seeded", EMP_ID, PROP_ID)


if __name__ == "__main__":
    asyncio.run(main())
