"""API 명세 13장 에러 형식: {"error": {"code", "message", "details"}}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """라우터·서비스에서 던지는 유일한 에러. code는 명세 13장 표에 있는 것만 쓴다."""

    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


_HTTP_CODES = {
    401: ("UNAUTHORIZED", "로그인이 필요해요."),
    403: ("FORBIDDEN", "권한이 없어요."),
    404: ("NOT_FOUND", "대상을 찾을 수 없어요."),
    405: ("METHOD_NOT_ALLOWED", "지원하지 않는 요청이에요."),
    429: ("RATE_LIMITED", "요청이 많아요. 잠시 후 다시 시도해 주세요."),
}


class UnhandledErrorMiddleware:
    """처리하지 못한 예외에 500 INTERNAL_ERROR 응답을 CORSMiddleware 안쪽에서 보낸다.

    Starlette는 이런 예외를 가장 바깥(CORSMiddleware 밖)에서 처리해서 500 응답에 CORS 헤더가 없다.
    그러면 브라우저는 응답을 읽지 못하고 네트워크 오류로 본다. 응답을 보낸 뒤 예외는 그대로 다시 던져서
    바깥 처리(handle_unexpected의 로그, 서버 로그)는 전과 같다. 바깥은 응답이 시작된 것을 보고 다시 보내지 않는다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception:
            if not started:  # 이미 응답을 보내기 시작했으면 바꿀 수 없다
                body = error_body("INTERNAL_ERROR", "잠시 후 다시 시도해 주세요.")
                await JSONResponse(status_code=500, content=body)(scope, receive, send)
            raise


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content=error_body(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {
            ".".join(str(part) for part in error["loc"][1:]) or "body": error["msg"]
            for error in exc.errors()
        }
        body = error_body("VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields})
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("HTTP_ERROR", str(exc.detail)))
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("처리하지 못한 예외", exc_info=exc)
        body = error_body("INTERNAL_ERROR", "잠시 후 다시 시도해 주세요.")
        return JSONResponse(status_code=500, content=body)
