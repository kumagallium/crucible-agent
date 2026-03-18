"""Crucible Registry からの MCP サーバー自動検出"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from crucible_agent.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredServer:
    """検出された MCP サーバー"""

    name: str
    display_name: str
    description: str
    url: str  # SSE/MCP エンドポイント URL
    transport: str  # "sse" or "streamable-http"
    status: str


async def discover_servers() -> list[DiscoveredServer]:
    """Crucible Registry API から稼働中の MCP サーバー一覧を取得する

    Crucible に接続できない場合は空リストを返す（フォールバック: mcp_agent.config.yaml）
    """
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
            servers = resp.json()
    except Exception:
        logger.warning("Crucible Registry に接続できません (%s)", settings.crucible_api_url)
        return []

    discovered: list[DiscoveredServer] = []
    for s in servers:
        if s.get("status") != "running":
            continue

        endpoint_path = s.get("endpoint_path", "/sse")
        static_ip = s.get("static_ip", "")
        port = s.get("port", 8000)

        # トランスポート判定: /mcp → streamable-http, /sse → sse
        transport = "streamable-http" if endpoint_path == "/mcp" else "sse"
        url = f"http://{static_ip}:{port}{endpoint_path}"

        discovered.append(
            DiscoveredServer(
                name=s["name"],
                display_name=s.get("display_name", s["name"]),
                description=s.get("description", ""),
                url=url,
                transport=transport,
                status=s["status"],
            )
        )

    logger.info("Crucible から %d 台の MCP サーバーを検出", len(discovered))
    return discovered
