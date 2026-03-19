"""PROV-DM 来歴記録 — エージェント行動を DB に記録する"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crucible_agent.config import settings
from crucible_agent.provenance.models import (
    Base,
    ProvenanceActivity,
    ProvenanceAgent,
    ProvenanceDerivation,
    ProvenanceEntity,
    ProvenanceUsage,
)

logger = logging.getLogger(__name__)

# 非同期エンジン + セッション
_engine = create_async_engine(settings.database_url, echo=False)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db() -> None:
    """DB テーブルを作成する（Alembic 移行前の簡易版）"""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Provenance DB tables initialized")


async def record_agent_run(
    session_id: str,
    user_message: str,
    agent_response: str,
    tool_calls: list[dict],
    duration_ms: int = 0,
    llm_provider: str | None = None,
    llm_model_id: str | None = None,
    llm_model_version: str | None = None,
    context_ids: list[str] | None = None,
) -> str:
    """エージェント実行の来歴を記録する

    Args:
        llm_provider: LLM プロバイダー名 ("anthropic", "openai", "sakura" など)
        llm_model_id: LLM モデル ID ("claude-sonnet-4-6" など)
        llm_model_version: LLM モデルバージョン（省略可）
        context_ids: 手動引用した過去 Entity の ID リスト（wasInfluencedBy を記録）

    Returns:
        provenance_id: 記録した Activity の ID
    """
    async with _session_factory() as db:
        # Agent: LLM 実行者（provider/model_id を記録）
        llm_agent = ProvenanceAgent(
            name=llm_model_id or "llm",
            type="llm",
            provider=llm_provider,
            model_id=llm_model_id,
            model_version=llm_model_version,
        )
        db.add(llm_agent)
        await db.flush()  # llm_agent.id を確定させる

        # Activity: エージェント実行
        activity = ProvenanceActivity(
            session_id=session_id,
            type="agent_run",
            input_data={"message": user_message},
            output_data={"response": agent_response[:1000]},  # 長すぎる場合は切り詰め
            duration_ms=duration_ms,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            agent_id=llm_agent.id,
        )
        db.add(activity)
        await db.flush()  # activity.id を確定させる

        # Entity: ユーザー入力
        user_entity = ProvenanceEntity(
            session_id=session_id,
            type="user_message",
            content=user_message,
        )
        db.add(user_entity)
        await db.flush()  # user_entity.id を確定させる

        # prov:used — agent_run が user_message を入力として使った
        db.add(ProvenanceUsage(
            activity_id=activity.id,
            entity_id=user_entity.id,
            role="input",
        ))

        # Entity: エージェント応答
        response_entity = ProvenanceEntity(
            session_id=session_id,
            type="agent_response",
            content=agent_response[:5000],
            generated_by=activity.id,
        )
        db.add(response_entity)
        await db.flush()

        # prov:wasInfluencedBy — 手動引用した過去 Entity との関係を記録
        for source_id in (context_ids or []):
            db.add(ProvenanceDerivation(
                derived_entity_id=response_entity.id,
                source_entity_id=source_id,
                relation_type="wasInfluencedBy",
            ))

        # tool_use ごとに Activity + Entity を記録
        for tc in tool_calls:
            tool_agent = ProvenanceAgent(
                name=tc.get("tool_name", "unknown"),
                type="mcp_tool",
                server_name=tc.get("server_name"),
            )
            db.add(tool_agent)
            await db.flush()

            tool_activity = ProvenanceActivity(
                session_id=session_id,
                type="tool_use",
                tool_name=tc.get("tool_name", ""),
                server_name=tc.get("server_name"),
                input_data=tc.get("input", {}),
                output_data=tc.get("output", {}),
                duration_ms=tc.get("duration_ms", 0),
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                agent_id=tool_agent.id,
            )
            db.add(tool_activity)
            await db.flush()

            tool_result_entity = ProvenanceEntity(
                session_id=session_id,
                type="tool_result",
                content=str(tc.get("output", "")),
                metadata_json={"tool_name": tc.get("tool_name", "")},
                generated_by=tool_activity.id,
            )
            db.add(tool_result_entity)
            await db.flush()

            # prov:used — agent_run が tool_result を入力として使った
            db.add(ProvenanceUsage(
                activity_id=activity.id,
                entity_id=tool_result_entity.id,
                role="tool_result",
            ))

        await db.commit()
        logger.info("Provenance recorded (session=%s, activity=%s)", session_id, activity.id)
        return activity.id


async def list_sessions() -> list[dict]:
    """全セッション一覧を取得する（最新順）"""
    from sqlalchemy import func, select

    async with _session_factory() as db:
        result = await db.execute(
            select(
                ProvenanceActivity.session_id,
                func.min(ProvenanceActivity.started_at).label("first_at"),
                func.max(ProvenanceActivity.started_at).label("last_at"),
                func.count(ProvenanceActivity.id).label("count"),
            )
            .group_by(ProvenanceActivity.session_id)
            .order_by(func.max(ProvenanceActivity.started_at).desc())
            .limit(50)
        )
        rows = result.all()
        return [
            {
                "session_id": r.session_id,
                "first_at": r.first_at.isoformat() if r.first_at else None,
                "last_at": r.last_at.isoformat() if r.last_at else None,
                "activity_count": r.count,
            }
            for r in rows
        ]


async def get_conversation_history(session_id: str) -> list[dict]:
    """セッションの会話履歴を LLM messages 形式で返す（履歴復元用）"""
    from sqlalchemy import select

    async with _session_factory() as db:
        result = await db.execute(
            select(ProvenanceActivity)
            .where(ProvenanceActivity.session_id == session_id)
            .where(ProvenanceActivity.type == "agent_run")
            .order_by(ProvenanceActivity.started_at)
        )
        activities = result.scalars().all()
        messages = []
        for a in activities:
            user_msg = (a.input_data or {}).get("message", "")
            agent_resp = (a.output_data or {}).get("response", "")
            if user_msg:
                messages.append({"role": "user", "content": user_msg})
            if agent_resp:
                messages.append({"role": "assistant", "content": agent_resp})
        return messages


async def get_session_history(session_id: str) -> list[dict]:
    """セッションの来歴を取得する"""
    from sqlalchemy import select

    async with _session_factory() as db:
        result = await db.execute(
            select(ProvenanceActivity)
            .where(ProvenanceActivity.session_id == session_id)
            .order_by(ProvenanceActivity.started_at)
        )
        activities = result.scalars().all()
        return [
            {
                "id": a.id,
                "type": a.type,
                "tool_name": a.tool_name,
                "input": a.input_data,
                "output": a.output_data,
                "duration_ms": a.duration_ms,
                "started_at": a.started_at.isoformat() if a.started_at else None,
            }
            for a in activities
        ]


async def get_entity(entity_id: str) -> ProvenanceEntity | None:
    """Entity を ID で取得する（引用カード描画用）"""
    from sqlalchemy import select

    async with _session_factory() as db:
        result = await db.execute(
            select(ProvenanceEntity).where(ProvenanceEntity.id == entity_id)
        )
        return result.scalar_one_or_none()


async def get_conversation_history_until(
    session_id: str,
    until_entity_id: str,
) -> list[dict]:
    """セッションの会話履歴を指定 Entity まで取得する（ブランチ用）

    until_entity_id の agent_response が属する agent_run までを含める。
    """
    from sqlalchemy import select

    async with _session_factory() as db:
        # until_entity_id が含まれる Activity を特定
        entity_result = await db.execute(
            select(ProvenanceEntity).where(ProvenanceEntity.id == until_entity_id)
        )
        entity = entity_result.scalar_one_or_none()
        if entity is None:
            return []

        # entity.generated_by が分岐点の activity_id
        branch_activity_id = entity.generated_by

        # 全 agent_run を時系列で取得
        activities_result = await db.execute(
            select(ProvenanceActivity)
            .where(ProvenanceActivity.session_id == session_id)
            .where(ProvenanceActivity.type == "agent_run")
            .order_by(ProvenanceActivity.started_at)
        )
        activities = activities_result.scalars().all()

        messages = []
        for a in activities:
            user_msg = (a.input_data or {}).get("message", "")
            agent_resp = (a.output_data or {}).get("response", "")
            if user_msg:
                messages.append({"role": "user", "content": user_msg})
            if agent_resp:
                messages.append({"role": "assistant", "content": agent_resp})
            # 分岐点の Activity まで到達したら終了
            if a.id == branch_activity_id:
                break

        return messages


async def record_branch_run(
    parent_session_id: str,
    branch_session_id: str,
    branch_from_entity_id: str,
    user_message: str,
    agent_response: str,
    tool_calls: list[dict],
    duration_ms: int = 0,
    llm_provider: str | None = None,
    llm_model_id: str | None = None,
) -> str:
    """ブランチセッションの来歴を記録し、wasDerivedFrom を張る

    Returns:
        provenance_id: 記録した Activity の ID
    """
    # 通常の record_agent_run で記録（新セッション ID で）
    activity_id = await record_agent_run(
        session_id=branch_session_id,
        user_message=user_message,
        agent_response=agent_response,
        tool_calls=tool_calls,
        duration_ms=duration_ms,
        llm_provider=llm_provider,
        llm_model_id=llm_model_id,
    )

    # ブランチの agent_response Entity を取得して wasDerivedFrom を記録
    from sqlalchemy import select

    async with _session_factory() as db:
        result = await db.execute(
            select(ProvenanceEntity)
            .where(ProvenanceEntity.session_id == branch_session_id)
            .where(ProvenanceEntity.type == "agent_response")
            .order_by(ProvenanceEntity.created_at.desc())
            .limit(1)
        )
        branch_response_entity = result.scalar_one_or_none()

        if branch_response_entity:
            db.add(ProvenanceDerivation(
                derived_entity_id=branch_response_entity.id,
                source_entity_id=branch_from_entity_id,
                relation_type="wasDerivedFrom",
            ))
            await db.commit()
            logger.info(
                "Branch derivation recorded (parent=%s, branch=%s)",
                parent_session_id,
                branch_session_id,
            )

    return activity_id
