import pytest

from crucible_agent.config import Settings


class TestSettingsDefaults:
    def test_default_litellm_api_base(self):
        s = Settings()
        assert s.litellm_api_base == "http://litellm:4000"

    def test_default_llm_model(self):
        s = Settings()
        assert s.llm_model == "sakura"

    def test_default_database_url(self):
        s = Settings()
        assert "postgresql+asyncpg" in s.database_url

    def test_default_agent_port(self):
        s = Settings()
        assert s.agent_port == 8090

    def test_default_log_level(self):
        s = Settings()
        assert s.log_level == "info"


class TestSettingsEnvOverride:
    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("LITELLM_API_BASE", "http://custom:5000")
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        monkeypatch.setenv("AGENT_PORT", "7777")
        monkeypatch.setenv("LOG_LEVEL", "debug")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")

        s = Settings()
        assert s.litellm_api_base == "http://custom:5000"
        assert s.llm_model == "gpt-4"
        assert s.agent_port == 7777
        assert s.log_level == "debug"
        assert s.database_url == "sqlite:///test.db"


class TestSettingsModelConfig:
    def test_env_file_setting(self):
        assert Settings.model_config["env_file"] == ".env"

    def test_env_file_encoding(self):
        assert Settings.model_config["env_file_encoding"] == "utf-8"
