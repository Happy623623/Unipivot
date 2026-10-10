from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import create_pools
from app.errors import register_error_handlers
from app.logging_redact import install_log_redaction
from app.routers import auth, events, health, me, meta, opportunities


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.pool = app.state.log_pool = None
    if settings.database_url:
        app.state.pool, app.state.log_pool = create_pools(settings.database_url)
        await app.state.pool.open()
        await app.state.log_pool.open()
    yield
    for pool in (app.state.pool, app.state.log_pool):
        if pool is not None:
            await pool.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    install_log_redaction()  # 로그에서 토큰을 가린다 (요청 처리 전에 건다)
    settings = settings or get_settings()
    app = FastAPI(title="UNIPIVOT API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    for router in (auth.router, me.router, meta.router, events.router, opportunities.router):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
