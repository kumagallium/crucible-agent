"""Pydantic リクエスト/レスポンスモデル"""

from __future__ import annotations

from pydantic import BaseModel, Field


# --- POST /agent/run ---


class AgentRunOptions(BaseModel):
    """エージェント実行オプション"""

    max_turns: int = Field(default=10, description="最大ループ回数")
    require_approval: bool = Field(default=False, description="tool 実行前に承認を求めるか")
    model: str | None = Field(default=None, description="使用モデル名（省略時は環境変数 LLM_MODEL）")


class AgentRunRequest(BaseModel):
    """POST /agent/run リクエスト"""

    message: str = Field(..., description="ユーザーのメッセージ")
    session_id: str | None = Field(default=None, description="会話セッション ID（省略時は新規作成）")
    profile: str | None = Field(default=None, description="プロンプトプロファイル名（例: science, general）")
    custom_instructions: str | None = Field(default=None, description="カスタム指示（プロファイルに追加）")
    options: AgentRunOptions = Field(default_factory=AgentRunOptions)


class ToolCallRecord(BaseModel):
    """ツール呼び出しの記録"""

    tool_name: str
    server: str
    input: dict
    output: dict
    duration_ms: int


class TokenUsage(BaseModel):
    """トークン使用量"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class AgentRunResponse(BaseModel):
    """POST /agent/run レスポンス"""

    session_id: str
    message: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    provenance_id: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


# --- GET /profiles ---


class ProfileInfo(BaseModel):
    """プロファイル情報"""

    name: str
    description: str = ""


class ProfilesResponse(BaseModel):
    """GET /profiles レスポンス"""

    profiles: list[ProfileInfo] = Field(default_factory=list)


# --- GET /tools ---


class ToolInfo(BaseModel):
    """検出されたツール情報"""

    name: str
    display_name: str
    description: str
    url: str
    transport: str
    status: str


class ToolSourceInfo(BaseModel):
    """ツールソースの接続状態"""

    url: str
    status: str
    server_count: int


class ToolsResponse(BaseModel):
    """GET /tools レスポンス"""

    tools: list[ToolInfo] = Field(default_factory=list)
    sources: dict[str, ToolSourceInfo] = Field(default_factory=dict)


# --- GET /health ---


class HealthResponse(BaseModel):
    """GET /health レスポンス"""

    status: str = "healthy"
    components: dict[str, str] = Field(default_factory=dict)
    version: str
