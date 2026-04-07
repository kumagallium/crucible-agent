import sys
from types import ModuleType
from unittest.mock import MagicMock

# mcp-agent / asyncpg が未インストールでもテスト可能にする
for mod in [
    "mcp_agent", "mcp_agent.app", "mcp_agent.config",
    "mcp_agent.agents", "mcp_agent.agents.agent",
    "mcp_agent.workflows", "mcp_agent.workflows.llm",
    "mcp_agent.workflows.llm.augmented_llm",
    "asyncpg",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# provenance モジュール: Python 3.12+ では型ヒントのモック不要。
# recorder は import 時に DB エンジンを初期化するため、
# テスト用 config (database_url = sqlite) で安全に動作する。

# Settings が .env を読み込んで extra fields エラーになるのを防ぐため、
# config モジュールをモック版に差し替えてからアプリコードをインポートする
from pydantic_settings import BaseSettings


class _TestSettings(BaseSettings):
    litellm_api_base: str = "http://localhost:4000"
    litellm_api_key: str = "sk-test"
    llm_model: str = "test-model"
    crucible_api_url: str = "http://localhost:8080"
    crucible_api_key: str = "test-key"
    crucible_mcp_direct: bool = False
    database_url: str = "sqlite+aiosqlite:///test.db"
    agent_port: int = 9999
    log_level: str = "debug"
    llm_timeout: int = 10
    llm_max_retries: int = 1
    llm_retry_base_delay: float = 0.01
    llm_max_context_messages: int = 40
    approval_timeout: int = 5
    agent_api_key: str = ""
    cors_origins: str = "*"
    mcp_config_path: str = "/tmp/mcp.yaml"

    model_config = {"env_file": None, "extra": "ignore"}


# crucible_agent.config をモック版として先に登録
_config_mod = ModuleType("crucible_agent.config")
_config_mod.Settings = _TestSettings
_config_mod.settings = _TestSettings()
sys.modules["crucible_agent.config"] = _config_mod

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
