import sys
from unittest.mock import AsyncMock, MagicMock, patch

for mod in [
    "asyncpg",
    "mcp_agent",
    "mcp_agent.app",
    "mcp_agent.config",
    "mcp_agent.agents",
    "mcp_agent.agents.agent",
    "mcp_agent.workflows",
    "mcp_agent.workflows.llm",
    "mcp_agent.workflows.llm.augmented_llm",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import pytest
from fastapi.testclient import TestClient

from crucible_agent.crucible.discovery import DiscoveredServer


@pytest.fixture()
def client():
    with patch("crucible_agent.main.init_db", new_callable=AsyncMock):
        from crucible_agent.main import app

        with TestClient(app) as c:
            yield c


def _make_server(**overrides):
    defaults = {
        "name": "test-server",
        "display_name": "Test Server",
        "description": "A test MCP server",
        "url": "http://localhost:8000/sse",
        "transport": "sse",
        "status": "running",
    }
    defaults.update(overrides)
    return DiscoveredServer(**defaults)


class TestHealthEndpoint:
    @patch("crucible_agent.api.routes.httpx.AsyncClient")
    def test_all_ok(self, mock_httpx_cls, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client_instance

        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["components"]["agent"] == "ok"
        assert data["components"]["litellm"] == "ok"
        assert data["components"]["crucible"] == "ok"

    @patch("crucible_agent.api.routes.httpx.AsyncClient")
    def test_litellm_unavailable(self, mock_httpx_cls, client):
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client_instance

        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["components"]["litellm"] == "unavailable"

    @patch("crucible_agent.api.routes.httpx.AsyncClient")
    def test_crucible_unreachable(self, mock_httpx_cls, client):
        call_count = 0

        async def side_effect_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "litellm" in url or call_count == 1:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                return mock_resp
            raise Exception("crucible unreachable")

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(side_effect=side_effect_get)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client_instance

        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["components"]["crucible"] == "unavailable"

    @patch("crucible_agent.api.routes.httpx.AsyncClient")
    def test_litellm_degraded_status_code(self, mock_httpx_cls, client):
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client_instance

        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["components"]["litellm"] == "degraded"

    @patch("crucible_agent.api.routes.httpx.AsyncClient")
    def test_version_included(self, mock_httpx_cls, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_cls.return_value = mock_client_instance

        resp = client.get("/health")
        data = resp.json()
        assert "version" in data
        assert data["version"] == "0.1.0"


class TestToolsEndpoint:
    @patch("crucible_agent.api.routes.discover_servers", new_callable=AsyncMock)
    def test_returns_tool_list(self, mock_discover, client):
        mock_discover.return_value = [
            _make_server(name="server-a", display_name="Server A"),
            _make_server(name="server-b", display_name="Server B"),
        ]

        resp = client.get("/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tools"]) == 2
        assert data["tools"][0]["name"] == "server-a"
        assert data["tools"][1]["name"] == "server-b"

    @patch("crucible_agent.api.routes.discover_servers", new_callable=AsyncMock)
    def test_tool_fields(self, mock_discover, client):
        mock_discover.return_value = [_make_server()]

        resp = client.get("/tools")
        tool = resp.json()["tools"][0]
        assert tool["name"] == "test-server"
        assert tool["display_name"] == "Test Server"
        assert tool["description"] == "A test MCP server"
        assert tool["url"] == "http://localhost:8000/sse"
        assert tool["transport"] == "sse"
        assert tool["status"] == "running"

    @patch("crucible_agent.api.routes.discover_servers", new_callable=AsyncMock)
    def test_discovery_returns_empty(self, mock_discover, client):
        mock_discover.return_value = []

        resp = client.get("/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tools"] == []

    @patch("crucible_agent.api.routes.discover_servers", new_callable=AsyncMock)
    def test_sources_included(self, mock_discover, client):
        mock_discover.return_value = [_make_server()]

        resp = client.get("/tools")
        data = resp.json()
        assert "sources" in data
        assert "crucible" in data["sources"]
        assert data["sources"]["crucible"]["server_count"] == 1
        assert data["sources"]["crucible"]["status"] == "connected"


class TestProfilesEndpoint:
    @patch("crucible_agent.api.routes.list_profiles")
    def test_returns_profiles(self, mock_list, client):
        mock_list.return_value = ["general", "science", "code"]

        resp = client.get("/profiles")
        assert resp.status_code == 200
        data = resp.json()
        names = [p["name"] for p in data["profiles"]]
        assert names == ["general", "science", "code"]

    @patch("crucible_agent.api.routes.list_profiles")
    def test_empty_profiles(self, mock_list, client):
        mock_list.return_value = []

        resp = client.get("/profiles")
        assert resp.status_code == 200
        assert resp.json()["profiles"] == []


class TestAgentRunEndpoint:
    @patch("crucible_agent.api.routes.record_agent_run", new_callable=AsyncMock)
    @patch("crucible_agent.api.routes.run_agent", new_callable=AsyncMock)
    def test_success(self, mock_run, mock_record, client):
        mock_run.return_value = {
            "session_id": "sess-123",
            "message": "Hello from agent",
            "tool_calls": [],
            "token_usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        }
        mock_record.return_value = "prov-abc"

        resp = client.post("/agent/run", json={"message": "Hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-123"
        assert data["message"] == "Hello from agent"
        assert data["provenance_id"] == "prov-abc"
        assert data["token_usage"]["total_tokens"] == 30

    @patch("crucible_agent.api.routes.run_agent", new_callable=AsyncMock)
    def test_run_agent_raises(self, mock_run, client):
        mock_run.side_effect = RuntimeError("LLM failed")

        with pytest.raises(RuntimeError, match="LLM failed"):
            client.post("/agent/run", json={"message": "Hello"})

    def test_missing_message(self, client):
        resp = client.post("/agent/run", json={})
        assert resp.status_code == 422

    @patch("crucible_agent.api.routes.record_agent_run", new_callable=AsyncMock)
    @patch("crucible_agent.api.routes.run_agent", new_callable=AsyncMock)
    def test_provenance_failure_does_not_break(self, mock_run, mock_record, client):
        mock_run.return_value = {
            "session_id": "sess-456",
            "message": "response",
            "tool_calls": [],
            "token_usage": {},
        }
        mock_record.side_effect = Exception("DB down")

        resp = client.post("/agent/run", json={"message": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["provenance_id"] is None
        assert data["session_id"] == "sess-456"

    @patch("crucible_agent.api.routes.record_agent_run", new_callable=AsyncMock)
    @patch("crucible_agent.api.routes.run_agent", new_callable=AsyncMock)
    def test_with_optional_fields(self, mock_run, mock_record, client):
        mock_run.return_value = {
            "session_id": "sess-789",
            "message": "ok",
            "tool_calls": [],
            "token_usage": {},
        }
        mock_record.return_value = None

        resp = client.post(
            "/agent/run",
            json={
                "message": "Hello",
                "session_id": "custom-session",
                "profile": "science",
                "custom_instructions": "Be concise",
            },
        )
        assert resp.status_code == 200
        mock_run.assert_called_once_with(
            message="Hello",
            session_id="custom-session",
            profile="science",
            custom_instructions="Be concise",
        )
