"""Provenance モデルの実 DB テスト — SQLite in-memory で CRUD 操作を検証"""

import uuid

from sqlalchemy import select

from crucible_agent.provenance.models import (
    ProvenanceActivity,
    ProvenanceAgent,
    ProvenanceDerivation,
    ProvenanceEntity,
    ProvenanceUsage,
    Profile,
)


class TestProvenanceAgentCRUD:
    async def test_create_and_read(self, async_session):
        agent = ProvenanceAgent(name="test-llm", type="llm", provider="anthropic", model_id="claude")
        async_session.add(agent)
        await async_session.commit()

        result = await async_session.execute(select(ProvenanceAgent).where(ProvenanceAgent.name == "test-llm"))
        fetched = result.scalar_one()
        assert fetched.type == "llm"
        assert fetched.provider == "anthropic"
        assert fetched.id is not None

    async def test_uuid_auto_generation(self, async_session):
        agent = ProvenanceAgent(name="auto-id", type="user")
        async_session.add(agent)
        await async_session.commit()

        result = await async_session.execute(select(ProvenanceAgent).where(ProvenanceAgent.name == "auto-id"))
        fetched = result.scalar_one()
        # UUID 形式であること
        uuid.UUID(fetched.id)

    async def test_nullable_fields(self, async_session):
        agent = ProvenanceAgent(name="minimal", type="mcp_tool")
        async_session.add(agent)
        await async_session.commit()

        result = await async_session.execute(select(ProvenanceAgent).where(ProvenanceAgent.name == "minimal"))
        fetched = result.scalar_one()
        assert fetched.provider is None
        assert fetched.model_id is None
        assert fetched.server_name is None
        assert fetched.external_id is None


class TestProvenanceActivityCRUD:
    async def test_create_with_agent(self, async_session):
        agent = ProvenanceAgent(name="llm", type="llm")
        async_session.add(agent)
        await async_session.flush()

        activity = ProvenanceActivity(
            session_id="sess-1",
            type="agent_run",
            input_data={"message": "hello"},
            output_data={"response": "hi"},
            agent_id=agent.id,
        )
        async_session.add(activity)
        await async_session.commit()

        result = await async_session.execute(
            select(ProvenanceActivity).where(ProvenanceActivity.session_id == "sess-1")
        )
        fetched = result.scalar_one()
        assert fetched.type == "agent_run"
        assert fetched.agent_id == agent.id

    async def test_json_fields(self, async_session):
        activity = ProvenanceActivity(
            session_id="sess-2",
            type="tool_use",
            tool_name="search",
            input_data={"query": "test", "limit": 10},
            output_data={"results": [1, 2, 3]},
        )
        async_session.add(activity)
        await async_session.commit()

        result = await async_session.execute(
            select(ProvenanceActivity).where(ProvenanceActivity.session_id == "sess-2")
        )
        fetched = result.scalar_one()
        assert fetched.input_data["query"] == "test"
        assert fetched.output_data["results"] == [1, 2, 3]


class TestProvenanceEntityCRUD:
    async def test_create_with_activity(self, async_session):
        activity = ProvenanceActivity(session_id="sess-1", type="agent_run")
        async_session.add(activity)
        await async_session.flush()

        entity = ProvenanceEntity(
            session_id="sess-1",
            type="agent_response",
            content="Hello world",
            generated_by=activity.id,
        )
        async_session.add(entity)
        await async_session.commit()

        result = await async_session.execute(
            select(ProvenanceEntity).where(ProvenanceEntity.generated_by == activity.id)
        )
        fetched = result.scalar_one()
        assert fetched.content == "Hello world"
        assert fetched.type == "agent_response"


class TestProvenanceUsageCRUD:
    async def test_link_activity_to_entity(self, async_session):
        activity = ProvenanceActivity(session_id="s1", type="agent_run")
        entity = ProvenanceEntity(session_id="s1", type="user_message", content="hi")
        async_session.add_all([activity, entity])
        await async_session.flush()

        usage = ProvenanceUsage(activity_id=activity.id, entity_id=entity.id, role="input")
        async_session.add(usage)
        await async_session.commit()

        result = await async_session.execute(
            select(ProvenanceUsage).where(ProvenanceUsage.activity_id == activity.id)
        )
        fetched = result.scalar_one()
        assert fetched.role == "input"
        assert fetched.entity_id == entity.id


class TestProvenanceDerivationCRUD:
    async def test_create_derivation(self, async_session):
        e1 = ProvenanceEntity(session_id="s1", type="agent_response", content="original")
        e2 = ProvenanceEntity(session_id="s2", type="agent_response", content="derived")
        async_session.add_all([e1, e2])
        await async_session.flush()

        deriv = ProvenanceDerivation(
            derived_entity_id=e2.id,
            source_entity_id=e1.id,
            relation_type="wasDerivedFrom",
        )
        async_session.add(deriv)
        await async_session.commit()

        result = await async_session.execute(
            select(ProvenanceDerivation).where(
                ProvenanceDerivation.derived_entity_id == e2.id
            )
        )
        fetched = result.scalar_one()
        assert fetched.source_entity_id == e1.id
        assert fetched.relation_type == "wasDerivedFrom"

    async def test_revision_relation(self, async_session):
        e1 = ProvenanceEntity(session_id="s1", type="user_message", content="v1")
        e2 = ProvenanceEntity(session_id="s1", type="user_message", content="v2")
        async_session.add_all([e1, e2])
        await async_session.flush()

        deriv = ProvenanceDerivation(
            derived_entity_id=e2.id,
            source_entity_id=e1.id,
            relation_type="wasRevisionOf",
        )
        async_session.add(deriv)
        await async_session.commit()

        result = await async_session.execute(
            select(ProvenanceDerivation).where(
                ProvenanceDerivation.relation_type == "wasRevisionOf"
            )
        )
        fetched = result.scalar_one()
        assert fetched.derived_entity_id == e2.id


class TestProfileCRUD:
    async def test_create_and_read(self, async_session):
        profile = Profile(
            name="test-profile",
            description="Test profile",
            content="You are a helpful assistant.",
            is_active=True,
        )
        async_session.add(profile)
        await async_session.commit()

        result = await async_session.execute(
            select(Profile).where(Profile.name == "test-profile")
        )
        fetched = result.scalar_one()
        assert fetched.content == "You are a helpful assistant."
        assert fetched.is_active is True

    async def test_unique_name(self, async_session):
        p1 = Profile(name="unique-name", content="v1")
        async_session.add(p1)
        await async_session.commit()

        from sqlalchemy.exc import IntegrityError

        p2 = Profile(name="unique-name", content="v2")
        async_session.add(p2)
        with pytest.raises(IntegrityError):
            await async_session.commit()


# pytest をインポート（test_unique_name で使用）
import pytest
