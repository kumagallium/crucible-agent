import pytest

from crucible_agent.api.schemas import (
    AgentRunOptions,
    AgentRunRequest,
    AgentRunResponse,
    HealthResponse,
    ProfileInfo,
    TokenUsage,
    ToolCallRecord,
    ToolInfo,
)


class TestAgentRunRequest:
    def test_required_message(self):
        req = AgentRunRequest(message="hello")
        assert req.message == "hello"

    def test_missing_message_raises(self):
        with pytest.raises(Exception):
            AgentRunRequest()

    def test_optional_session_id_default(self):
        req = AgentRunRequest(message="hi")
        assert req.session_id is None

    def test_optional_profile_default(self):
        req = AgentRunRequest(message="hi")
        assert req.profile is None

    def test_optional_custom_instructions_default(self):
        req = AgentRunRequest(message="hi")
        assert req.custom_instructions is None

    def test_options_default_factory(self):
        req = AgentRunRequest(message="hi")
        assert isinstance(req.options, AgentRunOptions)


class TestAgentRunOptions:
    def test_default_max_turns(self):
        opts = AgentRunOptions()
        assert opts.max_turns == 10

    def test_default_require_approval(self):
        opts = AgentRunOptions()
        assert opts.require_approval is False

    def test_default_model_is_none(self):
        opts = AgentRunOptions()
        assert opts.model is None


class TestTokenUsage:
    def test_defaults_all_zero(self):
        t = TokenUsage()
        assert t.input_tokens == 0
        assert t.output_tokens == 0
        assert t.total_tokens == 0


class TestAgentRunResponse:
    def test_construction(self):
        resp = AgentRunResponse(session_id="s1", message="done")
        assert resp.session_id == "s1"
        assert resp.message == "done"
        assert resp.tool_calls == []
        assert resp.provenance_id is None
        assert isinstance(resp.token_usage, TokenUsage)


class TestToolCallRecord:
    def test_construction(self):
        rec = ToolCallRecord(
            tool_name="search",
            server="mcp-search",
            input={"q": "test"},
            output={"result": "ok"},
            duration_ms=150,
        )
        assert rec.tool_name == "search"
        assert rec.server == "mcp-search"
        assert rec.duration_ms == 150


class TestHealthResponse:
    def test_construction(self):
        h = HealthResponse(version="1.0.0")
        assert h.status == "healthy"
        assert h.components == {}
        assert h.version == "1.0.0"


class TestToolInfo:
    def test_construction(self):
        t = ToolInfo(
            name="tool1",
            display_name="Tool 1",
            description="desc",
            url="http://localhost:8000/sse",
            transport="sse",
            status="running",
        )
        assert t.name == "tool1"
        assert t.transport == "sse"


class TestProfileInfo:
    def test_construction(self):
        p = ProfileInfo(id="test-id", name="science")
        assert p.id == "test-id"
        assert p.name == "science"
        assert p.description == ""

    def test_with_description(self):
        p = ProfileInfo(id="test-id", name="general", description="General profile")
        assert p.description == "General profile"
