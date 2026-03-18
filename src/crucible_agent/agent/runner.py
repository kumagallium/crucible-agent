"""エージェントループ実行 — adapter を呼び出すラッパー"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from crucible_agent.agent.adapter import (
    AdapterResult,
    StreamEvent,
    run as adapter_run,
    run_stream as adapter_run_stream,
)
from crucible_agent.crucible.discovery import discover_servers

logger = logging.getLogger(__name__)

# デフォルトのシステムプロンプト（Phase 4 でプロファイルから読み込む）
DEFAULT_INSTRUCTION = (
    "You are a helpful AI assistant. "
    "Use the available tools to assist the user. "
    "Be concise and accurate."
)


async def _resolve_servers(server_names: list[str] | None) -> list[str]:
    """サーバー名リストを解決する（未指定なら auto-discovery）"""
    if server_names is not None:
        return server_names
    discovered = await discover_servers()
    names = [s.name for s in discovered]
    if names:
        logger.info("Crucible から %d 台のサーバーを使用: %s", len(names), names)
    return names


async def run_agent(
    message: str,
    session_id: str | None = None,
    instruction: str | None = None,
    server_names: list[str] | None = None,
) -> dict:
    """エージェントを実行して結果を返す（同期版）"""
    session_id = session_id or str(uuid.uuid4())
    instruction = instruction or DEFAULT_INSTRUCTION
    server_names = await _resolve_servers(server_names)

    logger.info("Agent run started (session=%s)", session_id)

    result: AdapterResult = await adapter_run(
        instruction=instruction,
        message=message,
        server_names=server_names,
    )

    logger.info("Agent run completed (session=%s)", session_id)

    return {
        "session_id": session_id,
        "message": result.message,
        "tool_calls": result.tool_calls,
        "token_usage": result.token_usage,
    }


async def run_agent_stream(
    message: str,
    session_id: str | None = None,
    instruction: str | None = None,
    server_names: list[str] | None = None,
) -> AsyncIterator[StreamEvent]:
    """エージェントを実行し、イベントをストリームする（WebSocket 用）"""
    instruction = instruction or DEFAULT_INSTRUCTION
    server_names = await _resolve_servers(server_names)

    logger.info("Agent stream started (session=%s)", session_id)

    async for event in adapter_run_stream(
        instruction=instruction,
        message=message,
        server_names=server_names,
    ):
        yield event

    logger.info("Agent stream completed (session=%s)", session_id)
