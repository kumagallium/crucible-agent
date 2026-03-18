"""設定管理 — 環境変数を pydantic-settings で読み込む"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Crucible Agent の全設定。環境変数 or .env から読み込む。"""

    # --- LLM ---
    litellm_api_base: str = "http://litellm:4000"
    litellm_api_key: str = "sk-crucible-agent-dev"
    llm_model: str = "sakura"

    # --- Crucible ---
    crucible_api_url: str = "http://crucible-api:8080"
    crucible_api_key: str = ""

    # --- Database ---
    database_url: str = "postgresql+asyncpg://agent:agent@postgres:5432/crucible_agent"

    # --- Agent ---
    agent_port: int = 8090
    log_level: str = "info"

    # --- mcp-agent ---
    mcp_config_path: str = "mcp_agent.config.yaml"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# シングルトン
settings = Settings()
