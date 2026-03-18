import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# SQLAlchemy モデルの型ヒント (str | None) は Python 3.10+ が必要
# conftest.py でモックされている場合もあるため、実際の SQLAlchemy クラスかどうか確認
_models_available = False
_recorder_available = False

try:
    from crucible_agent.provenance.models import ProvenanceActivity, ProvenanceAgent, ProvenanceEntity
    if hasattr(ProvenanceAgent, "__tablename__"):
        _models_available = True
except Exception:
    pass

try:
    from crucible_agent.provenance.recorder import record_agent_run, get_session_history
    if callable(record_agent_run) and not isinstance(record_agent_run, MagicMock):
        _recorder_available = True
except Exception:
    pass

skip_if_no_models = pytest.mark.skipif(
    not _models_available,
    reason="SQLAlchemy models require Python 3.10+ (str | None syntax)"
)

skip_if_no_recorder = pytest.mark.skipif(
    not _recorder_available,
    reason="Provenance recorder requires Python 3.10+ (depends on models)"
)


@skip_if_no_models
class TestProvenanceAgentModel:
    def test_table_name(self):
        assert ProvenanceAgent.__tablename__ == "prov_agents"

    def test_columns(self):
        col_names = {c.name for c in ProvenanceAgent.__table__.columns}
        assert {"id", "name", "type", "created_at"} <= col_names


@skip_if_no_models
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


@skip_if_no_models
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


@skip_if_no_recorder
class TestRecordAgentRun:
    @pytest.mark.asyncio
    async def test_creates_activity_and_entities(self):
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.provenance.recorder._session_factory", mock_session_factory):
            result = await record_agent_run(
                session_id="sess-1",
                user_message="hello",
                agent_response="world",
                tool_calls=[],
                duration_ms=100,
            )

        assert result is not None
        assert mock_session.add.call_count == 3
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_tool_entities(self):
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        tool_calls = [
            {"tool_name": "search", "input": {"q": "test"}, "output": {"result": "ok"}, "duration_ms": 50},
        ]

        with patch("crucible_agent.provenance.recorder._session_factory", mock_session_factory):
            await record_agent_run(
                session_id="sess-2",
                user_message="hi",
                agent_response="result",
                tool_calls=tool_calls,
            )

        assert mock_session.add.call_count == 5

    @pytest.mark.asyncio
    async def test_truncates_long_content(self):
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        long_response = "x" * 10000

        with patch("crucible_agent.provenance.recorder._session_factory", mock_session_factory):
            await record_agent_run(
                session_id="sess-3",
                user_message="hi",
                agent_response=long_response,
                tool_calls=[],
            )

        calls = mock_session.add.call_args_list
        activity = calls[0].args[0]
        assert len(activity.output_data["response"]) <= 1000

        response_entity = calls[2].args[0]
        assert len(response_entity.content) <= 5000


@skip_if_no_recorder
class TestGetSessionHistory:
    @pytest.mark.asyncio
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

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.provenance.recorder._session_factory", mock_session_factory):
            history = await get_session_history("sess-1")

        assert len(history) == 2
        assert history[0]["id"] == "a1"
        assert history[0]["type"] == "agent_run"
        assert history[1]["id"] == "a2"
        assert history[1]["type"] == "tool_use"
        assert history[1]["tool_name"] == "search"
