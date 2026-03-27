"""Provenance モデル・レコーダーのユニットテスト（モックベース）

モデル構造テスト + recorder の呼び出しパターンテスト。
実 DB を使ったテストは tests/provenance/ で行う。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crucible_agent.provenance.models import (
    ProvenanceActivity,
    ProvenanceAgent,
    ProvenanceEntity,
    ProvenanceUsage,
)
from crucible_agent.provenance.recorder import get_session_history, record_agent_run


class TestProvenanceAgentModel:
    def test_table_name(self):
        assert ProvenanceAgent.__tablename__ == "prov_agents"

    def test_columns(self):
        col_names = {c.name for c in ProvenanceAgent.__table__.columns}
        assert {"id", "name", "type", "created_at"} <= col_names

    def test_extended_columns(self):
        """マイグレーション 38c468927df5 で追加されたカラムが存在する"""
        col_names = {c.name for c in ProvenanceAgent.__table__.columns}
        assert {"provider", "model_id", "model_version", "server_name", "external_id"} <= col_names


class TestProvenanceActivityModel:
    def test_table_name(self):
        assert ProvenanceActivity.__tablename__ == "prov_activities"

    def test_columns(self):
        col_names = {c.name for c in ProvenanceActivity.__table__.columns}
        expected = {
            "id", "session_id", "type", "tool_name", "server_name",
            "input_data", "output_data", "duration_ms", "agent_id",
            "started_at", "ended_at",
        }
        assert expected <= col_names

    def test_foreign_key(self):
        fk_columns = [
            fk.target_fullname
            for col in ProvenanceActivity.__table__.columns
            for fk in col.foreign_keys
        ]
        assert "prov_agents.id" in fk_columns


class TestProvenanceEntityModel:
    def test_table_name(self):
        assert ProvenanceEntity.__tablename__ == "prov_entities"

    def test_columns(self):
        col_names = {c.name for c in ProvenanceEntity.__table__.columns}
        expected = {
            "id", "session_id", "type", "content",
            "metadata_json", "generated_by", "created_at",
        }
        assert expected <= col_names

    def test_foreign_key(self):
        fk_columns = [
            fk.target_fullname
            for col in ProvenanceEntity.__table__.columns
            for fk in col.foreign_keys
        ]
        assert "prov_activities.id" in fk_columns


class TestProvenanceUsageModel:
    def test_table_name(self):
        assert ProvenanceUsage.__tablename__ == "prov_usage"

    def test_foreign_keys(self):
        fk_targets = {
            fk.target_fullname
            for col in ProvenanceUsage.__table__.columns
            for fk in col.foreign_keys
        }
        assert "prov_activities.id" in fk_targets
        assert "prov_entities.id" in fk_targets


def _make_mock_session():
    """recorder の _session_factory をモック化するヘルパー"""
    mock_session = AsyncMock()
    # flush() 後にモデルの .id が参照されるため、add() のたびに id をセット
    _id_counter = [0]

    def _add_side_effect(obj):
        _id_counter[0] += 1
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = f"mock-id-{_id_counter[0]}"

    mock_session.add.side_effect = _add_side_effect
    mock_session.flush = AsyncMock()  # flush は no-op
    mock_session.commit = AsyncMock()
    # execute() は空のクエリ結果を返す
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_factory, mock_session


class TestRecordAgentRun:
    async def test_creates_activity_and_entities(self):
        mock_factory, mock_session = _make_mock_session()

        with patch("crucible_agent.provenance.recorder._session_factory", mock_factory):
            result = await record_agent_run(
                session_id="sess-1",
                user_message="hello",
                agent_response="world",
                tool_calls=[],
                duration_ms=100,
            )

        assert result is not None
        assert "activity_id" in result
        assert "response_entity_id" in result
        # Agent + Activity + user_entity + Usage + response_entity = 5 add()
        assert mock_session.add.call_count == 5
        mock_session.commit.assert_awaited_once()

    async def test_creates_tool_entities(self):
        mock_factory, mock_session = _make_mock_session()

        tool_calls = [
            {"tool_name": "search", "input": {"q": "test"}, "output": {"result": "ok"}, "duration_ms": 50},
        ]

        with patch("crucible_agent.provenance.recorder._session_factory", mock_factory):
            await record_agent_run(
                session_id="sess-2",
                user_message="hi",
                agent_response="result",
                tool_calls=tool_calls,
            )

        # Agent + Activity + user_entity + Usage + response_entity
        # + tool_agent + tool_activity + tool_result_entity + tool_usage = 9
        assert mock_session.add.call_count == 9

    async def test_truncates_long_content(self):
        mock_factory, mock_session = _make_mock_session()
        long_response = "x" * 10000

        with patch("crucible_agent.provenance.recorder._session_factory", mock_factory):
            await record_agent_run(
                session_id="sess-3",
                user_message="hi",
                agent_response=long_response,
                tool_calls=[],
            )

        # Activity の output_data["response"] が 1000 文字以下
        calls = mock_session.add.call_args_list
        activity = calls[1].args[0]  # 0=Agent, 1=Activity
        assert isinstance(activity, ProvenanceActivity)
        assert len(activity.output_data["response"]) <= 1000

        # response_entity の content が 5000 文字以下
        response_entity = calls[4].args[0]  # 4=response_entity
        assert isinstance(response_entity, ProvenanceEntity)
        assert len(response_entity.content) <= 5000

    async def test_records_llm_provider_info(self):
        mock_factory, mock_session = _make_mock_session()

        with patch("crucible_agent.provenance.recorder._session_factory", mock_factory):
            await record_agent_run(
                session_id="sess-4",
                user_message="test",
                agent_response="response",
                tool_calls=[],
                llm_provider="anthropic",
                llm_model_id="claude-sonnet-4-6",
                llm_model_version="20260301",
            )

        # 最初の add() は Agent
        agent = mock_session.add.call_args_list[0].args[0]
        assert isinstance(agent, ProvenanceAgent)
        assert agent.provider == "anthropic"
        assert agent.model_id == "claude-sonnet-4-6"
        assert agent.model_version == "20260301"


class TestGetSessionHistory:
    async def test_returns_ordered_activities(self):
        mock_activity_1 = MagicMock()
        mock_activity_1.id = "a1"
        mock_activity_1.type = "agent_run"
        mock_activity_1.tool_name = None
        mock_activity_1.input_data = {"message": "hi"}
        mock_activity_1.output_data = {"response": "hello"}
        mock_activity_1.duration_ms = 100
        mock_activity_1.started_at = MagicMock()
        mock_activity_1.started_at.isoformat.return_value = "2025-01-01T00:00:00+00:00"

        mock_activity_2 = MagicMock()
        mock_activity_2.id = "a2"
        mock_activity_2.type = "tool_use"
        mock_activity_2.tool_name = "search"
        mock_activity_2.input_data = {"q": "test"}
        mock_activity_2.output_data = {"result": "found"}
        mock_activity_2.duration_ms = 50
        mock_activity_2.started_at = MagicMock()
        mock_activity_2.started_at.isoformat.return_value = "2025-01-01T00:00:01+00:00"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_activity_1, mock_activity_2]

        # entity/usage クエリ用のモック
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        call_count = [0]

        def _execute_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_result  # activities
            return empty_result  # entities/usages/derivations

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.provenance.recorder._session_factory", mock_factory):
            history = await get_session_history("sess-1")

        assert len(history) == 2
        assert history[0]["id"] == "a1"
        assert history[0]["type"] == "agent_run"
        assert history[1]["id"] == "a2"
        assert history[1]["type"] == "tool_use"
        assert history[1]["tool_name"] == "search"
