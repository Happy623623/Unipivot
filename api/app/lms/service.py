"""LearningX 연결 (F-50). 토큰을 확인하고 암호화해 저장한 뒤 수강 과목을 받아 둔다.

순서(명세 9장): `GET /api/v1/users/self`로 확인 → 과목 목록 → 저장. 두 호출 모두 실행 하나(`lms_sync`)
안에서 도구로 기록한다(api/CLAUDE.md: 외부 호출은 agent_run 안에서만). 확인에 실패하면 아무것도 저장하지
않고 422 `LMS_TOKEN_INVALID`다(실행은 실패로 남는다). 과목 목록을 읽지 못하면 502 `LMS_API_ERROR`이고 역시 저장하지 않는다
(과목을 못 읽으면 과제·자료도 못 읽어서 연결해 둘 뜻이 없다).

토큰은 암호화해서만 저장하고, 응답·로그·`tool_calls.input`에 넣지 않는다. 화면에는 끝 4자리만 간다.
과제·주차 항목·공지 동기화는 F-51·F-52다. 여기서는 과목 목록까지만 받는다.
"""

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends

from app.agent_log import LogConnect, agent_run
from app.config import Settings, get_settings
from app.crypto import encrypt
from app.db import get_log_connect
from app.errors import ApiError
from app.lms.client import LearningXClient, LearningXError
from app.lms.parse import is_canvas_id
from app.repositories.lms import LmsRepoDep, LmsRepository
from app.schemas.lms import ConnectResult

logger = logging.getLogger(__name__)

NOT_CONNECTED = (
    "LearningX를 연결해 주세요."  # 404 LMS_NOT_CONNECTED의 문구(라우터·동기화가 함께 쓴다)
)
TOKEN_INVALID = "토큰을 확인할 수 없어요. 복사할 때 앞뒤 공백이 들어갔는지 확인해 주세요."
TOKEN_EXPIRED = "토큰이 만료되었거나 삭제되었어요."
API_ERROR = "LearningX가 응답하지 않아요. 잠시 후 다시 시도해 주세요."
# 학생 등록인 과목만 본다(청강·조교 과목은 과제가 내 것이 아니다)
STUDENT = "student"
OPEN_STATES = ("available", "completed")  # 그 밖(unpublished 등)은 아직 열지 않은 과목이다


def student_courses(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """내가 학생으로 듣는, 열려 있는 과목만. 2026-10-16 녹화의 8과목은 모두 student·available이었다."""
    mine = []
    for course in courses:
        enrollments = course.get("enrollments") or []
        is_student = any(
            isinstance(one, dict) and one.get("type") == STUDENT for one in enrollments
        )
        if (
            is_student
            and course.get("workflow_state") in OPEN_STATES
            and is_canvas_id(course.get("id"))
        ):
            mine.append(course)
    return mine


class LmsService:
    def __init__(
        self,
        repo: LmsRepository,
        client: LearningXClient,
        *,
        encryption_key: str,
        log_connect: LogConnect,
    ) -> None:
        self.repo = repo
        self.client = client
        self.key = encryption_key
        self.log_connect = log_connect

    async def connect(self, user_id: str, token: str, now: datetime) -> ConnectResult:
        async with agent_run(self.log_connect, trigger="lms_sync", user_id=user_id) as run:
            async with run.tool("check_lms_token") as call:
                me = await self._check(token)
                call.output = {"ok": True}  # 사용자 번호·토큰은 기록하지 않는다
            async with run.tool("fetch_lms_courses") as call:
                courses = student_courses(await self._courses(token))
                call.output = {"courses": len(courses)}
            saved = await self.repo.save_courses(user_id, courses, now=now)
            await self.repo.save_connection(
                user_id,
                token=encrypt(token, self.key),
                last4=token[-4:],
                canvas_user_id=me.get("id") if isinstance(me.get("id"), int) else None,
                now=now,
            )
            run_id = run.id
        return ConnectResult(
            status="active", token_last4=token[-4:], courses=saved, first_sync_run_id=run_id
        )

    async def _check(self, token: str) -> dict[str, Any]:
        try:
            return await self.client.me(token)
        except LearningXError as exc:
            logger.info("LearningX 토큰 확인 실패: status %s", exc.status)
            raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_INVALID) from exc

    async def _courses(self, token: str) -> list[dict[str, Any]]:
        try:
            return await self.client.courses(token)
        except LearningXError as exc:
            if exc.unauthorized:
                raise ApiError(422, "LMS_TOKEN_INVALID", TOKEN_EXPIRED) from exc
            logger.warning("LearningX 과목 목록 실패: status %s", exc.status)
            raise ApiError(502, "LMS_API_ERROR", API_ERROR) from exc


def get_lms_service(
    repo: LmsRepoDep,
    settings: Annotated[Settings, Depends(get_settings)],
    log_connect: Annotated[LogConnect, Depends(get_log_connect)],
) -> LmsService:
    return LmsService(
        repo,
        LearningXClient(api_base=settings.lms_api_base),
        encryption_key=settings.token_encryption_key,
        log_connect=log_connect,
    )


LmsServiceDep = Annotated[LmsService, Depends(get_lms_service)]
