"""Mobile release registry — active release lookup + release management.

Rules that protect employees from bad deploys:
  * version_code must strictly increase — a release at or below the
    current latest is rejected, so a stale CI run can't downgrade prod.
  * exactly one release per platform is active; publishing a new row
    atomically deactivates the previous one.
  * rows are never deleted — rollback re-activates an older release.
"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.mobile_release import MobileRelease
from app.schemas.mobile import MobileReleaseCreate


class ReleaseConflict(AppError):
    status_code = 409
    code = "RELEASE_CONFLICT"


class ReleaseNotFound(AppError):
    status_code = 404
    code = "RELEASE_NOT_FOUND"
    message = "No mobile release is published for this platform."


async def get_active_release(
    session: AsyncSession, platform: str
) -> MobileRelease | None:
    result = await session.execute(
        select(MobileRelease)
        .where(
            MobileRelease.platform == platform,
            MobileRelease.is_active.is_(True),
        )
        .order_by(MobileRelease.version_code.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_releases(
    session: AsyncSession, platform: str
) -> list[MobileRelease]:
    result = await session.execute(
        select(MobileRelease)
        .where(MobileRelease.platform == platform)
        .order_by(MobileRelease.version_code.desc())
    )
    return list(result.scalars())


async def publish_release(
    session: AsyncSession, data: MobileReleaseCreate
) -> MobileRelease:
    """Insert a release and make it the active one for its platform."""
    latest_code = await session.scalar(
        select(func.max(MobileRelease.version_code)).where(
            MobileRelease.platform == data.platform
        )
    )
    if latest_code is not None and data.version_code <= latest_code:
        raise ReleaseConflict(
            f"version_code {data.version_code} is not newer than the "
            f"current latest ({latest_code}) — bump the build."
        )
    if data.minimum_version_code > data.version_code:
        raise ReleaseConflict(
            "minimum_version_code cannot exceed the release version_code"
        )
    await session.execute(
        update(MobileRelease)
        .where(MobileRelease.platform == data.platform)
        .values(is_active=False)
    )
    release = MobileRelease(**data.model_dump(), is_active=True)
    session.add(release)
    await session.commit()
    await session.refresh(release)
    return release


async def update_release(
    session: AsyncSession,
    release_id,
    platform: str,
    data,
) -> MobileRelease:
    """Patch mutable fields (download_url, release_notes) on an existing
    release — lets ops repoint a download without a version bump."""
    release = await session.get(MobileRelease, release_id)
    if release is None or release.platform != platform:
        raise ReleaseNotFound("Release not found for this platform.")
    patch = data.model_dump(exclude_unset=True)
    if patch:
        for key, value in patch.items():
            setattr(release, key, value)
        await session.commit()
        await session.refresh(release)
    return release


async def activate_release(
    session: AsyncSession, release_id, platform: str
) -> MobileRelease:
    """Rollback: mark an existing release as the active one again."""
    release = await session.get(MobileRelease, release_id)
    if release is None or release.platform != platform:
        raise ReleaseNotFound("Release not found for this platform.")
    await session.execute(
        update(MobileRelease)
        .where(MobileRelease.platform == platform)
        .values(is_active=False)
    )
    release.is_active = True
    await session.commit()
    await session.refresh(release)
    return release
