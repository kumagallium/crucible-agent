"""REST / WebSocket エンドポイント"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from crucible_agent import __version__
from crucible_agent.agent.runner import run_agent, run_agent_stream
from crucible_agent.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    HealthResponse,
    ProfileInfo,
    ProfilesResponse,
    TokenUsage,
    ToolInfo,
    ToolSourceInfo,
    ToolsResponse,
)
from crucible_agent.config import settings
from crucible_agent.crucible.discovery import discover_servers
from crucible_agent.prompts.loader import list_profiles
from crucible_agent.provenance.recorder import record_agent_run

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """ヘルスチェック — 各コンポーネントの状態を返す"""
    components: dict[str, str] = {"agent": "ok"}

    # LiteLLM Proxy の疎通確認
    try:
        litellm_headers = {"Authorization": f"Bearer {settings.litellm_api_key}"}
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.litellm_api_base}/health", headers=litellm_headers)
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


@router.get("/profiles", response_model=ProfilesResponse)
async def profiles() -> ProfilesResponse:
    """利用可能なプロンプトプロファイル一覧を返す"""
    return ProfilesResponse(
        profiles=[ProfileInfo(name=p) for p in list_profiles()]
    )


@router.post("/agent/run", response_model=AgentRunResponse)
async def agent_run(req: AgentRunRequest) -> AgentRunResponse:
    """エージェントを同期実行し結果を返す"""
    result = await run_agent(
        message=req.message,
        session_id=req.session_id,
        profile=req.profile,
        custom_instructions=req.custom_instructions,
    )

    # PROV-DM 来歴記録
    provenance_id = None
    try:
        provenance_id = await record_agent_run(
            session_id=result["session_id"],
            user_message=req.message,
            agent_response=result["message"],
            tool_calls=result.get("tool_calls", []),
        )
    except Exception:
        logger.warning("Provenance recording failed", exc_info=True)

    return AgentRunResponse(
        session_id=result["session_id"],
        message=result["message"],
        tool_calls=[],
        provenance_id=provenance_id,
        token_usage=TokenUsage(**result.get("token_usage", {})),
    )


@router.websocket("/agent/ws")
async def agent_ws(websocket: WebSocket, session_id: str | None = None) -> None:
    """WebSocket でストリーミング応答を返す"""
    await websocket.accept()
    session_id = session_id or str(uuid.uuid4())

    # Plan モード用: tool_call_id → Future[bool] のマップ
    pending_approvals: dict[str, asyncio.Future[bool]] = {}

    async def approval_callback(tool_call_id: str, tool_name: str, tool_input: dict) -> bool:
        """ツール実行前にユーザーの承認を待つ"""
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()
        pending_approvals[tool_call_id] = future
        # approval_request は adapter 側から yield される
        # ユーザーからの approval メッセージを待つ
        return await future

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            # Plan モード: 承認応答
            if msg.get("type") == "approval":
                tool_call_id = msg.get("tool_call_id", "")
                approved = msg.get("approved", False)
                future = pending_approvals.pop(tool_call_id, None)
                if future and not future.done():
                    future.set_result(approved)
                continue

            if msg.get("type") == "message":
                content = msg.get("content", "")
                profile = msg.get("profile")
                custom_instructions = msg.get("custom_instructions")
                server_names = msg.get("server_names")
                require_approval = msg.get("require_approval", False)

                async for event in run_agent_stream(
                    message=content,
                    session_id=session_id,
                    profile=profile,
                    custom_instructions=custom_instructions,
                    server_names=server_names,
                    require_approval=require_approval,
                    approval_callback=approval_callback if require_approval else None,
                ):
                    await websocket.send_json({
                        "type": event.type,
                        "content": event.content,
                        "tool_call_id": event.tool_call_id,
                        "tool_name": event.tool_name,
                        "input": event.input,
                        "output": event.output,
                        "duration_ms": event.duration_ms,
                        "token_usage": event.token_usage,
                    })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected (session=%s)", session_id)
        # 未処理の承認をキャンセル
        for future in pending_approvals.values():
            if not future.done():
                future.set_result(False)
    except Exception as e:
        logger.exception("WebSocket error (session=%s)", session_id)
        for future in pending_approvals.values():
            if not future.done():
                future.set_result(False)
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass
