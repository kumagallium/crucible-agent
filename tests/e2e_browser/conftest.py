"""ブラウザ E2E テスト用 fixture

FastAPI サーバーを実 HTTP ポートで起動し、
run_agent_stream をモックして LLM 不要でチャットフローをテストする。
"""

import asyncio
import socket
import threading
import time
from collections.abc import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
import uvicorn

from crucible_agent.agent.adapter import StreamEvent
from crucible_agent.provenance.models import Base


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def _mock_run_agent_stream(**kwargs) -> AsyncIterator[StreamEvent]:
    """LLM の代わりに固定レスポンスを返すモック"""
    message = kwargs.get("message", "")
    response = f"Mock response to: {message}"

    for chunk in [response[:20], response[20:]]:
        yield StreamEvent(type="text_delta", content=chunk)
        await asyncio.sleep(0.01)

    yield StreamEvent(
        type="done",
        content="",
        token_usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )


def _run_server(port: int, ready_event: threading.Event) -> uvicorn.Server:
    """別スレッドで FastAPI サーバーを起動（DB セットアップ含む）"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # DB セットアップ（このスレッドの event loop で実行）
    async def setup_db():
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return engine

    engine = loop.run_until_complete(setup_db())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # パッチ適用（このスレッド内で）
    patches = [
        patch("crucible_agent.provenance.recorder._session_factory", factory),
        patch("crucible_agent.provenance.recorder._engine", engine),
        patch("crucible_agent.profiles.repository._session_factory", factory),
        patch(
            "crucible_agent.agent.runner.adapter_run_stream",
            side_effect=lambda **kw: _mock_run_agent_stream(**kw),
        ),
    ]
    for p in patches:
        p.start()

    from crucible_agent.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)

    # startup 完了をシグナル
    original_startup = server.startup

    async def patched_startup(*args, **kwargs):
        result = await original_startup(*args, **kwargs)
        ready_event.set()
        return result

    server.startup = patched_startup
    server.run()

    for p in patches:
        p.stop()


@pytest.fixture(scope="session")
def server_url():
    """テスト用 FastAPI サーバーを起動し、URL を返す"""
    port = _find_free_port()
    ready = threading.Event()

    thread = threading.Thread(target=_run_server, args=(port, ready), daemon=True)
    thread.start()

    # サーバー起動を待機（ready_event + HTTP ポーリング）
    ready.wait(timeout=10)
    for _ in range(50):
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
            if resp.status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("テストサーバー起動失敗")

    yield f"http://127.0.0.1:{port}"
