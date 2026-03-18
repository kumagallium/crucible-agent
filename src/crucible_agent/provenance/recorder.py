"""PROV-DM 来歴記録 — エージェント行動を DB に記録する"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from crucible_agent.config import settings
from crucible_agent.provenance.models import Base, ProvenanceActivity, ProvenanceEntity

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
) -> str:
    """エージェント実行の来歴を記録する

    Returns:
        provenance_id: 記録した Activity の ID
    """
    async with _session_factory() as db:
        # Activity: エージェント実行
        activity = ProvenanceActivity(
            session_id=session_id,
            type="agent_run",
            input_data={"message": user_message},
            output_data={"response": agent_response[:1000]},  # 長すぎる場合は切り詰め
            duration_ms=duration_ms,
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
        )
        db.add(activity)

        # Entity: ユーザー入力
        db.add(ProvenanceEntity(
            session_id=session_id,
            type="user_message",
            content=user_message,
        ))

        # Entity: エージェント応答
        db.add(ProvenanceEntity(
            session_id=session_id,
            type="agent_response",
            content=agent_response[:5000],
            generated_by=activity.id,
        ))

        # tool_use ごとに Activity + Entity を記録
        for tc in tool_calls:
            tool_activity = ProvenanceActivity(
                session_id=session_id,
                type="tool_use",
                tool_name=tc.get("tool_name", ""),
                input_data=tc.get("input", {}),
                output_data=tc.get("output", {}),
                duration_ms=tc.get("duration_ms", 0),
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
            )
            db.add(tool_activity)

            db.add(ProvenanceEntity(
                session_id=session_id,
                type="tool_result",
                content=str(tc.get("output", "")),
                metadata_json={"tool_name": tc.get("tool_name", "")},
                generated_by=tool_activity.id,
            ))

        await db.commit()
        logger.info("Provenance recorded (session=%s, activity=%s)", session_id, activity.id)
        return activity.id


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
