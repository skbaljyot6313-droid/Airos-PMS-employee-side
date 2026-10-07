from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, user_id, token_hash: str, expires_at) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_valid(self, token_hash: str) -> RefreshToken | None:
        res = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked.is_(False),
                RefreshToken.expires_at > datetime.now(timezone.utc),
            )
        )
        return res.scalar_one_or_none()

    async def revoke(self, token_hash: str) -> None:
        token = await self.get_valid(token_hash)
        if token:
            token.revoked = True
            await self.session.flush()

    async def revoke_all_for_user(self, user_id) -> int:
        res = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)
            )
        )
        tokens = res.scalars().all()
        for t in tokens:
            t.revoked = True
        await self.session.flush()
        return len(tokens)
