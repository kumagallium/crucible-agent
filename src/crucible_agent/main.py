"""FastAPI エントリポイント"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from crucible_agent import __version__
from crucible_agent.api.routes import router
from crucible_agent.config import settings
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
    yield


app = FastAPI(
    title="Crucible Agent",
    description="AI agent runtime connecting frontends to MCP servers via LLM",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(router)

# Chat UI（/ でアクセス可能）
if CHAT_UI_DIR.exists():
    @app.get("/", include_in_schema=False)
    async def chat_ui():
        return FileResponse(CHAT_UI_DIR / "index.html")

    app.mount("/chat-ui", StaticFiles(directory=str(CHAT_UI_DIR)), name="chat-ui")
