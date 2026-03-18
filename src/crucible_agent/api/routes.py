"""REST エンドポイント — GET /health, GET /tools, POST /agent/run"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter

from crucible_agent import __version__
from crucible_agent.agent.runner import run_agent
from crucible_agent.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    HealthResponse,
    TokenUsage,
    ToolInfo,
    ToolSourceInfo,
    ToolsResponse,
)
from crucible_agent.config import settings
from crucible_agent.crucible.discovery import discover_servers

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """ヘルスチェック — 各コンポーネントの状態を返す"""
    components: dict[str, str] = {"agent": "ok"}

    # LiteLLM Proxy の疎通確認
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.litellm_api_base}/health")
            components["litellm"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        components["litellm"] = "unavailable"

    # Crucible Registry の疎通確認
    if settings.crucible_api_url:
        try:
            headers: dict[str, str] = {}
            if settings.crucible_api_key:
                headers["X-API-Key"] = settings.crucible_api_key
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{settings.crucible_api_url}/health", headers=headers)
                components["crucible"] = "ok" if resp.status_code == 200 else "degraded"
        except Exception:
            components["crucible"] = "unavailable"

    status = "healthy" if all(v == "ok" for v in components.values()) else "degraded"

    return HealthResponse(status=status, components=components, version=__version__)


@router.get("/tools", response_model=ToolsResponse)
async def tools() -> ToolsResponse:
    """Crucible から検出した利用可能ツール一覧を返す"""
    servers = await discover_servers()

    tool_list = [
        ToolInfo(
            name=s.name,
            display_name=s.display_name,
            description=s.description,
            url=s.url,
            transport=s.transport,
            status=s.status,
        )
        for s in servers
    ]

    sources: dict[str, ToolSourceInfo] = {}
    if settings.crucible_api_url:
        sources["crucible"] = ToolSourceInfo(
            url=settings.crucible_api_url,
            status="connected" if servers else "no_servers",
            server_count=len(servers),
        )

    return ToolsResponse(tools=tool_list, sources=sources)


@router.post("/agent/run", response_model=AgentRunResponse)
async def agent_run(req: AgentRunRequest) -> AgentRunResponse:
    """エージェントを同期実行し結果を返す"""
    result = await run_agent(
        message=req.message,
        session_id=req.session_id,
    )

    return AgentRunResponse(
        session_id=result["session_id"],
        message=result["message"],
        tool_calls=[],  # Phase 3 で実装
        token_usage=TokenUsage(**result.get("token_usage", {})),
    )
