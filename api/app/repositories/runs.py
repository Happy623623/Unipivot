"""실행 조회(GET /runs/{id}, API 명세 11장). 실행·단계(tool_calls)와 작업별 결과.

결과는 따로 저장하지 않고 실행이 만든 행에서 다시 읽는다. 준비하기는 그 실행의 계획(prep_plans)·서류·할 일이고,
포스터 추출과 LMS 동기화는 그 실행의 도구 출력(`tool_calls.output`)이다. 동기화 수는 그 실행만의 사실이라
다른 표에서 다시 셀 수 없다(과제 표에는 어느 실행이 넣었는지 적지 않는다).
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection
from pydantic import ValidationError

from app.db import get_conn
from app.eligibility import KST
from app.schemas.lms import SAVE_TOOL, LmsSyncResult, SyncCounts
from app.schemas.opportunities import DocumentItem, ProcessStep
from app.schemas.posters import (
    EXTRACT_LABEL,
    DuplicateCandidate,
    PosterDraft,
    PosterExtractResult,
)
from app.schemas.posters import (
    EXTRACT_TOOL as POSTER_TOOL,
)
from app.schemas.prepare import PrepareResult, PrepTask, RunError

# 준비하기 단계 이름(화면의 처리 과정). 정해진 순서로 도는 단계라 chosen_by는 pipeline이다.
# 마감일 캘린더 등록은 준비하기 단계가 아니라 따로 부르는 API다(POST /calendar/events, F-32)
PREPARE_LABELS = {
    "get_document_guide": "필요 서류 확인",
    "build_prep_plan": "마감일에서 거꾸로 일정 짜기",
}
# 포스터 추출 단계 이름. Vision 한 번이라 단계도 하나다(app/posters/service.py)
POSTER_LABELS = {POSTER_TOOL: EXTRACT_LABEL}
# LMS 동기화 단계 이름(F-50 연결·F-51 동기화, app/lms/sync.py)
LMS_LABELS = {
    "check_lms_token": "토큰 확인",
    "fetch_lms_courses": "수강 과목 받기",
    "fetch_lms_assignments": "과제·제출 받기",
    SAVE_TOOL: "바뀐 것 저장",
}
FAILED_MESSAGE = "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요."
# 코드를 남기지 못한 실패에 보여 줄 문구. 작업마다 할 말이 다르다(무엇을 하면 되는지)
FAILED_MESSAGES = {
    "lms_sync": "LMS 자료를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.",
}
_CODED = re.compile(r"^([A-Z][A-Z_]+): (.+)$", re.S)  # agent_log.error_text의 "코드: 문구"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunRow:
    id: str
    user_id: str | None
    trigger_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    latency_ms: int | None
    error_message: str | None

    def error(self) -> RunError | None:
        """학생에게 보여 줄 실패 이유. ApiError로 남긴 것만 그대로 보여 주고 나머지는 내부 기록이다."""
        if self.status != "failed":
            return None
        if self.error_message and (match := _CODED.match(self.error_message)):
            return RunError(code=match.group(1), message=match.group(2))
        message = FAILED_MESSAGES.get(self.trigger_type, FAILED_MESSAGE)
        return RunError(code="INTERNAL_ERROR", message=message)


def _label(tool_name: str) -> str:
    """화면에 보이는 단계 이름. 작업마다 표가 다르고, 표에 없으면 도구 이름 그대로다."""
    return (
        PREPARE_LABELS.get(tool_name)
        or POSTER_LABELS.get(tool_name)
        or LMS_LABELS.get(tool_name)
        or tool_name
    )


class RunRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def run(self, run_id: str) -> RunRow | None:
        row = await (
            await self.conn.execute(
                "select id, user_id, trigger_type, status::text as status, started_at, finished_at,"
                " latency_ms, error_message from agent_runs where id = %s",
                (run_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return RunRow(
            id=str(row["id"]),
            user_id=str(row["user_id"]) if row["user_id"] else None,
            trigger_type=row["trigger_type"],
            status=row["status"],
            started_at=_kst(row["started_at"]),
            finished_at=_kst(row["finished_at"]),
            latency_ms=row["latency_ms"],
            error_message=row["error_message"],
        )

    async def steps(self, run_id: str) -> list[ProcessStep]:
        rows = await (
            await self.conn.execute(
                "select seq, tool_name, status::text as status, latency_ms from tool_calls"
                " where run_id = %s order by seq, id",
                (run_id,),
            )
        ).fetchall()
        return [
            ProcessStep(
                seq=row["seq"],
                tool=row["tool_name"],
                label=_label(row["tool_name"]),
                status=row["status"],
                latency_ms=row["latency_ms"],
                chosen_by="pipeline",
                note=None,
            )
            for row in rows
        ]

    async def prepare_result(self, user_id: str, run_id: str) -> PrepareResult | None:
        """그 실행이 만든 내 계획. 없으면(지워짐) None."""
        plan = await (
            await self.conn.execute(
                "select id, opportunity_id from prep_plans where agent_run_id = %s and user_id = %s",
                (run_id, user_id),
            )
        ).fetchone()
        if plan is None:
            return None
        params: dict[str, Any] = {"plan": plan["id"], "oid": plan["opportunity_id"]}
        documents = await (
            await self.conn.execute(
                "select d.id::text as id, d.name, d.issuer, d.how_to, d.lead_days, d.effort_minutes,"
                " d.form_url, coalesce(d.is_required, true) as is_required,"
                " t.id::text as task_id, t.is_done"
                " from opportunity_documents d left join planner_tasks t"
                " on t.prep_plan_id = %(plan)s and t.document_id = d.id"
                " where d.opportunity_id = %(oid)s"
                " order by coalesce(d.is_required, true) desc, d.name, d.id",
                params,
            )
        ).fetchall()
        tasks = await (
            await self.conn.execute(
                "select id::text as id, title, due_date, document_id::text as document_id"
                " from planner_tasks where prep_plan_id = %(plan)s order by sort_order, due_date, id",
                params,
            )
        ).fetchall()
        return PrepareResult(
            prep_plan_id=str(plan["id"]),
            documents=[DocumentItem(**row) for row in documents],
            tasks=[PrepTask(**row) for row in tasks],
            # 마감일 캘린더는 따로 등록한다(POST /calendar/events). 준비하기 결과에는 담지 않는다
            calendar_event=None,
            calendar_error=None,
        )

    async def lms_sync_result(self, user_id: str, run_id: str) -> LmsSyncResult | None:
        """그 동기화가 바꾼 것(명세 8장). 저장 단계가 없으면(F-50 연결 실행 등) None이다."""
        row = await (
            await self.conn.execute(
                "select t.output from tool_calls t join agent_runs r on r.id = t.run_id"
                " where t.run_id = %s and r.user_id = %s and t.tool_name = %s"
                " order by t.seq desc, t.id desc limit 1",
                (run_id, user_id, SAVE_TOOL),
            )
        ).fetchone()
        output = row["output"] if row else None
        if not isinstance(output, dict):
            return None
        try:
            return LmsSyncResult(
                courses=int(output["courses"]),
                assignments=SyncCounts(
                    new=int(output["new"]),
                    due_changed=int(output["due_changed"]),
                    submitted=int(output["submitted"]),
                ),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("동기화 결과 모양이 달라 읽지 못했어요: run %s", run_id)
            return None

    async def poster_result(self, user_id: str, run_id: str) -> PosterExtractResult | None:
        """그 실행이 만든 초안. 기록이 지워졌거나 모양이 달라졌으면 None이다."""
        row = await (
            await self.conn.execute(
                "select t.output from tool_calls t join agent_runs r on r.id = t.run_id"
                " where t.run_id = %s and r.user_id = %s and t.tool_name = %s"
                " order by t.seq desc, t.id desc limit 1",
                (run_id, user_id, POSTER_TOOL),
            )
        ).fetchone()
        output = row["output"] if row else None
        if not isinstance(output, dict) or "draft" not in output:
            return None
        try:
            draft = PosterDraft.model_validate(output["draft"])
        except ValidationError:
            logger.warning("포스터 초안 모양이 달라 읽지 못했어요: run %s", run_id)
            return None
        candidate = output.get("duplicate_candidate")
        duplicate = None
        if isinstance(candidate, dict):
            try:
                duplicate = DuplicateCandidate.model_validate(candidate)
            except ValidationError:
                duplicate = None
        return PosterExtractResult(draft=draft, duplicate_candidate=duplicate)


def _kst(value: datetime | None) -> datetime | None:
    return value.astimezone(KST) if value else None


def get_run_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> RunRepository:
    return RunRepository(conn)


RunRepoDep = Annotated[RunRepository, Depends(get_run_repo)]
