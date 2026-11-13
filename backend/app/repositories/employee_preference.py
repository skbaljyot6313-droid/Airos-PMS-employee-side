import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_preference import EmployeePreference


class EmployeePreferenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_employee(
        self, employee_id: uuid.UUID
    ) -> EmployeePreference | None:
        res = await self.session.execute(
            select(EmployeePreference).where(
                EmployeePreference.employee_id == employee_id
            )
        )
        return res.scalar_one_or_none()

    async def create(self, *, employee_id: uuid.UUID) -> EmployeePreference:
        pref = EmployeePreference(employee_id=employee_id)
        self.session.add(pref)
        await self.session.flush()
        return pref

    async def get_or_create(
        self, employee_id: uuid.UUID
    ) -> EmployeePreference:
        return (
            await self.get_by_employee(employee_id)
            or await self.create(employee_id=employee_id)
        )
