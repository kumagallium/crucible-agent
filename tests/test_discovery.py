from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from crucible_agent.crucible.discovery import DiscoveredServer, discover_servers


def _make_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


def _server_data(name="test-mcp", endpoint_path="/sse", port=9000, status="running", **extra):
    data = {
        "name": name,
        "display_name": extra.get("display_name", name),
        "description": extra.get("description", ""),
        "endpoint_path": endpoint_path,
        "port": port,
        "status": status,
    }
    data.update(extra)
    return data


@pytest.mark.asyncio
class TestDiscoverServers:
    async def test_success_parses_response(self, monkeypatch):
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_url", "http://registry:8080")
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_key", "")
        server_data = [_server_data(name="search", port=9001)]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=_make_response(server_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.crucible.discovery.httpx.AsyncClient", return_value=mock_client):
            result = await discover_servers()

        assert len(result) == 1
        assert isinstance(result[0], DiscoveredServer)
        assert result[0].name == "search"
        assert result[0].url == "http://registry:9001/sse"

    async def test_mcp_endpoint_transport(self, monkeypatch):
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_url", "http://registry:8080")
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_key", "")
        server_data = [_server_data(endpoint_path="/mcp", port=9002)]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=_make_response(server_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.crucible.discovery.httpx.AsyncClient", return_value=mock_client):
            result = await discover_servers()

        assert result[0].transport == "streamable-http"

    async def test_sse_endpoint_transport(self, monkeypatch):
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_url", "http://registry:8080")
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_key", "")
        server_data = [_server_data(endpoint_path="/sse", port=9003)]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=_make_response(server_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.crucible.discovery.httpx.AsyncClient", return_value=mock_client):
            result = await discover_servers()

        assert result[0].transport == "sse"

    async def test_filters_running_only(self, monkeypatch):
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_url", "http://registry:8080")
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_key", "")
        server_data = [
            _server_data(name="running-srv", status="running"),
            _server_data(name="stopped-srv", status="stopped"),
            _server_data(name="error-srv", status="error"),
        ]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=_make_response(server_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.crucible.discovery.httpx.AsyncClient", return_value=mock_client):
            result = await discover_servers()

        assert len(result) == 1
        assert result[0].name == "running-srv"

    async def test_connection_error_returns_empty(self, monkeypatch):
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_url", "http://registry:8080")
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_key", "")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.crucible.discovery.httpx.AsyncClient", return_value=mock_client):
            result = await discover_servers()

        assert result == []

    async def test_timeout_returns_empty(self, monkeypatch):
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_url", "http://registry:8080")
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_key", "")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.crucible.discovery.httpx.AsyncClient", return_value=mock_client):
            result = await discover_servers()

        assert result == []

    async def test_api_key_header(self, monkeypatch):
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_url", "http://registry:8080")
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_key", "secret-key")
        server_data = [_server_data()]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=_make_response(server_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.crucible.discovery.httpx.AsyncClient", return_value=mock_client):
            await discover_servers()

        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["headers"]["X-API-Key"] == "secret-key"

    async def test_empty_response(self, monkeypatch):
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_url", "http://registry:8080")
        monkeypatch.setattr("crucible_agent.crucible.discovery.settings.crucible_api_key", "")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=_make_response([]))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("crucible_agent.crucible.discovery.httpx.AsyncClient", return_value=mock_client):
            result = await discover_servers()

        assert result == []
