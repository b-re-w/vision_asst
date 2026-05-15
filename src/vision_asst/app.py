"""FastAPI application factory and lifespan that boots the omni engine."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings, get_settings
from .engine.omni_engine import OmniEngineProto, VllmOmniEngine
from .logging_setup import configure_logging
from .routes.http import router as http_router
from .routes.ws import router as ws_router

log = logging.getLogger(__name__)


def create_app(
    *, settings: Settings | None = None, engine: OmniEngineProto | None = None
) -> FastAPI:
    """Build a FastAPI app.

    ``engine`` may be supplied for tests; otherwise the default
    :class:`VllmOmniEngine` is constructed and started in the lifespan.
    """
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = cfg
        app.state.ws_sem = asyncio.Semaphore(cfg.max_concurrent_ws)
        engine_to_run: OmniEngineProto = engine if engine is not None else VllmOmniEngine(settings=cfg)
        app.state.engine = engine_to_run
        try:
            if not engine_to_run.is_ready():
                await engine_to_run.start()
            yield
        finally:
            await engine_to_run.stop()

    app = FastAPI(
        title="Vision Assistant",
        version="0.1.0",
        description="Real-time vision assistant for visually impaired users.",
        lifespan=lifespan,
    )
    app.include_router(http_router)
    app.include_router(ws_router)
    return app


__all__ = ["create_app"]
