"""MCP SDK + httpx による直接実装 — mcp-agent を使わない adapter

mcp-agent の OpenAI SDK バリデーション問題を回避するため、
MCP Python SDK と httpx で tool_use ループを自前実装する。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client

from crucible_agent.config import settings

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crucible_agent.crucible.discovery import DiscoveredServer

logger = logging.getLogger(__name__)

# 承認コールバック型
ApprovalCallback = Callable[[str, str, dict], asyncio.Future[bool]]


@dataclass
class StreamEvent:
    """ストリーミングイベント"""

    type: str  # text_delta, tool_start, tool_end, approval_request, done, error
    content: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    server: str = ""
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    duration_ms: int = 0
    token_usage: dict = field(default_factory=dict)


@dataclass
class AdapterResult:
    """adapter の実行結果"""

    message: str
    tool_calls: list[dict]
    token_usage: dict


# --- MCP サーバー接続 ---


async def _connect_mcp_server(
    name: str, url: str
) -> tuple[ClientSession, Any, Any]:
    """MCP サーバーに SSE 接続してセッションを返す"""
    read_stream, write_stream = await sse_client(url).__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()
    logger.info("MCP connected: %s (%s)", name, url)
    return session, read_stream, write_stream


async def _get_tools_from_servers(
    servers: list[DiscoveredServer],
) -> tuple[dict[str, ClientSession], list[dict]]:
    """全 MCP サーバーに接続し、ツール定義を収集する

    Returns:
        (sessions: {tool_name: session}, tools: OpenAI function 形式のリスト)
    """
    sessions: dict[str, ClientSession] = {}
    tools: list[dict] = []
    tool_to_server: dict[str, str] = {}

    for s in servers:
        try:
            session, _, _ = await _connect_mcp_server(s.name, s.url)
            result = await session.list_tools()
            for tool in result.tools:
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                    },
                }
                tools.append(tool_def)
                sessions[tool.name] = session
                tool_to_server[tool.name] = s.name
            logger.info("  %s: %d tools loaded", s.name, len(result.tools))
        except Exception as e:
            logger.warning("MCP server '%s' connection failed: %s", s.name, e)

    return sessions, tools


async def _call_tool(
    sessions: dict[str, ClientSession],
    tool_name: str,
    arguments: dict,
) -> str:
    """MCP サーバー上のツールを呼び出す"""
    session = sessions.get(tool_name)
    if not session:
        return json.dumps({"error": f"Tool '{tool_name}' not found in connected servers"})

    try:
        result = await session.call_tool(tool_name, arguments)
        # MCP の content は配列形式 → 文字列に変換
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)
    except Exception as e:
        logger.error("Tool call failed: %s - %s", tool_name, e)
        return json.dumps({"error": str(e)})


# --- LLM 呼び出し ---


async def _call_llm(
    messages: list[dict],
    tools: list[dict] | None = None,
) -> dict:
    """LiteLLM Proxy に chat completions リクエストを送る"""
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.litellm_api_key}",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.litellm_api_base}/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


# --- tool_use ループ ---


async def run(
    instruction: str,
    message: str,
    server_names: list[str] | None = None,
    discovered_servers: list[DiscoveredServer] | None = None,
    max_turns: int = 10,
) -> AdapterResult:
    """エージェントを実行する（同期版）"""
    servers = discovered_servers or []

    # MCP サーバーに接続してツール定義を取得
    sessions, tools = await _get_tools_from_servers(servers)

    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": message},
    ]

    tool_calls_log: list[dict] = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    try:
        for turn in range(max_turns):
            resp = await _call_llm(messages, tools if tools else None)

            # トークン使用量を加算
            usage = resp.get("usage", {})
            total_usage["input_tokens"] += usage.get("prompt_tokens", 0)
            total_usage["output_tokens"] += usage.get("completion_tokens", 0)
            total_usage["total_tokens"] += usage.get("total_tokens", 0)

            choice = resp["choices"][0]
            msg = choice["message"]

            # tool_calls があれば実行
            if msg.get("tool_calls"):
                # アシスタントメッセージを履歴に追加
                messages.append(msg)

                for tc in msg["tool_calls"]:
                    func = tc["function"]
                    tool_name = func["name"]
                    arguments = json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"]

                    logger.info("Tool call: %s(%s)", tool_name, json.dumps(arguments, ensure_ascii=False)[:200])

                    start = time.monotonic()
                    result_str = await _call_tool(sessions, tool_name, arguments)
                    duration_ms = int((time.monotonic() - start) * 1000)

                    # ツール結果を文字列としてメッセージに追加
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

                    tool_calls_log.append({
                        "tool_name": tool_name,
                        "input": arguments,
                        "output": result_str[:1000],
                        "duration_ms": duration_ms,
                    })

                # 次のターンへ（LLM にツール結果をフィードバック）
                continue

            # テキスト応答のみ → 完了
            return AdapterResult(
                message=msg.get("content", ""),
                tool_calls=tool_calls_log,
                token_usage=total_usage,
            )

        # max_turns に到達
        return AdapterResult(
            message="(最大ループ回数に到達しました)",
            tool_calls=tool_calls_log,
            token_usage=total_usage,
        )
    finally:
        # MCP セッションをクリーンアップ
        for session in set(sessions.values()):
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass


async def run_stream(
    instruction: str,
    message: str,
    server_names: list[str] | None = None,
    discovered_servers: list[DiscoveredServer] | None = None,
    require_approval: bool = False,
    approval_callback: ApprovalCallback | None = None,
    max_turns: int = 10,
) -> AsyncIterator[StreamEvent]:
    """エージェントを実行し、イベントをストリームする"""
    servers = discovered_servers or []

    sessions, tools = await _get_tools_from_servers(servers)

    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": message},
    ]

    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    try:
        for turn in range(max_turns):
            resp = await _call_llm(messages, tools if tools else None)

            usage = resp.get("usage", {})
            total_usage["input_tokens"] += usage.get("prompt_tokens", 0)
            total_usage["output_tokens"] += usage.get("completion_tokens", 0)
            total_usage["total_tokens"] += usage.get("total_tokens", 0)

            choice = resp["choices"][0]
            msg = choice["message"]

            if msg.get("tool_calls"):
                messages.append(msg)

                for tc in msg["tool_calls"]:
                    func = tc["function"]
                    tool_name = func["name"]
                    tool_call_id = tc["id"]
                    arguments = json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"]

                    # Plan モード: 承認を求める
                    if require_approval and approval_callback:
                        yield StreamEvent(
                            type="approval_request",
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            input=arguments,
                            content=f"ツール '{tool_name}' を実行してよいですか？",
                        )
                        approved = await approval_callback(tool_call_id, tool_name, arguments)
                        if not approved:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": "ユーザーがツール実行を拒否しました。",
                            })
                            yield StreamEvent(
                                type="tool_end",
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                output={"rejected": True},
                            )
                            continue

                    yield StreamEvent(
                        type="tool_start",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        input=arguments,
                    )

                    start = time.monotonic()
                    result_str = await _call_tool(sessions, tool_name, arguments)
                    duration_ms = int((time.monotonic() - start) * 1000)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result_str,
                    })

                    yield StreamEvent(
                        type="tool_end",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        output={"result": result_str[:500]},
                        duration_ms=duration_ms,
                    )

                continue

            # テキスト応答
            content = msg.get("content", "")
            if content:
                yield StreamEvent(type="text_delta", content=content)

            yield StreamEvent(type="done", token_usage=total_usage)
            return

        yield StreamEvent(type="done", token_usage=total_usage)
    except Exception as e:
        logger.exception("Agent stream error")
        yield StreamEvent(type="error", content=str(e))
    finally:
        for session in set(sessions.values()):
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
