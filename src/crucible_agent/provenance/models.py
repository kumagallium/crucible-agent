"""PROV-DM 来歴記録の SQLAlchemy モデル

PROV-DM (W3C Provenance Data Model) に基づき、エージェントの行動を記録する。
- Entity: データ（入力/出力）
- Activity: エージェントの行動（tool_use, LLM 呼び出し）
- Agent: 実行者（mcp-agent, MCP tool, ユーザー）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProvenanceAgent(Base):
    """prov:Agent — 実行者"""

    __tablename__ = "prov_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))  # "llm", "mcp_tool", "user"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ProvenanceActivity(Base):
    """prov:Activity — エージェントの行動"""

    __tablename__ = "prov_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    type: Mapped[str] = mapped_column(String(50))  # "agent_run", "tool_use", "llm_call"
    tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    server_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("prov_agents.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped[ProvenanceAgent | None] = relationship()


class ProvenanceEntity(Base):
    """prov:Entity — データ"""

    __tablename__ = "prov_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    type: Mapped[str] = mapped_column(String(50))  # "user_message", "agent_response", "tool_result"
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_by: Mapped[str | None] = mapped_column(ForeignKey("prov_activities.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    activity: Mapped[ProvenanceActivity | None] = relationship()
