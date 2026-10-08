import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.user import User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        res = await self.session.execute(
            select(User)
            .options(joinedload(User.company))
            .where(User.id == user_id)
        )
        return res.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        res = await self.session.execute(
            select(User)
            .options(joinedload(User.company))
            .where(func.lower(User.email) == email.lower())
        )
        return res.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        res = await self.session.execute(
            select(User)
            .options(joinedload(User.company))
            .where(func.lower(User.username) == username.lower())
        )
        return res.scalar_one_or_none()

    async def get_by_identifier(self, identifier: str) -> User | None:
        """Resolve login identifier — email or username, case-insensitive."""
        ident = identifier.strip()
        if "@" in ident:
            return await self.get_by_email(ident)
        return await self.get_by_username(ident)

    async def username_exists(self, username: str) -> bool:
        res = await self.session.execute(
            select(User.id).where(func.lower(User.username) == username.lower())
        )
        return res.scalar_one_or_none() is not None

    async def create(
        self,
        *,
        company_id: uuid.UUID,
        name: str,
        email: str,
        username: str,
        password_hash: str,
        phone_number: str | None = None,
        role: UserRole = UserRole.EMPLOYEE,
        property_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None,
        zone_id: uuid.UUID | None = None,
        job_title: str | None = None,
    ) -> User:
        user = User(
            company_id=company_id,
            name=name,
            email=email,
            username=username,
            password_hash=password_hash,
            phone_number=phone_number,
            role=role,
            property_id=property_id,
            employee_id=employee_id,
            zone_id=zone_id,
            job_title=job_title,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def touch_last_login(self, user: User) -> None:
        user.last_login_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def update_profile(
        self, user: User, *, name=None, phone_number=None, email=None
    ) -> User:
        if name is not None:
            user.name = name
        if phone_number is not None:
            user.phone_number = phone_number
        if email is not None:
            user.email = email.lower()
        await self.session.flush()
        return user
