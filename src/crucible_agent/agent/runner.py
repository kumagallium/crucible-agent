"""エージェントループ実行 — adapter を呼び出すラッパー"""

from __future__ import annotations

import logging
import uuid

from crucible_agent.agent.adapter import AdapterResult, run as adapter_run
from crucible_agent.crucible.discovery import discover_servers

logger = logging.getLogger(__name__)

# デフォルトのシステムプロンプト（Phase 4 でプロファイルから読み込む）
DEFAULT_INSTRUCTION = (
    "You are a helpful AI assistant. "
    "Use the available tools to assist the user. "
    "Be concise and accurate."
)


async def run_agent(
    message: str,
    session_id: str | None = None,
    instruction: str | None = None,
    server_names: list[str] | None = None,
) -> dict:
    """エージェントを実行して結果を返す

    Args:
        message: ユーザーメッセージ
        session_id: セッション ID（省略時は新規生成）
        instruction: システムプロンプト（省略時はデフォルト）
        server_names: 使用する MCP サーバー名リスト
    """
    session_id = session_id or str(uuid.uuid4())
    instruction = instruction or DEFAULT_INSTRUCTION

    # Crucible auto-discovery でサーバーを取得（指定がなければ）
    if server_names is None:
        discovered = await discover_servers()
        server_names = [s.name for s in discovered]
        if server_names:
            logger.info("Crucible から %d 台のサーバーを使用: %s", len(server_names), server_names)

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
