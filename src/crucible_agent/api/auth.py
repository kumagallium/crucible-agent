"""API キー認証 — X-API-Key ヘッダーによる共有キー認証"""

import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from crucible_agent.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Depends(_api_key_header),
) -> None:
    """API キーを検証する。agent_api_key が未設定の場合はスキップ（開発用）"""
    if not settings.agent_api_key:
        return
    if api_key is None or not hmac.compare_digest(api_key, settings.agent_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
