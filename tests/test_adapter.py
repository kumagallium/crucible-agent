import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

mcp_agent_mock = types.ModuleType("mcp_agent")
mcp_agent_app_mock = types.ModuleType("mcp_agent.app")
mcp_agent_config_mock = types.ModuleType("mcp_agent.config")
mcp_agent_agents_mock = types.ModuleType("mcp_agent.agents")
mcp_agent_agents_agent_mock = types.ModuleType("mcp_agent.agents.agent")
mcp_agent_workflows_mock = types.ModuleType("mcp_agent.workflows")
mcp_agent_workflows_llm_mock = types.ModuleType("mcp_agent.workflows.llm")
mcp_agent_workflows_llm_aug_mock = types.ModuleType("mcp_agent.workflows.llm.augmented_llm")
mcp_agent_workflows_llm_openai_mock = types.ModuleType("mcp_agent.workflows.llm.augmented_llm_openai")

MockMCPApp = MagicMock(name="MCPApp")
MockAgent = MagicMock(name="Agent")
MockMCPServerSettings = MagicMock(name="MCPServerSettings")
MockMCPSettings = MagicMock(name="MCPSettings")
MockOpenAISettings = MagicMock(name="OpenAISettings")
MockMCPAgentSettings = MagicMock(name="Settings")
MockAugmentedLLM = MagicMock(name="AugmentedLLM")
MockOpenAIAugmentedLLM = MagicMock(name="OpenAIAugmentedLLM")

mcp_agent_app_mock.MCPApp = MockMCPApp
mcp_agent_config_mock.MCPServerSettings = MockMCPServerSettings
mcp_agent_config_mock.MCPSettings = MockMCPSettings
mcp_agent_config_mock.OpenAISettings = MockOpenAISettings
mcp_agent_config_mock.Settings = MockMCPAgentSettings
mcp_agent_agents_agent_mock.Agent = MockAgent
mcp_agent_workflows_llm_aug_mock.AugmentedLLM = MockAugmentedLLM
mcp_agent_workflows_llm_openai_mock.OpenAIAugmentedLLM = MockOpenAIAugmentedLLM

sys.modules["mcp_agent"] = mcp_agent_mock
sys.modules["mcp_agent.app"] = mcp_agent_app_mock
sys.modules["mcp_agent.config"] = mcp_agent_config_mock
sys.modules["mcp_agent.agents"] = mcp_agent_agents_mock
sys.modules["mcp_agent.agents.agent"] = mcp_agent_agents_agent_mock
sys.modules["mcp_agent.workflows"] = mcp_agent_workflows_mock
sys.modules["mcp_agent.workflows.llm"] = mcp_agent_workflows_llm_mock
sys.modules["mcp_agent.workflows.llm.augmented_llm"] = mcp_agent_workflows_llm_aug_mock
sys.modules["mcp_agent.workflows.llm.augmented_llm_openai"] = mcp_agent_workflows_llm_openai_mock

from crucible_agent.crucible.discovery import DiscoveredServer
from crucible_agent.agent.adapter import (
    AdapterResult,
    StreamEvent,
    _discovered_to_server_configs,
    _extract_tool_call,
    _get_event_content,
    _get_event_type,
    _get_tool_id,
    _get_tool_input,
    _get_tool_name,
    _get_tool_output,
    _get_token_usage,
    run,
    run_stream,
)


class TestDiscoveredToServerConfigs:
    def test_streamable_http_converts_to_sse(self):
        servers = [
            DiscoveredServer(
                name="s1",
                display_name="S1",
                description="desc",
                url="http://localhost:8000/mcp",
                transport="streamable-http",
                status="running",
            )
        ]
        result = _discovered_to_server_configs(servers)
        assert "s1" in result
        call_kwargs = MockMCPServerSettings.call_args
        assert call_kwargs.kwargs["transport"] == "sse"

    def test_sse_transport_stays_sse(self):
        servers = [
            DiscoveredServer(
                name="s2",
                display_name="S2",
                description="desc",
                url="http://localhost:8000/sse",
                transport="sse",
                status="running",
            )
        ]
        result = _discovered_to_server_configs(servers)
        assert "s2" in result
        call_kwargs = MockMCPServerSettings.call_args
        assert call_kwargs.kwargs["transport"] == "sse"

    def test_empty_list_returns_empty_dict(self):
        result = _discovered_to_server_configs([])
        assert result == {}


class TestGetEventType:
    def test_with_dict_like_object_having_type_attr(self):
        event = MagicMock()
        event.type = "text_delta"
        del event.type.value
        assert _get_event_type(event) == "text_delta"

    def test_with_enum_type(self):
        event = MagicMock()
        event.type.value = "TEXT_DELTA"
        assert _get_event_type(event) == "text_delta"

    def test_missing_type_returns_unknown(self):
        event = object()
        assert _get_event_type(event) == "unknown"


class TestGetEventContent:
    def test_with_content_attr(self):
        event = MagicMock()
        event.content = "hello world"
        assert _get_event_content(event) == "hello world"

    def test_missing_content_returns_empty(self):
        event = object()
        assert _get_event_content(event) == ""

    def test_none_content_returns_empty(self):
        event = MagicMock()
        event.content = None
        assert _get_event_content(event) == ""


class TestGetToolId:
    def test_with_tool_call_id_in_metadata(self):
        event = MagicMock()
        event.metadata = {"tool_call_id": "tc-123"}
        assert _get_tool_id(event) == "tc-123"

    def test_with_id_fallback(self):
        event = MagicMock()
        event.metadata = {"id": "id-456"}
        assert _get_tool_id(event) == "id-456"

    def test_missing_metadata_returns_empty(self):
        event = object()
        assert _get_tool_id(event) == ""


class TestGetToolName:
    def test_with_tool_name_in_metadata(self):
        event = MagicMock()
        event.metadata = {"tool_name": "search"}
        assert _get_tool_name(event) == "search"

    def test_with_name_fallback(self):
        event = MagicMock()
        event.metadata = {"name": "fetch"}
        assert _get_tool_name(event) == "fetch"


class TestGetToolInput:
    def test_with_input_in_metadata(self):
        event = MagicMock()
        event.metadata = {"input": {"query": "test"}}
        assert _get_tool_input(event) == {"query": "test"}

    def test_with_arguments_fallback(self):
        event = MagicMock()
        event.metadata = {"arguments": {"q": "hello"}}
        assert _get_tool_input(event) == {"q": "hello"}

    def test_missing_metadata_returns_empty_dict(self):
        event = object()
        assert _get_tool_input(event) == {}


class TestGetToolOutput:
    def test_dict_content(self):
        event = MagicMock()
        event.content = {"data": "result"}
        assert _get_tool_output(event) == {"data": "result"}

    def test_string_content_wraps_in_result(self):
        event = MagicMock()
        event.content = "plain text"
        assert _get_tool_output(event) == {"result": "plain text"}

    def test_none_content_returns_empty(self):
        event = MagicMock()
        event.content = None
        assert _get_tool_output(event) == {}


class TestGetTokenUsage:
    def test_with_usage(self):
        event = MagicMock()
        event.usage.input_tokens = 10
        event.usage.output_tokens = 20
        event.usage.total_tokens = 30
        result = _get_token_usage(event)
        assert result == {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}

    def test_no_usage_returns_empty(self):
        event = object()
        assert _get_token_usage(event) == {}


class TestExtractToolCall:
    def test_extracts_complete_info(self):
        event = MagicMock()
        event.metadata = {"tool_name": "search", "input": {"q": "test"}}
        event.content = {"answer": "42"}
        result = _extract_tool_call(event)
        assert result["tool_name"] == "search"
        assert result["input"] == {"q": "test"}
        assert result["output"] == {"answer": "42"}


class TestRun:
    @pytest.mark.asyncio
    async def test_success_with_stream(self):
        text_event = MagicMock()
        text_event.type = "text_delta"
        del text_event.type.value
        text_event.content = "Hello"
        text_event.metadata = {}

        tool_event = MagicMock()
        tool_event.type = "tool_result"
        del tool_event.type.value
        tool_event.content = {"res": "ok"}
        tool_event.metadata = {"tool_name": "test_tool", "input": {"a": 1}}

        async def fake_stream(msg):
            for e in [text_event, tool_event]:
                yield e

        mock_llm = MagicMock()
        mock_llm.generate_stream = fake_stream

        mock_agent_instance = MagicMock()
        mock_agent_instance.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_instance.__aexit__ = AsyncMock(return_value=False)
        mock_agent_instance.attach_llm = AsyncMock(return_value=mock_llm)

        mock_app_ctx = MagicMock()
        mock_app_ctx.__aenter__ = AsyncMock()
        mock_app_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.agent.adapter._build_mcp_app") as mock_build, \
             patch("crucible_agent.agent.adapter.Agent", return_value=mock_agent_instance):
            mock_build.return_value.run.return_value = mock_app_ctx
            result = await run("instruction", "hello")

        assert isinstance(result, AdapterResult)
        assert result.message == "Hello"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool_name"] == "test_tool"

    @pytest.mark.asyncio
    async def test_fallback_to_generate_str(self):
        mock_llm = MagicMock()
        mock_llm.generate_stream = MagicMock(side_effect=AttributeError("no stream"))
        mock_llm.generate_str = AsyncMock(return_value="fallback response")

        mock_agent_instance = MagicMock()
        mock_agent_instance.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_instance.__aexit__ = AsyncMock(return_value=False)
        mock_agent_instance.attach_llm = AsyncMock(return_value=mock_llm)

        mock_app_ctx = MagicMock()
        mock_app_ctx.__aenter__ = AsyncMock()
        mock_app_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.agent.adapter._build_mcp_app") as mock_build, \
             patch("crucible_agent.agent.adapter.Agent", return_value=mock_agent_instance):
            mock_build.return_value.run.return_value = mock_app_ctx
            result = await run("instruction", "hello")

        assert result.message == "fallback response"
        assert result.tool_calls == []


class TestRunStream:
    @pytest.mark.asyncio
    async def test_text_delta_events(self):
        text_event = MagicMock()
        text_event.type = "text_delta"
        del text_event.type.value
        text_event.content = "streaming"
        text_event.metadata = {}

        async def fake_stream(msg):
            yield text_event

        mock_llm = MagicMock()
        mock_llm.generate_stream = fake_stream

        mock_agent_instance = MagicMock()
        mock_agent_instance.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_instance.__aexit__ = AsyncMock(return_value=False)
        mock_agent_instance.attach_llm = AsyncMock(return_value=mock_llm)

        mock_app_ctx = MagicMock()
        mock_app_ctx.__aenter__ = AsyncMock()
        mock_app_ctx.__aexit__ = AsyncMock(return_value=False)

        events = []
        with patch("crucible_agent.agent.adapter._build_mcp_app") as mock_build, \
             patch("crucible_agent.agent.adapter.Agent", return_value=mock_agent_instance):
            mock_build.return_value.run.return_value = mock_app_ctx
            async for ev in run_stream("instruction", "hello"):
                events.append(ev)

        assert len(events) == 1
        assert events[0].type == "text_delta"
        assert events[0].content == "streaming"

    @pytest.mark.asyncio
    async def test_tool_use_events(self):
        tool_start_event = MagicMock()
        tool_start_event.type = "tool_use_start"
        del tool_start_event.type.value
        tool_start_event.content = ""
        tool_start_event.metadata = {"tool_call_id": "tc1", "tool_name": "search", "input": {"q": "hi"}}

        tool_result_event = MagicMock()
        tool_result_event.type = "tool_result"
        del tool_result_event.type.value
        tool_result_event.content = {"answer": "found"}
        tool_result_event.metadata = {"tool_call_id": "tc1", "tool_name": "search"}

        async def fake_stream(msg):
            yield tool_start_event
            yield tool_result_event

        mock_llm = MagicMock()
        mock_llm.generate_stream = fake_stream

        mock_agent_instance = MagicMock()
        mock_agent_instance.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_instance.__aexit__ = AsyncMock(return_value=False)
        mock_agent_instance.attach_llm = AsyncMock(return_value=mock_llm)

        mock_app_ctx = MagicMock()
        mock_app_ctx.__aenter__ = AsyncMock()
        mock_app_ctx.__aexit__ = AsyncMock(return_value=False)

        events = []
        with patch("crucible_agent.agent.adapter._build_mcp_app") as mock_build, \
             patch("crucible_agent.agent.adapter.Agent", return_value=mock_agent_instance):
            mock_build.return_value.run.return_value = mock_app_ctx
            async for ev in run_stream("instruction", "hello"):
                events.append(ev)

        assert events[0].type == "tool_start"
        assert events[0].tool_name == "search"
        assert events[1].type == "tool_end"
        assert events[1].tool_name == "search"
        assert events[1].output == {"answer": "found"}

    @pytest.mark.asyncio
    async def test_done_event(self):
        complete_event = MagicMock()
        complete_event.type = "complete"
        del complete_event.type.value
        complete_event.content = ""
        complete_event.metadata = {}
        del complete_event.usage

        async def fake_stream(msg):
            yield complete_event

        mock_llm = MagicMock()
        mock_llm.generate_stream = fake_stream

        mock_agent_instance = MagicMock()
        mock_agent_instance.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_instance.__aexit__ = AsyncMock(return_value=False)
        mock_agent_instance.attach_llm = AsyncMock(return_value=mock_llm)

        mock_app_ctx = MagicMock()
        mock_app_ctx.__aenter__ = AsyncMock()
        mock_app_ctx.__aexit__ = AsyncMock(return_value=False)

        events = []
        with patch("crucible_agent.agent.adapter._build_mcp_app") as mock_build, \
             patch("crucible_agent.agent.adapter.Agent", return_value=mock_agent_instance):
            mock_build.return_value.run.return_value = mock_app_ctx
            async for ev in run_stream("instruction", "hello"):
                events.append(ev)

        assert events[0].type == "done"
        assert events[0].token_usage == {}
