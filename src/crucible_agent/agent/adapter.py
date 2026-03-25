"""MCP SDK + httpx による直接実装

MCP Python SDK と httpx で tool_use ループを自前実装する。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

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


async def _connect_servers(
    servers: list[DiscoveredServer],
    exit_stack: AsyncExitStack,
) -> tuple[dict[str, ClientSession], list[dict]]:
    """全 MCP サーバーに接続し、ツール定義を収集する

    AsyncExitStack で接続のライフサイクルを管理する。
    """
    sessions: dict[str, ClientSession] = {}
    tools: list[dict] = []

    for s in servers:
        try:
            # トランスポートに応じてクライアントを切り替え
            if s.transport == "streamable-http":
                read_stream, write_stream, _ = await exit_stack.enter_async_context(
                    streamable_http_client(s.url)
                )
            else:
                read_stream, write_stream = await exit_stack.enter_async_context(sse_client(s.url))
            session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            logger.info("MCP connected: %s (%s)", s.name, s.url)

            result = await session.list_tools()
            for tool in result.tools:
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                    },
                }
                tools.append(tool_def)
                sessions[tool.name] = session
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
        return json.dumps({"error": f"Tool '{tool_name}' not found"})

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


class LLMError(Exception):
    """LLM API 呼び出しの基底エラー"""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMTimeoutError(LLMError):
    """LLM API タイムアウト"""

    def __init__(self, message: str = "LLM API がタイムアウトしました"):
        super().__init__(message, retryable=True)


class LLMRateLimitError(LLMError):
    """レートリミット超過"""

    def __init__(self, message: str = "LLM API のレートリミットに達しました"):
        super().__init__(message, retryable=True)


class LLMContextOverflowError(LLMError):
    """コンテキスト長超過"""

    def __init__(self, message: str = "コンテキスト長の上限を超えました"):
        super().__init__(message, retryable=False)


def _classify_llm_error(e: Exception) -> LLMError:
    """httpx エラーを分類して適切な LLMError に変換する"""
    if isinstance(e, httpx.TimeoutException):
        return LLMTimeoutError()
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        body = e.response.text
        if status == 429:
            return LLMRateLimitError()
        if status == 400 and "context" in body.lower():
            return LLMContextOverflowError()
        if status >= 500:
            return LLMError(f"LLM API サーバーエラー (HTTP {status})", retryable=True)
        return LLMError(f"LLM API エラー (HTTP {status}): {body[:200]}", retryable=False)
    return LLMError(f"LLM API 通信エラー: {e}", retryable=True)


async def _call_llm(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
) -> dict:
    """LiteLLM Proxy に chat completions リクエストを送る（リトライ付き）"""
    payload: dict[str, Any] = {
        "model": model or settings.llm_model,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.litellm_api_key}",
    }

    last_error: LLMError | None = None

    for attempt in range(settings.llm_max_retries):
        try:
            async with httpx.AsyncClient(timeout=float(settings.llm_timeout)) as client:
                resp = await client.post(
                    f"{settings.litellm_api_base}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            last_error = _classify_llm_error(e)
            if not last_error.retryable or attempt == settings.llm_max_retries - 1:
                raise last_error from e
            delay = settings.llm_retry_base_delay * (2**attempt)
            logger.warning(
                "LLM API リトライ (%d/%d): %s — %.1f秒後に再試行",
                attempt + 1,
                settings.llm_max_retries,
                last_error,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]


# --- コンテキスト管理 ---


def _truncate_history(history: list[dict], max_messages: int) -> list[dict]:
    """会話履歴が上限を超えた場合、古いメッセージを削除する

    - tool ロールのメッセージは対応する assistant (tool_calls) と一緒に削除
    - 直近のメッセージを優先的に残す
    """
    if len(history) <= max_messages:
        return history

    # 古い方から削除して上限に収める
    truncated = history[-max_messages:]

    # 先頭が tool ロールの場合、対応する assistant が切れているので削除
    while truncated and truncated[0].get("role") == "tool":
        truncated = truncated[1:]

    logger.info(
        "会話履歴を圧縮: %d → %d メッセージ",
        len(history),
        len(truncated),
    )
    return truncated


# --- tool_use ループ ---


async def run(
    instruction: str,
    message: str,
    server_names: list[str] | None = None,
    discovered_servers: list[DiscoveredServer] | None = None,
    session_id: str | None = None,
    max_turns: int = 10,
    model: str | None = None,
) -> AdapterResult:
    """エージェントを実行する（同期版）"""
    servers = discovered_servers or []

    async with AsyncExitStack() as stack:
        sessions, tools = await _connect_servers(servers, stack)

        # 過去の会話履歴を復元
        history: list[dict] = []
        if session_id:
            from crucible_agent.provenance.recorder import get_conversation_history

            try:
                history = await get_conversation_history(session_id)
            except Exception:
                logger.warning("会話履歴の読み込みに失敗しました (session=%s)", session_id)

        history = _truncate_history(history, settings.llm_max_context_messages)
        messages = [
            {"role": "system", "content": instruction},
            *history,
            {"role": "user", "content": message},
        ]

        tool_calls_log: list[dict] = []
        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        for turn in range(max_turns):
            resp = await _call_llm(messages, tools if tools else None, model=model)

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
                    arguments = (
                        json.loads(func["arguments"])
                        if isinstance(func["arguments"], str)
                        else func["arguments"]
                    )

                    logger.info(
                        "Tool call: %s(%s)",
                        tool_name,
                        json.dumps(arguments, ensure_ascii=False)[:200],
                    )

                    start = time.monotonic()
                    result_str = await _call_tool(sessions, tool_name, arguments)
                    duration_ms = int((time.monotonic() - start) * 1000)

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_str,
                        }
                    )

                    tool_calls_log.append(
                        {
                            "tool_name": tool_name,
                            "input": arguments,
                            "output": result_str[:1000],
                            "duration_ms": duration_ms,
                        }
                    )

                continue

            return AdapterResult(
                message=msg.get("content", ""),
                tool_calls=tool_calls_log,
                token_usage=total_usage,
            )

        return AdapterResult(
            message="(最大ループ回数に到達しました)",
            tool_calls=tool_calls_log,
            token_usage=total_usage,
        )


async def run_stream(
    instruction: str,
    message: str,
    server_names: list[str] | None = None,
    discovered_servers: list[DiscoveredServer] | None = None,
    session_id: str | None = None,
    require_approval: bool = False,
    approval_callback: ApprovalCallback | None = None,
    max_turns: int = 10,
    conversation_history: list[dict] | None = None,
    model: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """エージェントを実行し、イベントをストリームする

    Args:
        conversation_history: 明示的な会話履歴（指定時は DB からの復元をスキップ）
    """
    servers = discovered_servers or []

    async with AsyncExitStack() as stack:
        sessions, tools = await _connect_servers(servers, stack)

        # 過去の会話履歴を復元（明示的に渡された場合はそれを使用）
        if conversation_history is not None:
            history = conversation_history
        else:
            history = []
            if session_id:
                from crucible_agent.provenance.recorder import (
                    get_conversation_history,
                )

                try:
                    history = await get_conversation_history(session_id)
                except Exception:
                    logger.warning(
                        "会話履歴の読み込みに失敗しました (session=%s)",
                        session_id,
                    )

        history = _truncate_history(history, settings.llm_max_context_messages)
        messages = [
            {"role": "system", "content": instruction},
            *history,
            {"role": "user", "content": message},
        ]

        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        try:
            for turn in range(max_turns):
                resp = await _call_llm(messages, tools if tools else None, model=model)

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
                        arguments = (
                            json.loads(func["arguments"])
                            if isinstance(func["arguments"], str)
                            else func["arguments"]
                        )

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
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "content": "ユーザーがツール実行を拒否しました。",
                                    }
                                )
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

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": result_str,
                            }
                        )

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
        except LLMContextOverflowError as e:
            logger.warning("コンテキスト長超過: %s", e)
            yield StreamEvent(
                type="error",
                content="会話が長くなりすぎました。新しいセッションを開始してください。",
            )
        except LLMRateLimitError as e:
            logger.warning("レートリミット: %s", e)
            yield StreamEvent(
                type="error",
                content="API のリクエスト制限に達しました。しばらく待ってから再試行してください。",
            )
        except LLMTimeoutError as e:
            logger.warning("LLM タイムアウト: %s", e)
            yield StreamEvent(
                type="error",
                content="AI の応答がタイムアウトしました。もう一度お試しください。",
            )
        except LLMError as e:
            logger.exception("LLM エラー: %s", e)
            yield StreamEvent(type="error", content=str(e))
        except Exception as e:
            logger.exception("Agent stream error")
            yield StreamEvent(type="error", content=f"予期しないエラーが発生しました: {e}")
