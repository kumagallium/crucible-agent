"""エージェントループ実行 — adapter を呼び出すラッパー"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from crucible_agent.agent.adapter import (
    AdapterResult,
    ApprovalCallback,
    StreamEvent,
)
from crucible_agent.agent.adapter import (
    run as adapter_run,
)
from crucible_agent.agent.adapter import (
    run_stream as adapter_run_stream,
)
from crucible_agent.crucible.discovery import DiscoveredServer, discover_servers
from crucible_agent.prompts.loader import build_instruction

logger = logging.getLogger(__name__)


async def _resolve_servers(
    server_names: list[str] | None,
) -> tuple[list[str], list[DiscoveredServer]]:
    """サーバー名リストを解決する（未指定なら auto-discovery）

    Returns:
        (server_names, discovered_servers)
    """
    discovered = await discover_servers()
    if server_names is not None:
        # 指定されたサーバー名だけフィルタ
        filtered = [s for s in discovered if s.name in server_names]
        return server_names, filtered
    names = [s.name for s in discovered]
    if names:
        logger.info("Crucible から %d 台のサーバーを使用: %s", len(names), names)
    return names, discovered


async def _build_instruction_with_contexts(
    profile: str | None,
    custom_instructions: str | None,
    context_ids: list[str],
) -> str:
    """context_ids の Entity 内容をシステムプロンプトに注入した instruction を構築する"""
    from crucible_agent.provenance.recorder import get_entity

    base = await build_instruction(profile, custom_instructions)
    if not context_ids:
        return base

    context_blocks: list[str] = []
    for entity_id in context_ids:
        entity = await get_entity(entity_id)
        if entity and entity.content:
            context_blocks.append(f"[引用: {entity_id[:8]}...]\n{entity.content}")

    if not context_blocks:
        return base

    injected = "\n\n---\n".join(context_blocks)
    return f"{base}\n\n## 参照文脈（手動引用）\n\n{injected}"


async def run_agent(
    message: str,
    session_id: str | None = None,
    instruction: str | None = None,
    server_names: list[str] | None = None,
    profile: str | None = None,
    custom_instructions: str | None = None,
    context_ids: list[str] | None = None,
) -> dict:
    """エージェントを実行して結果を返す（同期版）"""
    session_id = session_id or str(uuid.uuid4())
    if instruction is None:
        instruction = await _build_instruction_with_contexts(
            profile, custom_instructions, context_ids or []
        )
    server_names, discovered = await _resolve_servers(server_names)

    logger.info("Agent run started (session=%s)", session_id)

    result: AdapterResult = await adapter_run(
        instruction=instruction,
        message=message,
        server_names=server_names,
        discovered_servers=discovered,
        session_id=session_id,
    )

    logger.info("Agent run completed (session=%s)", session_id)

    return {
        "session_id": session_id,
        "message": result.message,
        "tool_calls": result.tool_calls,
        "token_usage": result.token_usage,
        "context_ids": context_ids or [],
    }


async def run_agent_stream(
    message: str,
    session_id: str | None = None,
    instruction: str | None = None,
    server_names: list[str] | None = None,
    profile: str | None = None,
    custom_instructions: str | None = None,
    context_ids: list[str] | None = None,
    require_approval: bool = False,
    approval_callback: ApprovalCallback | None = None,
    conversation_history: list[dict] | None = None,
) -> AsyncIterator[StreamEvent]:
    """エージェントを実行し、イベントをストリームする（WebSocket 用）"""
    instruction = instruction or await _build_instruction_with_contexts(
        profile, custom_instructions, context_ids or []
    )
    server_names, discovered = await _resolve_servers(server_names)

    logger.info("Agent stream started (session=%s, plan_mode=%s)", session_id, require_approval)

    async for event in adapter_run_stream(
        instruction=instruction,
        message=message,
        server_names=server_names,
        discovered_servers=discovered,
        session_id=session_id,
        require_approval=require_approval,
        approval_callback=approval_callback,
        conversation_history=conversation_history,
    ):
        yield event

    logger.info("Agent stream completed (session=%s)", session_id)
