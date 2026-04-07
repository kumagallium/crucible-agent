"""Crucible Registry からのツール自動検出

MCP サーバー / CLI・Library / Skill の 3 種すべてを検出する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from crucible_agent.config import settings

logger = logging.getLogger(__name__)


# --- データクラス ---


@dataclass
class DiscoveredServer:
    """検出された MCP サーバー"""

    name: str
    display_name: str
    description: str
    url: str  # SSE/MCP エンドポイント URL
    transport: str  # "sse" or "streamable-http"
    status: str


@dataclass
class CliExecution:
    """CLI 実行情報（Registry の cli_execution フィールドに対応）"""

    run_command: str = ""  # 実行コマンドテンプレート（例: "arxiv-mcp --query {query}"）
    output_format: str = ""  # 出力形式（例: "json", "text"）
    install_command: str = ""  # インストールコマンド（例: "pip install arxiv-mcp"）


@dataclass
class DiscoveredCliLibrary:
    """検出された CLI/Library ツール"""

    name: str
    display_name: str
    description: str
    install_command: str  # 後方互換: cli_execution.install_command のフォールバック
    github_url: str
    cli_execution: CliExecution = field(default_factory=CliExecution)


@dataclass
class DiscoveredSkill:
    """検出された Skill"""

    name: str
    display_name: str
    description: str
    github_url: str
    content: str = ""  # スキル定義のマークダウン本文


@dataclass
class AllTools:
    """3 種のツールをまとめた検出結果"""

    servers: list[DiscoveredServer] = field(default_factory=list)
    cli_libraries: list[DiscoveredCliLibrary] = field(default_factory=list)
    skills: list[DiscoveredSkill] = field(default_factory=list)


# --- Registry API 取得（共通） ---


async def _fetch_registry() -> list[dict]:
    """Registry API からツール一覧の生 JSON を取得する"""
    if not settings.crucible_api_url:
        logger.debug("CRUCIBLE_API_URL が未設定のため検出をスキップ")
        return []

    headers: dict[str, str] = {}
    if settings.crucible_api_key:
        headers["X-API-Key"] = settings.crucible_api_key

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.crucible_api_url}/api/servers",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.warning("Crucible Registry に接続できません (%s)", settings.crucible_api_url)
        return []


# --- パース ---


def _parse_mcp_server(s: dict, crucible_host: str) -> DiscoveredServer | None:
    """JSON → DiscoveredServer（running のみ）"""
    if s.get("status") != "running":
        return None

    endpoint_path = s.get("endpoint_path", "/sse")
    static_ip = s.get("static_ip")
    port = s.get("port", 8000)

    # トランスポート判定: /mcp → streamable-http, /sse → sse
    transport = "streamable-http" if endpoint_path == "/mcp" else "sse"

    if settings.crucible_mcp_direct and static_ip:
        # 同一ホスト: Docker 内部 IP + 内部ポート (8000) で直接接続
        url = f"http://{static_ip}:8000{endpoint_path}"
    else:
        # デフォルト: Registry ホスト + 公開ポート（クロスホストでも到達可能）
        url = f"http://{crucible_host}:{port}{endpoint_path}"

    return DiscoveredServer(
        name=s["name"],
        display_name=s.get("display_name", s["name"]),
        description=s.get("description", ""),
        url=url,
        transport=transport,
        status=s["status"],
    )


def _parse_cli_library(s: dict) -> DiscoveredCliLibrary | None:
    """JSON → DiscoveredCliLibrary（registered のみ）"""
    if s.get("status") not in ("registered", "running"):
        return None

    # cli_execution: Registry の構造化フィールド
    raw_exec = s.get("cli_execution") or {}
    cli_exec = CliExecution(
        run_command=raw_exec.get("run_command", ""),
        output_format=raw_exec.get("output_format", ""),
        install_command=raw_exec.get("install_command", ""),
    )

    # cli_execution.install_command → トップレベルの順でフォールバック
    install_cmd = cli_exec.install_command or s.get("install_command", "")

    return DiscoveredCliLibrary(
        name=s["name"],
        display_name=s.get("display_name", s["name"]),
        description=s.get("description", ""),
        install_command=install_cmd,
        github_url=s.get("github_url", ""),
        cli_execution=cli_exec,
    )


def _parse_skill(s: dict) -> DiscoveredSkill | None:
    """JSON → DiscoveredSkill（registered のみ）"""
    if s.get("status") not in ("registered", "running"):
        return None
    return DiscoveredSkill(
        name=s["name"],
        display_name=s.get("display_name", s["name"]),
        description=s.get("description", ""),
        github_url=s.get("github_url", ""),
        content=s.get("content", ""),
    )


# --- 公開 API ---


async def discover_all_tools() -> AllTools:
    """Crucible Registry から 3 種のツールをすべて検出する"""
    raw = await _fetch_registry()
    crucible_host = urlparse(settings.crucible_api_url or "").hostname or "localhost"

    result = AllTools()
    for s in raw:
        tool_type = s.get("tool_type", "mcp_server")
        if tool_type == "mcp_server":
            srv = _parse_mcp_server(s, crucible_host)
            if srv:
                result.servers.append(srv)
        elif tool_type == "cli_library":
            cli = _parse_cli_library(s)
            if cli:
                result.cli_libraries.append(cli)
        elif tool_type == "skill":
            skill = _parse_skill(s)
            if skill:
                result.skills.append(skill)

    logger.info(
        "Crucible からツールを検出: MCP=%d, CLI/Library=%d, Skill=%d",
        len(result.servers),
        len(result.cli_libraries),
        len(result.skills),
    )
    return result


async def discover_servers() -> list[DiscoveredServer]:
    """Crucible Registry API から稼働中の MCP サーバー一覧を取得する

    互換ラッパー: 既存コードが使用している。
    """
    all_tools = await discover_all_tools()
    return all_tools.servers
