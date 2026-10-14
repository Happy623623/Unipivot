"""실행 조회(GET /runs/{id}, API 명세 11장). 실행·단계(tool_calls)와 작업별 결과.

결과는 따로 저장하지 않고 실행이 만든 행에서 다시 읽는다. 준비하기는 그 실행의 계획(prep_plans)·서류·할 일이다.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility import KST
from app.schemas.opportunities import DocumentItem, ProcessStep
from app.schemas.prepare import PrepareResult, PrepTask, RunError

# 준비하기 단계 이름(화면의 처리 과정). 정해진 순서로 도는 단계라 chosen_by는 pipeline이다
PREPARE_LABELS = {
    "get_document_guide": "필요 서류 확인",
    "build_prep_plan": "마감일에서 거꾸로 일정 짜기",
    "create_calendar_event": "캘린더에 마감일 넣기",
}
FAILED_MESSAGE = "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요."
_CODED = re.compile(r"^([A-Z][A-Z_]+): (.+)$", re.S)  # agent_log.error_text의 "코드: 문구"


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
        return RunError(code="INTERNAL_ERROR", message=FAILED_MESSAGE)


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
                label=PREPARE_LABELS.get(row["tool_name"], row["tool_name"]),
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
            calendar_event=None,  # 캘린더 등록(F-32)은 다음 작업
            calendar_error=None,
        )


def _kst(value: datetime | None) -> datetime | None:
    return value.astimezone(KST) if value else None


def get_run_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> RunRepository:
    return RunRepository(conn)


RunRepoDep = Annotated[RunRepository, Depends(get_run_repo)]
