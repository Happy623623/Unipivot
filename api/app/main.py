import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import auth_settings_problem
from app.background import TaskRunner
from app.config import Settings, get_settings
from app.db import create_pools
from app.errors import UnhandledErrorMiddleware, register_error_handlers
from app.logging_redact import install_log_redaction
from app.routers import (
    auth,
    calendar,
    events,
    files,
    health,
    internal,
    lms,
    me,
    meta,
    notifications,
    opportunities,
    planner,
    posters,
    push,
    runs,
    syllabi,
)
from app.scheduler import Scheduler, app_jobs
from app.uploads.storage import storage_settings_problem

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # 로그인 설정이 틀렸으면 첫 요청을 기다리지 않고 시작할 때 알린다(.env를 고치면 서버를 다시 켠다)
    if problem := auth_settings_problem(settings):
        logger.warning("로그인 설정 확인: %s", problem)
    # 파일 업로드(F-13)·공지 첨부 저장(F-54)은 Supabase Storage가 있어야 한다. 비었으면 첫 업로드에서
    # 502가 나고, 동기화는 공지 첨부를 받지 않는다. 키 모양이 틀렸으면(publishable key 등) 올릴 때마다
    # 거절된다
    if problem := storage_settings_problem(settings):
        logger.warning("파일 저장소 설정 확인: %s", problem)
    app.state.pool = app.state.log_pool = None
    if settings.database_url:
        app.state.pool, app.state.log_pool = create_pools(settings.database_url)
        await app.state.pool.open()
        await app.state.log_pool.open()
    # 정기 작업(알림 발송·LMS 동기화·알림 예약). 끄면 /internal/jobs/*로만 돈다
    app.state.scheduler = None
    if settings.scheduler_enabled and app.state.pool is None:
        logger.warning(
            "SCHEDULER_ENABLED가 켜져 있지만 DATABASE_URL이 없어 정기 작업을 띄우지 않아요"
        )
    elif settings.scheduler_enabled:
        app.state.scheduler = Scheduler(app_jobs(app))
        app.state.scheduler.start()
    try:
        yield
    finally:
        # 뜨는 중이나 도는 중에 터져도 여기를 지난다 — 안 닫으면 DB 풀의 일꾼이 남아 서버가 안 꺼진다
        # 새 일을 더 띄우지 않게 스케줄러를 먼저 멈춘다
        if app.state.scheduler is not None:
            await app.state.scheduler.stop()
        # 돌던 준비하기를 잠깐 기다린다(못 끝내면 다음 요청이 멈춘 실행으로 보고 다시 만든다)
        await app.state.runner.drain(timeout=10)
        for pool in (app.state.pool, app.state.log_pool):
            if pool is not None:
                await pool.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    install_log_redaction()  # 로그에서 토큰을 가린다 (요청 처리 전에 건다)
    # uvicorn은 자기 로거만 꾸민다. 그대로 두면 앱이 남기는 info 로그(정기 작업 결과 등)가 사라진다
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")
    settings = settings or get_settings()
    app = FastAPI(title="UNIPIVOT API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.runner = TaskRunner()  # 요청이 끝난 뒤 이어서 할 일(준비하기 실행)
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
    for router in (
        auth.router,
        calendar.router,
        files.router,
        internal.router,
        lms.router,
        me.router,
        meta.router,
        notifications.router,
        events.router,
        opportunities.router,
        planner.router,
        posters.router,
        push.router,
        runs.router,
        syllabi.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
