from crucible_agent.config import Settings, settings


class TestSettingsInstance:
    def test_has_litellm_api_base(self):
        assert hasattr(settings, "litellm_api_base")
        assert isinstance(settings.litellm_api_base, str)

    def test_has_llm_model(self):
        assert hasattr(settings, "llm_model")
        assert isinstance(settings.llm_model, str)

    def test_has_database_url(self):
        assert hasattr(settings, "database_url")
        assert isinstance(settings.database_url, str)

    def test_has_agent_port(self):
        assert hasattr(settings, "agent_port")
        assert isinstance(settings.agent_port, int)

    def test_has_log_level(self):
        assert hasattr(settings, "log_level")
        assert isinstance(settings.log_level, str)

    def test_has_crucible_api_url(self):
        assert hasattr(settings, "crucible_api_url")
        assert isinstance(settings.crucible_api_url, str)

    def test_has_mcp_config_path(self):
        assert hasattr(settings, "mcp_config_path")
        assert isinstance(settings.mcp_config_path, str)


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
