import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company


class CompanyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, company_id: uuid.UUID) -> Company | None:
        res = await self.session.execute(
            select(Company).where(Company.id == company_id)
        )
        return res.scalar_one_or_none()

    async def create(
        self,
        *,
        company_name: str,
        brand_name: str,
        address: str,
        pin_code: str,
        email: str,
        phone_number: str,
    ) -> Company:
        company = Company(
            company_name=company_name,
            brand_name=brand_name,
            address=address,
            pin_code=pin_code,
            email=email,
            phone_number=phone_number,
        )
        self.session.add(company)
        await self.session.flush()
        return company
