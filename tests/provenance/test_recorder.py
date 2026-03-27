"""Provenance recorder の実 DB テスト — SQLite in-memory で全関数を検証"""

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from crucible_agent.provenance.models import (
    ProvenanceActivity,
    ProvenanceAgent,
    ProvenanceDerivation,
    ProvenanceEntity,
    ProvenanceUsage,
)
from crucible_agent.provenance.recorder import (
    delete_session,
    get_conversation_history,
    get_conversation_history_until,
    get_entity,
    get_provenance_graph,
    get_session_history,
    list_sessions,
    record_agent_run,
    record_branch_run,
    record_revision,
)


@pytest.fixture()
def patch_session_factory(async_engine):
    """recorder のモジュールレベル _session_factory を テスト用エンジンに差し替え"""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    with patch("crucible_agent.provenance.recorder._session_factory", factory):
        yield factory


class TestRecordAgentRun:
    async def test_basic_record(self, patch_session_factory):
        result = await record_agent_run(
            session_id="sess-1",
            user_message="Hello",
            agent_response="Hi there",
            tool_calls=[],
            duration_ms=100,
        )

        assert "activity_id" in result
        assert "user_entity_id" in result
        assert "response_entity_id" in result

    async def test_creates_agent_activity_entities(self, patch_session_factory):
        await record_agent_run(
            session_id="sess-1",
            user_message="test",
            agent_response="response",
            tool_calls=[],
        )

        async with patch_session_factory() as db:
            # Agent が作成されている
            agents = (await db.execute(select(ProvenanceAgent))).scalars().all()
            assert len(agents) == 1
            assert agents[0].type == "llm"

            # Activity が作成されている
            activities = (await db.execute(select(ProvenanceActivity))).scalars().all()
            assert len(activities) == 1
            assert activities[0].type == "agent_run"
            assert activities[0].session_id == "sess-1"

            # Entity が作成されている（user_message + agent_response）
            entities = (await db.execute(select(ProvenanceEntity))).scalars().all()
            assert len(entities) == 2
            types = {e.type for e in entities}
            assert types == {"user_message", "agent_response"}

    async def test_records_llm_info(self, patch_session_factory):
        await record_agent_run(
            session_id="s1",
            user_message="test",
            agent_response="ok",
            tool_calls=[],
            llm_provider="anthropic",
            llm_model_id="claude-sonnet-4-6",
            llm_model_version="20260301",
        )

        async with patch_session_factory() as db:
            agent = (await db.execute(select(ProvenanceAgent))).scalar_one()
            assert agent.provider == "anthropic"
            assert agent.model_id == "claude-sonnet-4-6"
            assert agent.model_version == "20260301"

    async def test_tool_calls_create_separate_records(self, patch_session_factory):
        tool_calls = [
            {"tool_name": "search", "server_name": "mcp-search", "input": {"q": "test"}, "output": {"r": "ok"}},
            {"tool_name": "fetch", "input": {"url": "http://example.com"}, "output": {"html": "<p>hi</p>"}},
        ]

        await record_agent_run(
            session_id="s1",
            user_message="find info",
            agent_response="here it is",
            tool_calls=tool_calls,
        )

        async with patch_session_factory() as db:
            # agent_run + 2 tool_use = 3 activities
            activities = (await db.execute(select(ProvenanceActivity))).scalars().all()
            assert len(activities) == 3

            tool_activities = [a for a in activities if a.type == "tool_use"]
            assert len(tool_activities) == 2
            tool_names = {a.tool_name for a in tool_activities}
            assert tool_names == {"search", "fetch"}

            # LLM agent + 2 tool agents = 3
            agents = (await db.execute(select(ProvenanceAgent))).scalars().all()
            assert len(agents) == 3

    async def test_usage_links_created(self, patch_session_factory):
        await record_agent_run(
            session_id="s1",
            user_message="hello",
            agent_response="world",
            tool_calls=[],
        )

        async with patch_session_factory() as db:
            usages = (await db.execute(select(ProvenanceUsage))).scalars().all()
            # user_message → activity (input)
            input_usage = [u for u in usages if u.role == "input"]
            assert len(input_usage) == 1

    async def test_context_chain_between_turns(self, patch_session_factory):
        """2ターン目で前ターンの response が context として使われる"""
        await record_agent_run(
            session_id="s1",
            user_message="first",
            agent_response="first response",
            tool_calls=[],
        )
        await record_agent_run(
            session_id="s1",
            user_message="second",
            agent_response="second response",
            tool_calls=[],
        )

        async with patch_session_factory() as db:
            usages = (await db.execute(select(ProvenanceUsage))).scalars().all()
            context_usages = [u for u in usages if u.role == "context"]
            assert len(context_usages) == 1  # 2ターン目が1ターン目の response を context に

    async def test_truncates_output(self, patch_session_factory):
        long_response = "x" * 10000

        await record_agent_run(
            session_id="s1",
            user_message="hi",
            agent_response=long_response,
            tool_calls=[],
        )

        async with patch_session_factory() as db:
            activity = (await db.execute(select(ProvenanceActivity))).scalar_one()
            assert len(activity.output_data["response"]) <= 1000

            entity = (await db.execute(
                select(ProvenanceEntity).where(ProvenanceEntity.type == "agent_response")
            )).scalar_one()
            assert len(entity.content) <= 5000

    async def test_context_ids_create_derivations(self, patch_session_factory):
        """context_ids で wasInfluencedBy が記録される"""
        # 先に参照先の entity を作成
        r1 = await record_agent_run(
            session_id="s1",
            user_message="source",
            agent_response="source resp",
            tool_calls=[],
        )

        r2 = await record_agent_run(
            session_id="s2",
            user_message="derived",
            agent_response="derived resp",
            tool_calls=[],
            context_ids=[r1["response_entity_id"]],
        )

        async with patch_session_factory() as db:
            derivations = (await db.execute(select(ProvenanceDerivation))).scalars().all()
            assert len(derivations) == 1
            assert derivations[0].relation_type == "wasInfluencedBy"
            assert derivations[0].source_entity_id == r1["response_entity_id"]


class TestRecordRevision:
    async def test_creates_was_revision_of(self, patch_session_factory):
        r1 = await record_agent_run(
            session_id="s1",
            user_message="v1",
            agent_response="response v1",
            tool_calls=[],
        )
        r2 = await record_agent_run(
            session_id="s1",
            user_message="v2 (edited)",
            agent_response="response v2",
            tool_calls=[],
        )

        await record_revision(r2["response_entity_id"], r1["response_entity_id"])

        async with patch_session_factory() as db:
            derivs = (await db.execute(select(ProvenanceDerivation))).scalars().all()
            revision = [d for d in derivs if d.relation_type == "wasRevisionOf"]
            assert len(revision) == 1
            assert revision[0].derived_entity_id == r2["response_entity_id"]
            assert revision[0].source_entity_id == r1["response_entity_id"]


class TestListSessions:
    async def test_returns_sessions(self, patch_session_factory):
        await record_agent_run(session_id="s1", user_message="a", agent_response="b", tool_calls=[])
        await record_agent_run(session_id="s2", user_message="c", agent_response="d", tool_calls=[])

        sessions = await list_sessions()
        session_ids = {s["session_id"] for s in sessions}
        assert "s1" in session_ids
        assert "s2" in session_ids

    async def test_includes_activity_count(self, patch_session_factory):
        await record_agent_run(session_id="s1", user_message="a", agent_response="b", tool_calls=[])
        await record_agent_run(session_id="s1", user_message="c", agent_response="d", tool_calls=[])

        sessions = await list_sessions()
        s1 = [s for s in sessions if s["session_id"] == "s1"][0]
        assert s1["activity_count"] == 2


class TestDeleteSession:
    async def test_deletes_all_related_data(self, patch_session_factory):
        await record_agent_run(
            session_id="s1",
            user_message="hello",
            agent_response="world",
            tool_calls=[{"tool_name": "t1", "input": {}, "output": {}}],
        )

        deleted = await delete_session("s1")
        assert deleted is True

        async with patch_session_factory() as db:
            activities = (await db.execute(
                select(ProvenanceActivity).where(ProvenanceActivity.session_id == "s1")
            )).scalars().all()
            assert len(activities) == 0

            entities = (await db.execute(
                select(ProvenanceEntity).where(ProvenanceEntity.session_id == "s1")
            )).scalars().all()
            assert len(entities) == 0

    async def test_nonexistent_session_returns_false(self, patch_session_factory):
        deleted = await delete_session("nonexistent")
        assert deleted is False


class TestGetConversationHistory:
    async def test_single_turn(self, patch_session_factory):
        await record_agent_run(
            session_id="s1",
            user_message="hello",
            agent_response="world",
            tool_calls=[],
        )

        history = await get_conversation_history("s1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello"
        assert history[1]["role"] == "assistant"

    async def test_multi_turn(self, patch_session_factory):
        await record_agent_run(session_id="s1", user_message="hi", agent_response="hello", tool_calls=[])
        await record_agent_run(session_id="s1", user_message="how?", agent_response="fine", tool_calls=[])

        history = await get_conversation_history("s1")
        assert len(history) == 4
        assert history[0]["content"] == "hi"
        assert history[2]["content"] == "how?"

    async def test_empty_session(self, patch_session_factory):
        history = await get_conversation_history("nonexistent")
        assert history == []


class TestGetSessionHistory:
    async def test_includes_entity_ids(self, patch_session_factory):
        result = await record_agent_run(
            session_id="s1",
            user_message="test",
            agent_response="result",
            tool_calls=[],
        )

        history = await get_session_history("s1")
        agent_run = [h for h in history if h["type"] == "agent_run"][0]
        assert agent_run["response_entity_id"] == result["response_entity_id"]


class TestGetProvenanceGraph:
    async def test_returns_nodes_and_edges(self, patch_session_factory):
        await record_agent_run(
            session_id="s1",
            user_message="test",
            agent_response="result",
            tool_calls=[],
        )

        graph = await get_provenance_graph("s1")
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) > 0
        assert len(graph["edges"]) > 0

        # ノードタイプの確認
        node_types = {n["node_type"] for n in graph["nodes"]}
        assert "activity" in node_types
        assert "entity" in node_types
        assert "agent" in node_types

    async def test_cross_session_derivation_included(self, patch_session_factory):
        """クロスセッションの derivation がグラフに含まれる"""
        r1 = await record_agent_run(
            session_id="s1",
            user_message="source",
            agent_response="source resp",
            tool_calls=[],
        )
        r2 = await record_agent_run(
            session_id="s2",
            user_message="derived",
            agent_response="derived resp",
            tool_calls=[],
            context_ids=[r1["response_entity_id"]],
        )

        graph = await get_provenance_graph("s2")
        # s1 のソース entity が stub ノードとして含まれる
        node_ids = {n["id"] for n in graph["nodes"]}
        assert r1["response_entity_id"] in node_ids

        # wasInfluencedBy エッジが存在する
        deriv_edges = [e for e in graph["edges"] if e["relation"] == "wasInfluencedBy"]
        assert len(deriv_edges) == 1


class TestGetEntity:
    async def test_returns_entity(self, patch_session_factory):
        result = await record_agent_run(
            session_id="s1",
            user_message="test",
            agent_response="result",
            tool_calls=[],
        )

        entity = await get_entity(result["response_entity_id"])
        assert entity is not None
        assert entity.type == "agent_response"

    async def test_nonexistent_returns_none(self, patch_session_factory):
        entity = await get_entity("nonexistent-id")
        assert entity is None


class TestRecordBranchRun:
    async def test_creates_was_derived_from(self, patch_session_factory):
        r1 = await record_agent_run(
            session_id="parent",
            user_message="original",
            agent_response="original response",
            tool_calls=[],
        )

        r2 = await record_branch_run(
            parent_session_id="parent",
            branch_session_id="branch-1",
            branch_from_entity_id=r1["response_entity_id"],
            user_message="branched question",
            agent_response="branched answer",
            tool_calls=[],
        )

        assert "activity_id" in r2

        async with patch_session_factory() as db:
            derivs = (await db.execute(select(ProvenanceDerivation))).scalars().all()
            branch_derivs = [d for d in derivs if d.relation_type == "wasDerivedFrom"]
            assert len(branch_derivs) == 1
            assert branch_derivs[0].source_entity_id == r1["response_entity_id"]
