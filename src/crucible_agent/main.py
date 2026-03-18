"""FastAPI エントリポイント"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from crucible_agent import __version__
from crucible_agent.api.routes import router
from crucible_agent.config import settings
from crucible_agent.provenance.recorder import init_db

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
