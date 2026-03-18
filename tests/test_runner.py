from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crucible_agent.crucible.discovery import DiscoveredServer
from crucible_agent.agent.adapter import AdapterResult, StreamEvent


def _make_server(**overrides):
    defaults = {
        "name": "test-server",
        "display_name": "Test Server",
        "description": "desc",
        "url": "http://localhost:8000/sse",
        "transport": "sse",
        "status": "running",
    }
    defaults.update(overrides)
    return DiscoveredServer(**defaults)


@pytest.fixture
def discovered_servers():
    return [
        _make_server(name="server-a"),
        _make_server(name="server-b"),
        _make_server(name="server-c"),
    ]


class TestResolveServers:
    @pytest.mark.asyncio
    async def test_with_explicit_names_filters(self, discovered_servers):
        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc:
            mock_disc.return_value = discovered_servers
            from crucible_agent.agent.runner import _resolve_servers

            names, filtered = await _resolve_servers(["server-a", "server-c"])

        assert names == ["server-a", "server-c"]
        assert len(filtered) == 2
        assert {s.name for s in filtered} == {"server-a", "server-c"}

    @pytest.mark.asyncio
    async def test_with_none_returns_all(self, discovered_servers):
        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc:
            mock_disc.return_value = discovered_servers
            from crucible_agent.agent.runner import _resolve_servers

            names, discovered = await _resolve_servers(None)

        assert names == ["server-a", "server-b", "server-c"]
        assert len(discovered) == 3

    @pytest.mark.asyncio
    async def test_with_no_results_returns_empty(self):
        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc:
            mock_disc.return_value = []
            from crucible_agent.agent.runner import _resolve_servers

            names, discovered = await _resolve_servers(None)

        assert names == []
        assert discovered == []


class TestRunAgent:
    @pytest.mark.asyncio
    async def test_success(self, discovered_servers):
        mock_result = AdapterResult(
            message="response text",
            tool_calls=[{"tool_name": "t", "input": {}, "output": {}}],
            token_usage={"total_tokens": 100},
        )

        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc, \
             patch("crucible_agent.agent.runner.adapter_run", new_callable=AsyncMock) as mock_run, \
             patch("crucible_agent.agent.runner.build_instruction", return_value="sys prompt"):
            mock_disc.return_value = discovered_servers
            mock_run.return_value = mock_result
            from crucible_agent.agent.runner import run_agent

            result = await run_agent("hello", session_id="sess-1")

        assert result["session_id"] == "sess-1"
        assert result["message"] == "response text"
        assert len(result["tool_calls"]) == 1
        assert result["token_usage"] == {"total_tokens": 100}

    @pytest.mark.asyncio
    async def test_with_profile(self, discovered_servers):
        mock_result = AdapterResult(message="ok", tool_calls=[], token_usage={})

        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc, \
             patch("crucible_agent.agent.runner.adapter_run", new_callable=AsyncMock) as mock_run, \
             patch("crucible_agent.agent.runner.build_instruction", return_value="profile prompt") as mock_build:
            mock_disc.return_value = discovered_servers
            mock_run.return_value = mock_result
            from crucible_agent.agent.runner import run_agent

            await run_agent("hello", profile="developer")

        mock_build.assert_called_once_with("developer", None)

    @pytest.mark.asyncio
    async def test_with_custom_instructions(self, discovered_servers):
        mock_result = AdapterResult(message="ok", tool_calls=[], token_usage={})

        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc, \
             patch("crucible_agent.agent.runner.adapter_run", new_callable=AsyncMock) as mock_run, \
             patch("crucible_agent.agent.runner.build_instruction", return_value="custom prompt") as mock_build:
            mock_disc.return_value = discovered_servers
            mock_run.return_value = mock_result
            from crucible_agent.agent.runner import run_agent

            await run_agent("hello", custom_instructions="be brief")

        mock_build.assert_called_once_with(None, "be brief")

    @pytest.mark.asyncio
    async def test_generates_session_id_when_none(self, discovered_servers):
        mock_result = AdapterResult(message="ok", tool_calls=[], token_usage={})

        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc, \
             patch("crucible_agent.agent.runner.adapter_run", new_callable=AsyncMock) as mock_run, \
             patch("crucible_agent.agent.runner.build_instruction", return_value="prompt"):
            mock_disc.return_value = discovered_servers
            mock_run.return_value = mock_result
            from crucible_agent.agent.runner import run_agent

            result = await run_agent("hello")

        assert result["session_id"] is not None
        assert len(result["session_id"]) == 36


class TestRunAgentStream:
    @pytest.mark.asyncio
    async def test_yields_events(self, discovered_servers):
        async def fake_stream(**kwargs):
            yield StreamEvent(type="text_delta", content="hi")
            yield StreamEvent(type="done")

        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc, \
             patch("crucible_agent.agent.runner.adapter_run_stream", side_effect=fake_stream), \
             patch("crucible_agent.agent.runner.build_instruction", return_value="prompt"):
            mock_disc.return_value = discovered_servers
            from crucible_agent.agent.runner import run_agent_stream

            events = []
            async for ev in run_agent_stream("hello", session_id="s1"):
                events.append(ev)

        assert len(events) == 2
        assert events[0].type == "text_delta"
        assert events[0].content == "hi"
        assert events[1].type == "done"

    @pytest.mark.asyncio
    async def test_passes_approval_params(self, discovered_servers):
        async def fake_stream(**kwargs):
            yield StreamEvent(type="done")

        mock_callback = AsyncMock()

        with patch("crucible_agent.agent.runner.discover_servers", new_callable=AsyncMock) as mock_disc, \
             patch("crucible_agent.agent.runner.adapter_run_stream", side_effect=fake_stream) as mock_stream, \
             patch("crucible_agent.agent.runner.build_instruction", return_value="prompt"):
            mock_disc.return_value = discovered_servers
            from crucible_agent.agent.runner import run_agent_stream

            events = []
            async for ev in run_agent_stream(
                "hello",
                require_approval=True,
                approval_callback=mock_callback,
            ):
                events.append(ev)

        call_kwargs = mock_stream.call_args.kwargs
        assert call_kwargs["require_approval"] is True
        assert call_kwargs["approval_callback"] is mock_callback
