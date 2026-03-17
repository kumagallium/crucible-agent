# API Specification: Crucible Agent

Base URL: `http://localhost:8090`

## POST /agent/run

同期的にエージェントを実行し、結果を返す。短いタスク向け。

### Request

```json
{
  "message": "NMC811正極のXRDパターンを解析して",
  "session_id": "optional-session-uuid",
  "lab_config_id": "optional-lab-config-id",
  "options": {
    "max_turns": 10,
    "require_approval": false,
    "model": "sakura"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| message | string | yes | ユーザーのメッセージ |
| session_id | string | no | 会話セッションID。省略時は新規作成 |
| lab_config_id | string | no | ラボ設定ID（Layer 2プロンプト選択） |
| options.max_turns | int | no | 最大ループ回数（default: 10） |
| options.require_approval | bool | no | tool実行前に承認を求めるか（default: false） |
| options.model | string | no | 使用モデル名（default: 環境変数LLM_MODEL） |

### Response

```json
{
  "session_id": "uuid",
  "message": "XRDパターンの解析結果です。主相はNMC811...",
  "tool_calls": [
    {
      "tool_name": "xrd-analyzer",
      "server": "crucible-xrd",
      "input": {"file": "sample_001.csv"},
      "output": {"phases": ["NMC811", "Li2CO3"]},
      "duration_ms": 1200
    }
  ],
  "provenance_id": "prov-uuid",
  "token_usage": {
    "input_tokens": 1500,
    "output_tokens": 800,
    "total_tokens": 2300
  }
}
```

## WS /agent/ws

WebSocketでストリーミング応答。ELNチャットパネル向け。

### Connection

```
ws://localhost:8090/agent/ws?session_id=optional-uuid
```

### Client → Server messages

```json
{
  "type": "message",
  "content": "このデータを解析して",
  "lab_config_id": "optional"
}
```

```json
{
  "type": "approval",
  "tool_call_id": "tc-uuid",
  "approved": true
}
```

### Server → Client messages

```json
{
  "type": "text_delta",
  "content": "XRDパターンを"
}
```

```json
{
  "type": "tool_start",
  "tool_call_id": "tc-uuid",
  "tool_name": "xrd-analyzer",
  "server": "crucible-xrd",
  "input": {"file": "sample_001.csv"}
}
```

```json
{
  "type": "tool_end",
  "tool_call_id": "tc-uuid",
  "output": {"phases": ["NMC811"]},
  "duration_ms": 1200
}
```

```json
{
  "type": "approval_request",
  "tool_call_id": "tc-uuid",
  "tool_name": "file-delete",
  "input": {"path": "/data/raw/old.csv"},
  "message": "このファイルを削除してよいですか？"
}
```

```json
{
  "type": "done",
  "provenance_id": "prov-uuid",
  "token_usage": {"input_tokens": 1500, "output_tokens": 800}
}
```

```json
{
  "type": "error",
  "message": "MCP server connection failed",
  "code": "MCP_CONNECTION_ERROR"
}
```

## GET /tools

Crucibleから検出した利用可能ツール一覧を返す。

### Response

```json
{
  "tools": [
    {
      "name": "xrd-analyzer",
      "server": "crucible-xrd",
      "description": "Analyze XRD patterns and identify crystal phases",
      "source": "crucible",
      "input_schema": {
        "type": "object",
        "properties": {
          "file": {"type": "string", "description": "Path to XRD data file"}
        },
        "required": ["file"]
      }
    },
    {
      "name": "literature-survey",
      "server": "dify-lit-survey",
      "description": "Search PubMed and summarize recent papers",
      "source": "dify",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "max_results": {"type": "integer", "default": 10}
        },
        "required": ["query"]
      }
    }
  ],
  "sources": {
    "crucible": {"url": "http://crucible-api:8080", "status": "connected", "server_count": 5},
    "config": {"file": "mcp_agent.config.yaml", "server_count": 1}
  }
}
```

## GET /health

### Response

```json
{
  "status": "healthy",
  "components": {
    "agent": "ok",
    "litellm": "ok",
    "database": "ok",
    "crucible": "ok"
  },
  "version": "0.1.0"
}
```

## POST /lab-config

ラボ設定を登録・更新する（Layer 2プロンプト用）。

### Request

```json
{
  "lab_name": "Tanaka Lab",
  "instruments": [
    {"name": "Bruker D8 Advance", "type": "XRD", "notes": "Cu-Kα, 40kV/40mA"},
    {"name": "JEOL JSM-7800F", "type": "SEM", "notes": "FE-SEM with EDS"}
  ],
  "protocols": [
    {"name": "XRD sample prep", "steps": "Cut 10mm disc, dry 120°C 2h vacuum"},
    {"name": "Naming convention", "rule": "YYYYMMDD_SampleID_Method.csv"}
  ],
  "custom_instructions": "測定前に必ずキャリブレーションを実施すること"
}
```

### Response

```json
{
  "id": "lab-config-uuid",
  "lab_name": "Tanaka Lab",
  "created_at": "2026-03-16T10:00:00Z"
}
```
