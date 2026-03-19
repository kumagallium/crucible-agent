"""REST / WebSocket エンドポイント"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from crucible_agent import __version__
from crucible_agent.agent.runner import run_agent, run_agent_stream
from crucible_agent.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    BranchRequest,
    BranchResponse,
    EntityResponse,
    GraphResponse,
    HealthResponse,
    ProfileCreate,
    ProfileInfo,
    ProfileResponse,
    ProfilesResponse,
    ProfileUpdate,
    TokenUsage,
    ToolInfo,
    ToolSourceInfo,
    ToolsResponse,
)
from crucible_agent.config import settings
from crucible_agent.crucible.discovery import discover_servers
from crucible_agent.profiles.repository import (
    create_profile,
    delete_profile,
    get_profile,
    list_profiles,
    update_profile,
)
from crucible_agent.provenance.recorder import (
    get_conversation_history_until,
    get_entity,
    get_provenance_graph,
    get_session_history,
    list_sessions,
    record_agent_run,
    record_branch_run,
    record_revision,
)

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
async def profiles_list() -> ProfilesResponse:
    """プロファイル一覧を返す"""
    items = await list_profiles()
    return ProfilesResponse(profiles=[ProfileInfo.model_validate(p) for p in items])


@router.post("/profiles", response_model=ProfileResponse, status_code=201)
async def profiles_create(req: ProfileCreate) -> ProfileResponse:
    """プロファイルを作成する"""
    profile = await create_profile(
        name=req.name,
        description=req.description,
        content=req.content,
    )
    return _to_profile_response(profile)


@router.get("/profiles/{profile_id}", response_model=ProfileResponse)
async def profiles_get(profile_id: str) -> ProfileResponse:
    """プロファイル詳細を返す"""
    profile = await get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _to_profile_response(profile)


@router.put("/profiles/{profile_id}", response_model=ProfileResponse)
async def profiles_update(profile_id: str, req: ProfileUpdate) -> ProfileResponse:
    """プロファイルを更新する"""
    profile = await update_profile(
        profile_id=profile_id,
        name=req.name,
        description=req.description,
        content=req.content,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _to_profile_response(profile)


@router.delete("/profiles/{profile_id}", status_code=204)
async def profiles_delete(profile_id: str) -> None:
    """プロファイルを削除する"""
    deleted = await delete_profile(profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")


def _to_profile_response(profile) -> ProfileResponse:
    return ProfileResponse(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        content=profile.content,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


@router.post("/agent/run", response_model=AgentRunResponse)
async def agent_run(req: AgentRunRequest) -> AgentRunResponse:
    """エージェントを同期実行し結果を返す"""
    result = await run_agent(
        message=req.message,
        session_id=req.session_id,
        profile=req.profile,
        custom_instructions=req.custom_instructions,
        server_names=req.server_names,
        context_ids=req.context_ids or None,
    )

    # PROV-DM 来歴記録
    provenance_id = None
    try:
        run_result = await record_agent_run(
            session_id=result["session_id"],
            user_message=req.message,
            agent_response=result["message"],
            tool_calls=result.get("tool_calls", []),
            context_ids=result.get("context_ids") or None,
        )
        provenance_id = run_result["activity_id"]
    except Exception:
        logger.warning("Provenance recording failed", exc_info=True)

    return AgentRunResponse(
        session_id=result["session_id"],
        message=result["message"],
        tool_calls=[],
        provenance_id=provenance_id,
        token_usage=TokenUsage(**result.get("token_usage", {})),
    )


class _SessionTitleRequest(BaseModel):
    first_message: str


@router.post("/sessions/title")
async def generate_session_title(req: _SessionTitleRequest) -> dict:
    """最初のユーザーメッセージから AI セッションタイトルを生成する"""
    try:
        headers = {
            "Authorization": f"Bearer {settings.litellm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.llm_model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "次のメッセージを15文字以内の簡潔なタイトルにしてください。"
                        "タイトルのみを返してください。\n\n"
                        + req.first_message[:300]
                    ),
                }
            ],
            "max_tokens": 30,
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{settings.litellm_api_base}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            title = data["choices"][0]["message"]["content"].strip().strip('"\'「」')
            return {"title": title}
    except Exception:
        logger.warning("Title generation failed", exc_info=True)
        short = req.first_message.strip()[:25]
        return {"title": short + ("..." if len(req.first_message.strip()) > 25 else "")}


@router.get("/entities/{entity_id}", response_model=EntityResponse)
async def entity_get(entity_id: str) -> EntityResponse:
    """Entity を取得する（引用カード描画用）"""
    entity = await get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityResponse(
        id=entity.id,
        session_id=entity.session_id,
        type=entity.type,
        content=entity.content,
        created_at=entity.created_at.isoformat(),
    )


@router.post("/sessions/{session_id}/branch", response_model=BranchResponse)
async def session_branch(session_id: str, req: BranchRequest) -> BranchResponse:
    """セッションを指定 Entity で分岐し、新セッションでエージェントを実行する"""
    # 分岐元の履歴を分岐点 Entity まで取得
    history = await get_conversation_history_until(
        session_id=session_id,
        until_entity_id=req.branch_from_entity_id,
    )
    if not history:
        raise HTTPException(status_code=404, detail="Branch entity not found in session")

    branch_session_id = str(uuid.uuid4())

    # 履歴を instruction に追加して新セッションでエージェントを実行
    # history を「前の会話」として adapter に渡すため custom_instructions に埋め込む
    history_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in history
    )
    custom_instructions = f"## 引き継いだ会話履歴\n\n{history_text}"

    result = await run_agent(
        message=req.message,
        session_id=branch_session_id,
        profile=req.profile,
        custom_instructions=custom_instructions,
    )

    # PROV-DM 記録（wasDerivedFrom を含む）
    provenance_id = None
    try:
        branch_result = await record_branch_run(
            parent_session_id=session_id,
            branch_session_id=branch_session_id,
            branch_from_entity_id=req.branch_from_entity_id,
            user_message=req.message,
            agent_response=result["message"],
            tool_calls=result.get("tool_calls", []),
        )
        provenance_id = branch_result["activity_id"]
    except Exception:
        logger.warning("Branch provenance recording failed", exc_info=True)

    return BranchResponse(
        session_id=branch_session_id,
        branched_from_session_id=session_id,
        branched_from_entity_id=req.branch_from_entity_id,
        message=result["message"],
        provenance_id=provenance_id,
        token_usage=TokenUsage(**result.get("token_usage", {})),
    )


@router.get("/provenance")
async def provenance_sessions() -> list[dict]:
    """全セッション一覧を返す（最新順）"""
    return await list_sessions()


@router.get("/provenance/{session_id}", response_model=list[dict])
async def provenance_detail(session_id: str) -> list[dict]:
    """セッションの来歴（PROV-DM Activity チェーン）を返す"""
    return await get_session_history(session_id)


@router.get("/provenance/{session_id}/graph", response_model=GraphResponse)
async def provenance_graph(session_id: str) -> GraphResponse:
    """セッションの来歴グラフを返す（フロントエンド可視化用）

    クロスセッションの derivation エッジも含む。
    ノード: Entity / Activity / Agent
    エッジ: wasGeneratedBy / used / wasAssociatedWith / wasInfluencedBy / wasDerivedFrom
    """
    graph = await get_provenance_graph(session_id)
    return GraphResponse(nodes=graph["nodes"], edges=graph["edges"])


@router.websocket("/agent/ws")
async def agent_ws(websocket: WebSocket, session_id: str | None = None) -> None:
    """WebSocket でストリーミング応答を返す"""
    await websocket.accept()
    session_id = session_id or str(uuid.uuid4())

    # Plan モード用: tool_call_id → Future[bool]
    pending_approvals: dict[str, asyncio.Future[bool]] = {}
    # 受信メッセージキュー（ストリーム中も受信するため）
    incoming: asyncio.Queue[dict] = asyncio.Queue()

    async def approval_callback(tool_call_id: str, tool_name: str, tool_input: dict) -> bool:
        """ツール実行前にユーザーの承認を待つ"""
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()
        pending_approvals[tool_call_id] = future
        return await future

    async def receive_loop():
        """WebSocket からのメッセージを常時受信してキューに入れる"""
        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                # 承認応答は即座に処理
                if msg.get("type") == "approval":
                    tool_call_id = msg.get("tool_call_id", "")
                    approved = msg.get("approved", False)
                    future = pending_approvals.pop(tool_call_id, None)
                    if future and not future.done():
                        future.set_result(approved)
                else:
                    await incoming.put(msg)
        except WebSocketDisconnect:
            await incoming.put({"type": "_disconnect"})
        except Exception:
            await incoming.put({"type": "_disconnect"})

    # 受信ループをバックグラウンドタスクで起動
    receive_task = asyncio.create_task(receive_loop())

    try:
        while True:
            msg = await incoming.get()
            if msg.get("type") == "_disconnect":
                break

            if msg.get("type") == "message":
                content = msg.get("content", "")
                profile = msg.get("profile")
                custom_instructions = msg.get("custom_instructions")
                server_names = msg.get("server_names")
                require_approval = msg.get("require_approval", False)
                context_ids: list[str] = msg.get("context_ids") or []
                edit_from_entity_id: str | None = msg.get("edit_from_entity_id")

                # 編集モード: 指定 Entity 時点までの履歴のみ使用
                conversation_history: list[dict] | None = None
                if edit_from_entity_id:
                    conversation_history = await get_conversation_history_until(
                        session_id=session_id,
                        until_entity_id=edit_from_entity_id,
                    )

                # ストリーム中のテキストとツール呼び出しを収集
                collected_text = ""
                collected_tools: list[dict] = []

                async for event in run_agent_stream(
                    message=content,
                    session_id=session_id,
                    profile=profile,
                    custom_instructions=custom_instructions,
                    server_names=server_names,
                    context_ids=context_ids or None,
                    require_approval=require_approval,
                    approval_callback=approval_callback if require_approval else None,
                    conversation_history=conversation_history,
                ):
                    # 収集
                    if event.type == "text_delta":
                        collected_text += event.content
                    elif event.type == "tool_end" and not event.output.get("rejected"):
                        collected_tools.append({
                            "tool_name": event.tool_name,
                            "input": event.input,
                            "output": event.output,
                            "duration_ms": event.duration_ms,
                        })

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

                # PROV-DM 記録
                try:
                    ws_run_result = await record_agent_run(
                        session_id=session_id,
                        user_message=content,
                        agent_response=collected_text,
                        tool_calls=collected_tools,
                        context_ids=context_ids or None,
                        edit_from_entity_id=edit_from_entity_id,
                    )
                    # 編集モードの場合、wasRevisionOf を記録
                    if edit_from_entity_id:
                        await record_revision(
                            new_entity_id=ws_run_result["user_entity_id"],
                            original_entity_id=edit_from_entity_id,
                        )

                    # フロントエンドが entity_id を DOM に保存できるよう通知
                    await websocket.send_json({
                        "type": "entity_recorded",
                        "user_entity_id": ws_run_result["user_entity_id"],
                        "response_entity_id": ws_run_result["response_entity_id"],
                        "edit_from_entity_id": edit_from_entity_id,
                        "session_id": session_id,
                    })
                except Exception:
                    logger.warning("Provenance recording failed (WS)", exc_info=True)

    except Exception as e:
        logger.exception("WebSocket error (session=%s)", session_id)
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass
    finally:
        logger.info("WebSocket closed (session=%s)", session_id)
        for future in pending_approvals.values():
            if not future.done():
                future.set_result(False)
        receive_task.cancel()
