"""E2E テスト用 fixture — FastAPI TestClient + SQLite in-memory"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crucible_agent.provenance.models import Base


@pytest.fixture()
async def app_with_db():
    """SQLite in-memory DB 付きの FastAPI app を生成"""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)

    # テーブル作成
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    # recorder と repository の _session_factory を差し替え
    with (
        patch("crucible_agent.provenance.recorder._session_factory", factory),
        patch("crucible_agent.provenance.recorder._engine", engine),
        patch("crucible_agent.profiles.repository._session_factory", factory),
    ):
        from crucible_agent.main import app

        yield app

    # クリーンアップ
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def client(app_with_db):
    """非同期 HTTP テストクライアント"""
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
