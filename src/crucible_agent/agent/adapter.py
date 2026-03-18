"""mcp-agent との結合層 — 外部依存はここに集約する

mcp-agent が破壊的変更を入れた場合、このファイルだけ差し替えれば済む設計。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

# 承認コールバック型: tool_call_id, tool_name, input → approved (True/False)
ApprovalCallback = Callable[[str, str, dict], asyncio.Future[bool]]

from mcp_agent.app import MCPApp
from mcp_agent.agents.agent import Agent
from mcp_agent.config import (
    MCPServerSettings,
    MCPSettings,
    OpenAISettings,
    Settings as MCPAgentSettings,
)
from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM

from crucible_agent.config import settings

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """ストリーミングイベント（WebSocket 経由でクライアントに送信する）"""

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


def _build_mcp_settings(server_configs: dict[str, MCPServerSettings] | None = None) -> MCPAgentSettings:
    """mcp-agent 用の Settings を組み立てる"""
    mcp = MCPSettings(servers=server_configs or {})
    openai = OpenAISettings(
        default_model=settings.llm_model,
        base_url=f"{settings.litellm_api_base}/v1",
        api_key=settings.litellm_api_key,
    )
    return MCPAgentSettings(
        execution_engine="asyncio",
        mcp=mcp,
        openai=openai,
    )


# アプリケーションレベルの MCPApp インスタンス
_mcp_app: MCPApp | None = None


def get_mcp_app(
    server_configs: dict[str, MCPServerSettings] | None = None,
) -> MCPApp:
    """MCPApp のシングルトンを取得（初回呼び出し時に生成）"""
    global _mcp_app
    if _mcp_app is None:
        mcp_settings = _build_mcp_settings(server_configs)
        _mcp_app = MCPApp(name="crucible_agent", settings=mcp_settings)
        logger.info("MCPApp initialized (model=%s, base_url=%s)", settings.llm_model, settings.litellm_api_base)
    return _mcp_app


async def run(
    instruction: str,
    message: str,
    server_names: list[str] | None = None,
) -> AdapterResult:
    """mcp-agent を使ってエージェントを1回実行する（同期版）"""
    mcp_app = get_mcp_app()

    tool_calls: list[dict] = []
    full_text = ""

    async with mcp_app.run():
        agent = Agent(
            name="crucible_assistant",
            instruction=instruction,
            server_names=server_names or [],
        )

        async with agent:
            llm = await agent.attach_llm(OpenAIAugmentedLLM)

            try:
                async for event in llm.generate_stream(message):
                    event_type = _get_event_type(event)
                    if event_type == "text_delta":
                        full_text += _get_event_content(event)
                    elif event_type == "tool_result":
                        tool_calls.append(_extract_tool_call(event))
            except (AttributeError, TypeError):
                # generate_stream が利用できない場合はフォールバック
                logger.info("generate_stream unavailable, falling back to generate_str")
                full_text = await llm.generate_str(message)

    return AdapterResult(
        message=full_text,
        tool_calls=tool_calls,
        token_usage={},
    )


async def run_stream(
    instruction: str,
    message: str,
    server_names: list[str] | None = None,
    require_approval: bool = False,
    approval_callback: ApprovalCallback | None = None,
) -> AsyncIterator[StreamEvent]:
    """mcp-agent を使ってエージェントを実行し、イベントをストリームする

    Args:
        require_approval: True の場合、ツール実行前に承認を求める
        approval_callback: 承認リクエスト時に呼ばれるコールバック。
                           Future[bool] を返し、ユーザーの応答を待つ。
    """
    mcp_app = get_mcp_app()

    async with mcp_app.run():
        agent = Agent(
            name="crucible_assistant",
            instruction=instruction,
            server_names=server_names or [],
        )

        async with agent:
            llm = await agent.attach_llm(OpenAIAugmentedLLM)

            tool_start_times: dict[str, float] = {}

            try:
                async for event in llm.generate_stream(message):
                    event_type = _get_event_type(event)

                    if event_type == "text_delta":
                        yield StreamEvent(
                            type="text_delta",
                            content=_get_event_content(event),
                        )

                    elif event_type == "tool_use_start":
                        tool_id = _get_tool_id(event)
                        tool_name = _get_tool_name(event)
                        tool_input = _get_tool_input(event)

                        # Plan モード: ツール実行前に承認を求める
                        if require_approval and approval_callback:
                            yield StreamEvent(
                                type="approval_request",
                                tool_call_id=tool_id,
                                tool_name=tool_name,
                                input=tool_input,
                                content=f"ツール '{tool_name}' を実行してよいですか？",
                            )
                            approved = await approval_callback(tool_id, tool_name, tool_input)
                            if not approved:
                                yield StreamEvent(
                                    type="tool_end",
                                    tool_call_id=tool_id,
                                    tool_name=tool_name,
                                    output={"rejected": True, "reason": "ユーザーが拒否しました"},
                                )
                                continue

                        tool_start_times[tool_id] = time.monotonic()
                        yield StreamEvent(
                            type="tool_start",
                            tool_call_id=tool_id,
                            tool_name=tool_name,
                            input=tool_input,
                        )

                    elif event_type == "tool_result":
                        tool_id = _get_tool_id(event)
                        start = tool_start_times.pop(tool_id, time.monotonic())
                        duration_ms = int((time.monotonic() - start) * 1000)
                        yield StreamEvent(
                            type="tool_end",
                            tool_call_id=tool_id,
                            tool_name=_get_tool_name(event),
                            output=_get_tool_output(event),
                            duration_ms=duration_ms,
                        )

                    elif event_type == "complete":
                        yield StreamEvent(
                            type="done",
                            token_usage=_get_token_usage(event),
                        )

                    elif event_type == "error":
                        yield StreamEvent(
                            type="error",
                            content=_get_event_content(event),
                        )

            except (AttributeError, TypeError):
                logger.info("generate_stream unavailable, falling back to generate_str")
                result = await llm.generate_str(message)
                yield StreamEvent(type="text_delta", content=result)
                yield StreamEvent(type="done")


# --- mcp-agent イベントからの値抽出ヘルパー ---
# mcp-agent の StreamEvent 構造が変わっても、ここだけ修正すれば済む


def _get_event_type(event: Any) -> str:
    """イベントタイプを文字列で取得"""
    t = getattr(event, "type", None)
    if t is None:
        return "unknown"
    # StreamEventType enum → 小文字文字列
    return str(t.value).lower() if hasattr(t, "value") else str(t).lower()


def _get_event_content(event: Any) -> str:
    return str(getattr(event, "content", "") or "")


def _get_tool_id(event: Any) -> str:
    meta = getattr(event, "metadata", {}) or {}
    return str(meta.get("tool_call_id", meta.get("id", "")))


def _get_tool_name(event: Any) -> str:
    meta = getattr(event, "metadata", {}) or {}
    return str(meta.get("tool_name", meta.get("name", "")))


def _get_tool_input(event: Any) -> dict:
    meta = getattr(event, "metadata", {}) or {}
    return dict(meta.get("input", meta.get("arguments", {})) or {})


def _get_tool_output(event: Any) -> dict:
    content = getattr(event, "content", None)
    if isinstance(content, dict):
        return content
    return {"result": str(content)} if content else {}


def _get_token_usage(event: Any) -> dict:
    usage = getattr(event, "usage", None)
    if usage and hasattr(usage, "input_tokens"):
        return {
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
    return {}


def _extract_tool_call(event: Any) -> dict:
    return {
        "tool_name": _get_tool_name(event),
        "input": _get_tool_input(event),
        "output": _get_tool_output(event),
    }
