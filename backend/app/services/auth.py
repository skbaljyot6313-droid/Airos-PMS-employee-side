"""
AuthService — signup, login, token issue/refresh/revocation, profile.

Router → Service → Repository → SQLAlchemy.
"""

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import sessions
from app.core.exceptions import AppError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    slugify_username,
    verify_password,
)
from app.models.user import User, UserRole
from app.repositories.company import CompanyRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.auth import AuthResponse, SignupRequest, company_to_out, user_to_out


class AuthError(AppError):
    pass


class InvalidCredentials(AuthError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_CREDENTIALS"
    message = "Invalid email/username or password."


class EmailAlreadyExists(AuthError):
    status_code = status.HTTP_409_CONFLICT
    code = "EMAIL_ALREADY_EXISTS"
    message = "An account with this email already exists."


class UsernameTaken(AuthError):
    status_code = status.HTTP_409_CONFLICT
    code = "USERNAME_TAKEN"
    message = "This username is already taken."


class AccountInactive(AuthError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "ACCOUNT_INACTIVE"
    message = "This account has been deactivated."


class InvalidRefreshToken(AuthError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_REFRESH_TOKEN"
    message = "Session expired. Please sign in again."


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.companies = CompanyRepository(session)
        self.tokens = RefreshTokenRepository(session)

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------
    async def _issue_tokens(self, user: User) -> tuple[str, str]:
        refresh = generate_refresh_token()
        refresh_hash = hash_refresh_token(refresh)
        # Redis session registry — logout kills the access token's sid
        # immediately instead of letting it live out its JWT expiry.
        # None when Redis is down: the access token carries no sid and
        # auth degrades to plain JWT validation.
        sid = await sessions.create_session(
            user_id=user.id, refresh_hash=refresh_hash
        )
        access = create_access_token(
            user_id=str(user.id),
            company_id=str(user.company_id),
            role=user.role.value,
            session_id=sid,
        )
        await self.tokens.create(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_token_expiry(),
        )
        return access, refresh

    async def _auth_response(self, user: User) -> AuthResponse:
        # Token row + any pending writes commit in a single transaction
        access, refresh = await self._issue_tokens(user)
        await self.session.commit()
        return AuthResponse(
            access_token=access,
            refresh_token=refresh,
            user=user_to_out(user),
            company=company_to_out(user.company),
        )

    async def _unique_username(self, seed: str) -> str:
        base = slugify_username(seed)
        candidate = base
        n = 1
        while await self.users.username_exists(candidate):
            n += 1
            candidate = f"{base}.{n}"
        return candidate

    # ------------------------------------------------------------------
    # Signup — company + initial SUPER_ADMIN in one transaction
    # ------------------------------------------------------------------
    async def signup(self, payload: SignupRequest) -> AuthResponse:
        if await self.users.get_by_email(payload.email):
            raise EmailAlreadyExists()

        username = await self._unique_username(payload.email.split("@")[0])
        # Display name from the email local part until the user edits it
        name = " ".join(
            p.capitalize() for p in slugify_username(payload.email.split("@")[0]).split(".")
        )

        # The session autobegins — both creates flush into one transaction
        # and commit atomically. A failure anywhere rolls back both rows.
        company = await self.companies.create(
            company_name=payload.company_name.strip(),
            brand_name=payload.brand_name.strip(),
            address=payload.address.strip(),
            pin_code=payload.pin_code,
            email=payload.email,
            phone_number=payload.phone,
        )
        try:
            user = await self.users.create(
                company_id=company.id,
                name=name,
                email=payload.email,
                username=username,
                password_hash=hash_password(payload.password),
                phone_number=payload.phone,
                role=UserRole.SUPER_ADMIN,
                job_title="Administrator",
            )
        except IntegrityError as exc:
            # Unique constraint fired (concurrent signup) — rolls back
            # both company and user so no orphan remains.
            raise EmailAlreadyExists() from exc

        # ensure the relationship is available for serialization
        user.company = company

        return await self._auth_response(user)

    # ------------------------------------------------------------------
    # Login — identifier may be email or username
    # ------------------------------------------------------------------
    async def login(self, identifier: str, password: str) -> AuthResponse:
        user = await self.users.get_by_identifier(identifier)
        # Uniform failure — never reveal which part was wrong
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentials()
        if not user.is_active:
            raise AccountInactive()

        await self.users.touch_last_login(user)
        return await self._auth_response(user)

    # ------------------------------------------------------------------
    # Refresh / logout
    # ------------------------------------------------------------------
    async def refresh(self, refresh_token: str) -> str:
        refresh_hash = hash_refresh_token(refresh_token)
        stored = await self.tokens.get_valid(refresh_hash)
        if stored is None:
            raise InvalidRefreshToken()
        user = await self.users.get_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise InvalidRefreshToken()
        # Postgres is the source of truth — a refresh token that's still
        # valid re-materializes its Redis session if it was lost (e.g.
        # Redis restart), so users aren't force-logged-out on a blip.
        sid = await sessions.sid_by_refresh(refresh_hash)
        if sid is None:
            sid = await sessions.create_session(
                user_id=user.id, refresh_hash=refresh_hash
            )
        else:
            await sessions.touch(sid, refresh_hash)
        await self.session.commit()
        return create_access_token(
            user_id=str(user.id),
            company_id=str(user.company_id),
            role=user.role.value,
            session_id=sid,
        )

    async def logout(self, refresh_token: str | None) -> None:
        if refresh_token:
            refresh_hash = hash_refresh_token(refresh_token)
            # Resolve the session's owner BEFORE revoking — logout also
            # deactivates that user's push devices (logout scoping).
            stored = await self.tokens.get_valid(refresh_hash)
            # Kill the Redis session first — in-flight access tokens die
            # on their next request rather than at JWT expiry.
            await sessions.revoke_by_refresh(refresh_hash)
            await self.tokens.revoke(refresh_hash)
            if stored is not None and stored.user_id is not None:
                from app.services.notifications import DeviceRegistry
                await DeviceRegistry(self.session).deactivate_for_user(
                    stored.user_id
                )
            await self.session.commit()
