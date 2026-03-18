import pytest

from crucible_agent.crucible.discovery import DiscoveredServer


@pytest.fixture()
def mock_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///test.db")
    monkeypatch.setenv("LITELLM_API_BASE", "http://localhost:4000")
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("CRUCIBLE_API_URL", "http://localhost:8080")
    monkeypatch.setenv("CRUCIBLE_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_PORT", "9999")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("MCP_CONFIG_PATH", "/tmp/mcp.yaml")


@pytest.fixture()
def sample_discovered_server():
    def _factory(**overrides):
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

    return _factory
