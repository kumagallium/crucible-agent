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
from crucible_agent.crucible.discovery import (
    DiscoveredCliLibrary,
    DiscoveredServer,
    discover_all_tools,
    discover_servers,
)
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


async def _resolve_tools(
    server_names: list[str] | None,
) -> tuple[list[str], list[DiscoveredServer], list[DiscoveredCliLibrary]]:
    """3 種のツールを解決する（MCP サーバー + CLI/Library）

    Returns:
        (server_names, discovered_servers, cli_libraries)
    """
    all_tools = await discover_all_tools()

    servers = all_tools.servers
    if server_names is not None:
        servers = [s for s in servers if s.name in server_names]

    names = [s.name for s in servers]
    if names:
        logger.info("Crucible から %d 台の MCP サーバーを使用: %s", len(names), names)
    if all_tools.cli_libraries:
        logger.info(
            "Crucible から %d 個の CLI/Library を使用: %s",
            len(all_tools.cli_libraries),
            [t.name for t in all_tools.cli_libraries],
        )

    return names, servers, all_tools.cli_libraries


async def _build_instruction_with_contexts(
    profile: str | None,
    custom_instructions: str | None,
    context_ids: list[str],
) -> str:
    """instruction を構築する（context_ids は別途メッセージに注入）"""
    return await build_instruction(profile, custom_instructions)


async def _build_context_prefix(context_ids: list[str]) -> str:
    """context_ids の Entity 内容をユーザーメッセージの前に付与する文字列を構築する"""
    from crucible_agent.provenance.recorder import get_entity

    if not context_ids:
        return ""

    context_blocks: list[str] = []
    for entity_id in context_ids:
        entity = await get_entity(entity_id)
        if entity and entity.content:
            context_blocks.append(
                f"[引用されたメッセージ]\n{entity.content}"
            )

    if not context_blocks:
        return ""

    return "\n\n".join(context_blocks) + "\n\n---\n\n"


async def run_agent(
    message: str,
    session_id: str | None = None,
    instruction: str | None = None,
    server_names: list[str] | None = None,
    profile: str | None = None,
    custom_instructions: str | None = None,
    context_ids: list[str] | None = None,
    model: str | None = None,
) -> dict:
    """エージェントを実行して結果を返す（同期版）"""
    session_id = session_id or str(uuid.uuid4())
    if instruction is None:
        instruction = await _build_instruction_with_contexts(
            profile, custom_instructions, context_ids or []
        )
    server_names, discovered, cli_libs = await _resolve_tools(server_names)

    logger.info("Agent run started (session=%s)", session_id)

    result: AdapterResult = await adapter_run(
        instruction=instruction,
        message=message,
        server_names=server_names,
        discovered_servers=discovered,
        cli_libraries=cli_libs,
        session_id=session_id,
        model=model,
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
    model: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """エージェントを実行し、イベントをストリームする（WebSocket 用）"""
    instruction = instruction or await _build_instruction_with_contexts(
        profile, custom_instructions, context_ids or [],
    )
    # 引用コンテキストをユーザーメッセージに直���付与（LLM が確実に参照するため）
    context_prefix = await _build_context_prefix(context_ids or [])
    if context_prefix:
        message = context_prefix + message

    server_names, discovered, cli_libs = await _resolve_tools(server_names)

    logger.info("Agent stream started (session=%s, plan_mode=%s)", session_id, require_approval)

    async for event in adapter_run_stream(
        instruction=instruction,
        message=message,
        server_names=server_names,
        discovered_servers=discovered,
        cli_libraries=cli_libs,
        session_id=session_id,
        require_approval=require_approval,
        approval_callback=approval_callback,
        conversation_history=conversation_history,
        model=model,
    ):
        yield event

    logger.info("Agent stream completed (session=%s)", session_id)
