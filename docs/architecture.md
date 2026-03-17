# Architecture: Crucible Agent

## 1. システム全体像

Crucible Agentは4つの独立したdocker-composeユニットの1つとして動作する。

| Compose | コンポーネント | 役割 |
|---------|------------|------|
| A: ELN | Bocknote (Next.js) | 実験エディタ、チャットパネル |
| **B: Crucible Agent** | **mcp-agent + LiteLLM + PROV-DM DB** | **エージェントランタイム** |
| C: Crucible | Crucible API/UI + MCPサーバープール | MCPサーバーレジストリ |
| D: Dify | Dify platform | GUIワークフロー工場（MCP公開） |

### 通信プロトコル

```
ELN ──[REST/WS]──► Crucible Agent ──[SSE]──► Crucible MCP servers
                        │                        ▲
                        │                    [SSE] (Dify WF as MCP)
                        │                        │
                        ▼                      Dify
                   LiteLLM ──[HTTP]──► さくらAI Engine
```

- ELN → Agent: REST (`POST /agent/run`) or WebSocket (`WS /agent/ws`)
- Agent → MCPサーバー: SSE (MCP protocol)
- Agent → LLM: OpenAI互換HTTP (via LiteLLM Proxy)
- Dify → Crucible: MCP SSE publish

## 2. Crucible Agent内部アーキテクチャ

```
┌─ Crucible Agent Container ─────────────────────┐
│                                                  │
│  ┌─ FastAPI ───────────────────────────────────┐ │
│  │  POST /agent/run    (sync)                  │ │
│  │  WS   /agent/ws     (streaming)             │ │
│  │  GET  /tools         (tool list)            │ │
│  │  GET  /health                               │ │
│  └──────────┬──────────────────────────────────┘ │
│             │                                    │
│  ┌──────────▼──────────────────────────────────┐ │
│  │  Agent Runner (runner.py)                   │ │
│  │  - セッション管理                             │ │
│  │  - ストリーミング制御                          │ │
│  │  - PROV-DM記録のフック                        │ │
│  └──────────┬──────────────────────────────────┘ │
│             │                                    │
│  ┌──────────▼──────────────────────────────────┐ │
│  │  mcp-agent Adapter (adapter.py)             │ │
│  │  - MCPApp lifecycle                         │ │
│  │  - Agent + AugmentedLLM setup               │ │
│  │  - ★ここだけmcp-agent依存                    │ │
│  └──────────┬──────────┬───────────────────────┘ │
│             │          │                         │
│         ┌───▼───┐  ┌───▼────────┐               │
│         │LiteLLM│  │MCP Servers │               │
│         │ Proxy │  │ (via SSE)  │               │
│         └───┬───┘  └────────────┘               │
│             │                                    │
│         ┌───▼───────────┐                        │
│         │さくらAI Engine │                        │
│         └───────────────┘                        │
│                                                  │
│  ┌─ PostgreSQL ────────────────────────────────┐ │
│  │  PROV-DM provenance records                 │ │
│  └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

## 3. エージェントループの詳細

```python
# 擬似コード: runner.py
async def run_agent(user_message: str, session: Session):
    # 1. プロンプト構築
    instruction = build_instruction(
        base_prompt,        # Layer 1: 我々が提供
        lab_config,         # Layer 2: ユーザーのラボ設定
    )
    
    # 2. 利用可能ツール取得（Crucible auto-discovery）
    servers = await crucible_discovery.get_servers()
    
    # 3. mcp-agent経由でエージェント実行
    result = await adapter.run(
        instruction=instruction,
        message=user_message,
        server_names=servers,
    )
    
    # 4. PROV-DM記録
    await provenance.log_agent_run(session, result)
    
    return result
```

### tool_useループ（mcp-agent内部）

```
User message
    ↓
[LLM call] ← system prompt + tool definitions
    ↓
Response: text + tool_use?
    ├─ text only → stream to client, END
    └─ tool_use → 
        ├─ Call MCP server (SSE)
        ├─ Get result
        ├─ Log to PROV-DM
        └─ Feed result back to LLM → LOOP
```

## 4. Crucible Auto-Discovery

```python
# discovery.py
async def get_servers() -> list[ServerConfig]:
    """Crucible APIから稼働中のMCPサーバー一覧を取得し、
    mcp-agentのserver_names形式に変換する"""
    response = await httpx.get(f"{CRUCIBLE_API_URL}/api/servers")
    servers = response.json()
    return [
        ServerConfig(
            name=s["name"],
            url=s["sse_endpoint"],  # e.g. http://crucible:9001/sse
            transport="sse",
        )
        for s in servers
        if s["status"] == "running"
    ]
```

Crucibleが利用不可の場合、`mcp_agent.config.yaml`に直書きされたサーバー設定にフォールバック。

## 5. PROV-DM記録スキーマ

```
prov:Entity (実験データ)
    ↑ prov:wasGeneratedBy
prov:Activity (エージェント行動)
    ↑ prov:wasAssociatedWith
prov:Agent (mcp-agent / researcher / MCP tool)
```

各tool_useステップが1つのActivityとなり、入力Entity→Activity→出力Entityのチェーンでデータの来歴を追跡する。

## 6. LiteLLM設定

```yaml
# litellm_config.yaml
model_list:
  - model_name: sakura
    litellm_params:
      model: openai/sakura-model-name
      api_base: ${SAKURA_AI_API_BASE}
      api_key: ${SAKURA_AI_API_KEY}
```

mcp-agentは`OpenAIAugmentedLLM`を使うので、LiteLLMのOpenAI互換エンドポイント（`http://litellm:4000`）をapi_baseとして指定するだけ。

## 7. リスク対策の設計

### mcp-agent破壊的変更時

`adapter.py`のみを差し替える。代替実装:

```python
# adapter_fallback.py （mcp-agentなし版、約300行）
from mcp import ClientSession
from mcp.client.sse import sse_client

async def run(instruction, message, server_names):
    # MCP Python SDKで直接SSE接続
    # httpxでLLM呼び出し
    # tool_useループを自前実装
    ...
```

### LiteLLM障害時

環境変数変更のみ:
```
# Before (LiteLLM経由)
LITELLM_API_BASE=http://litellm:4000

# After (直接接続)
LITELLM_API_BASE=https://your-sakura-endpoint
```
