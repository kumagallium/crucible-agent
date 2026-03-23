"""FastAPI エントリポイント"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from crucible_agent import __version__
from crucible_agent.api.routes import router
from crucible_agent.config import settings
from crucible_agent.profiles.repository import seed_default_profiles
from crucible_agent.provenance.recorder import init_db

CHAT_UI_DIR = Path(__file__).parent.parent.parent / "chat-ui"

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーション起動時の初期化"""
    await init_db()
    await seed_default_profiles()
    yield


app = FastAPI(
    title="Crucible Agent",
    description="AI agent runtime connecting frontends to MCP servers via LLM",
    version=__version__,
    lifespan=lifespan,
)

# CORS: 外部フロントエンド（provnote 等）からの API アクセスを許可
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# gzip 圧縮: 500バイト以上のレスポンスを自動圧縮（モバイル回線の高速化）
app.add_middleware(GZipMiddleware, minimum_size=500)

app.include_router(router)

# Chat UI（/ でアクセス可能）
if CHAT_UI_DIR.exists():
    @app.get("/", include_in_schema=False)
    async def chat_ui():
        return FileResponse(CHAT_UI_DIR / "index.html")

    # Service Worker をルートスコープで配信（PWA 用）
    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(
            CHAT_UI_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    app.mount("/chat-ui", StaticFiles(directory=str(CHAT_UI_DIR)), name="chat-ui")
