"""Provenance テスト用 fixture — SQLite in-memory で実 DB テスト"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crucible_agent.provenance.models import Base


@pytest.fixture()
async def async_engine():
    """テストごとに新しい SQLite in-memory エンジンを作成"""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def async_session(async_engine):
    """テスト用非同期セッション"""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
