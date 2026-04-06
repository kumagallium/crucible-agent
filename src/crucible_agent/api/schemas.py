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
    server_names: list[str] | None = Field(default=None, description="使用するツール名リスト（省略時は全ツール）")
    options: AgentRunOptions = Field(default_factory=AgentRunOptions)
    context_ids: list[str] = Field(
        default_factory=list,
        description="注入する過去 Entity の ID リスト（手動ブロック引用）",
    )


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
    model: str | None = None


# --- GET /provenance/graph ---


class GraphNode(BaseModel):
    """来歴グラフのノード（Entity / Activity / Agent）"""

    id: str
    node_type: str  # "entity", "activity", "agent"
    prov_type: str  # "agent_response", "agent_run", "llm" など
    label: str
    session_id: str | None = None
    created_at: str | None = None
    # Agent ノード用
    provider: str | None = None
    model_id: str | None = None


class GraphEdge(BaseModel):
    """来歴グラフのエッジ（PROV-DM 関係）"""

    source: str
    target: str
    relation: str  # "wasGeneratedBy", "used", "wasAssociatedWith", "wasInfluencedBy" など
    role: str | None = None  # prov_usage の role


class GraphResponse(BaseModel):
    """GET /provenance/graph レスポンス"""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


# --- /profiles CRUD ---


class ProfileCreate(BaseModel):
    """POST /profiles リクエスト"""

    name: str = Field(..., description="プロファイル名（一意）")
    description: str = Field(default="", description="説明文")
    content: str = Field(..., description="システムプロンプト本文（Markdown）")


class ProfileUpdate(BaseModel):
    """PUT /profiles/{id} リクエスト"""

    name: str | None = Field(default=None, description="プロファイル名")
    description: str | None = Field(default=None, description="説明文")
    content: str | None = Field(default=None, description="システムプロンプト本文（Markdown）")


class ProfileResponse(BaseModel):
    """プロファイル詳細レスポンス"""

    id: str
    name: str
    description: str
    content: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ProfileInfo(BaseModel):
    """プロファイル一覧用（簡易情報）"""

    id: str
    name: str
    description: str = ""

    model_config = {"from_attributes": True}


class ProfilesResponse(BaseModel):
    """GET /profiles レスポンス"""

    profiles: list[ProfileInfo] = Field(default_factory=list)


# --- GET /entities ---


class EntityResponse(BaseModel):
    """GET /entities/{entity_id} レスポンス（引用カード描画用）"""

    id: str
    session_id: str
    type: str
    content: str | None
    created_at: str


# --- POST /sessions/{session_id}/branch ---


class BranchRequest(BaseModel):
    """POST /sessions/{session_id}/branch リクエスト"""

    branch_from_entity_id: str = Field(
        ..., description="どの agent_response Entity まで履歴を引き継ぐか"
    )
    message: str = Field(..., description="分岐後の最初のユーザーメッセージ")
    profile: str | None = Field(default=None, description="プロンプトプロファイル名")
    options: AgentRunOptions = Field(default_factory=AgentRunOptions)


class BranchResponse(BaseModel):
    """POST /sessions/{session_id}/branch レスポンス"""

    session_id: str
    branched_from_session_id: str
    branched_from_entity_id: str
    message: str
    provenance_id: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


# --- GET /tools ---


class CliExecutionInfo(BaseModel):
    """CLI 実行情報"""

    run_command: str = ""
    output_format: str = ""
    install_command: str = ""


class ToolInfo(BaseModel):
    """検出されたツール情報"""

    name: str
    display_name: str
    description: str
    tool_type: str = "mcp_server"  # "mcp_server" | "cli_library" | "skill"
    url: str = ""
    transport: str = ""
    status: str = "registered"
    install_command: str = ""
    github_url: str = ""
    cli_execution: CliExecutionInfo = Field(default_factory=CliExecutionInfo)
    content: str = ""  # Skill のマークダウン本文


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
