import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import auth_settings_problem
from app.config import Settings, get_settings
from app.db import create_pools
from app.errors import UnhandledErrorMiddleware, register_error_handlers
from app.logging_redact import install_log_redaction
from app.routers import auth, events, health, me, meta, opportunities

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # 로그인 설정이 틀렸으면 첫 요청을 기다리지 않고 시작할 때 알린다(.env를 고치면 서버를 다시 켠다)
    if problem := auth_settings_problem(settings):
        logger.warning("로그인 설정 확인: %s", problem)
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
    # 나중에 추가한 미들웨어가 바깥이다. 예외로 생긴 500에도 CORS 헤더가 붙게 CORS를 바깥에 둔다
    app.add_middleware(UnhandledErrorMiddleware)
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
