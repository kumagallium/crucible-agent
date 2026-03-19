"""プロファイル CRUD — DB 操作"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from crucible_agent.provenance.models import Profile
from crucible_agent.provenance.recorder import _session_factory

logger = logging.getLogger(__name__)


async def list_profiles() -> list[Profile]:
    """アクティブなプロファイル一覧を返す（名前順）"""
    async with _session_factory() as db:
        result = await db.execute(
            select(Profile).where(Profile.is_active == True).order_by(Profile.name)  # noqa: E712
        )
        return list(result.scalars().all())


async def get_profile(profile_id: str) -> Profile | None:
    """ID でプロファイルを取得する"""
    async with _session_factory() as db:
        result = await db.execute(
            select(Profile).where(Profile.id == profile_id, Profile.is_active == True)  # noqa: E712
        )
        return result.scalar_one_or_none()


async def get_profile_by_name(name: str) -> Profile | None:
    """名前でプロファイルを取得する"""
    async with _session_factory() as db:
        result = await db.execute(
            select(Profile).where(Profile.name == name, Profile.is_active == True)  # noqa: E712
        )
        return result.scalar_one_or_none()


async def create_profile(name: str, description: str, content: str) -> Profile:
    """プロファイルを作成する"""
    async with _session_factory() as db:
        profile = Profile(name=name, description=description, content=content)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        logger.info("Profile created: %s (id=%s)", name, profile.id)
        return profile


async def update_profile(
    profile_id: str,
    name: str | None = None,
    description: str | None = None,
    content: str | None = None,
) -> Profile | None:
    """プロファイルを更新する。見つからない場合は None を返す"""
    async with _session_factory() as db:
        result = await db.execute(
            select(Profile).where(Profile.id == profile_id, Profile.is_active == True)  # noqa: E712
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            return None

        if name is not None:
            profile.name = name
        if description is not None:
            profile.description = description
        if content is not None:
            profile.content = content
        profile.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(profile)
        logger.info("Profile updated: %s (id=%s)", profile.name, profile.id)
        return profile


async def delete_profile(profile_id: str) -> bool:
    """プロファイルを論理削除する。成功した場合は True を返す"""
    async with _session_factory() as db:
        result = await db.execute(
            select(Profile).where(Profile.id == profile_id, Profile.is_active == True)  # noqa: E712
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            return False

        profile.is_active = False
        profile.updated_at = datetime.now(UTC)
        await db.commit()
        logger.info("Profile deleted: %s (id=%s)", profile.name, profile.id)
        return True
