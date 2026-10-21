"""강의자료 요약(F-15 축소판)의 SQL. 요약은 `materials`에 파일마다 한 행이다(ERD, 파일이 지워지면 같이 지워진다).

요약할 수 있는 파일은 **내** 강의자료다(직접 올린 것과 공지 첨부로 저장된 것). 요약 상태는 행이 없으면 pending,
요약 중이면 running(그 실행 `agent_run_id`), 끝나면 succeeded·failed다. 실행이 서버 재시작 등으로 멈춰
running으로 남았으면 실패로 본다 — 실행이 끝났거나, 아직 running이지만 STALE_AFTER가 지났으면(요약은 55초 안에
끝나거나 실패한다. 서버를 끄는 사이 끊긴 실행은 running으로 남는다) 다시 요약할 수 있다(준비하기와 같은 방식).
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.eligibility.dates import KST
from app.errors import ApiError
from app.lms.parse import course_name
from app.repositories.opportunities import Cursor, encode_cursor
from app.schemas.materials import MaterialCourse, MaterialDetail, MaterialItem, ProcessedRange

MATERIALS_SCOPE = "materials"  # 목록 cursor의 지문(다른 목록의 cursor를 받지 않는다)
STALE_AFTER = "5 minutes"  # 이만큼 지나도 running인 요약 실행은 멈춘 것으로 본다
# 요약 실행이 아직 도는지(실행 행이 running이고 STALE_AFTER 안). 과목 상세의 자료 상태(lms.py)도 같은 식을 쓴다
RUN_ALIVE = "(r.status::text = 'running' and r.started_at > now() - interval '" + STALE_AFTER + "')"

_FILE = (
    "select f.id::text as file_id, f.storage_path, f.original_name, f.page_count, f.mime_type,"
    " c.id::text as course_id, c.name as course_name,"
    " m.file_id is not null as has_material, m.status::text as status, m.overall_summary,"
    " coalesce(m.over_limit, false) as over_limit, m.total_pages, m.page_start, m.page_end,"
    " m.source_language, m.agent_run_id::text as run_id, m.created_at,"
    " r.status::text as run_status, coalesce(" + RUN_ALIVE + ", false) as run_alive"
    " from files f"
    " left join lms_courses c on c.id = f.lms_course_id and c.user_id = f.user_id"
    " left join materials m on m.file_id = f.id"
    " left join agent_runs r on r.id = m.agent_run_id"
    " where f.user_id = %(uid)s and f.kind = 'lecture_material'"
)


@dataclass(frozen=True)
class MaterialFile:
    """요약할 내 강의자료와 그 요약 상태."""

    file_id: str
    storage_path: str
    page_count: int | None
    mime_type: str | None
    detail: MaterialDetail
    run_status: str | None  # 마지막 요약 실행의 상태(없으면 None)
    run_alive: bool  # 그 실행이 아직 돈다(멈춘 실행은 False)

    @property
    def summarizing(self) -> bool:
        """지금 요약 중이다(실행도 아직 돈다)."""
        return self.detail.status == "running" and self.run_alive

    @property
    def stopped_run(self) -> str | None:
        """멈췄는데 실행 행이 아직 running인 지난 요약 실행(다시 요약할 때 실패로 닫는다)."""
        if self.run_status == "running" and not self.run_alive:
            return self.detail.run_id
        return None


def _course(row: dict[str, Any]) -> MaterialCourse | None:
    if row["course_id"] is None:
        return None
    return MaterialCourse(
        lms_course_id=row["course_id"], name=course_name(row["course_name"]).short_name
    )


def _status(row: dict[str, Any]) -> str:
    if not row["has_material"]:
        return "pending"
    if row["status"] == "running" and not row["run_alive"]:
        return "failed"  # 실행이 멈췄다(서버 재시작 등). 다시 요약할 수 있다
    return row["status"]


def _detail(row: dict[str, Any]) -> MaterialDetail:
    start, end = row["page_start"], row["page_end"]
    return MaterialDetail(
        file_id=row["file_id"],
        file_name=row["original_name"],
        course=_course(row),
        source_language=row["source_language"],
        total_pages=row["total_pages"] if row["has_material"] else row["page_count"],
        processed_range=ProcessedRange(start=start, end=end)
        if start is not None and end is not None
        else None,
        status=_status(row),  # type: ignore[arg-type]
        overall_summary=row["overall_summary"] if row["status"] == "succeeded" else None,
        over_limit=row["over_limit"],
        run_id=row["run_id"],
    )


class MaterialRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def material(self, user_id: str, file_id: str) -> MaterialFile | None:
        """내 강의자료와 요약 상태. 내 강의자료가 아니면 None이다."""
        row = await (
            await self.conn.execute(_FILE + " and f.id = %(fid)s", {"uid": user_id, "fid": file_id})
        ).fetchone()
        if row is None:
            return None
        return MaterialFile(
            file_id=row["file_id"],
            storage_path=row["storage_path"],
            page_count=row["page_count"],
            mime_type=row["mime_type"],
            detail=_detail(row),
            run_status=row["run_status"],
            run_alive=row["run_alive"],
        )

    async def start(self, file_id: str, *, run_id: str, pages: int, text_tokens: int) -> str:
        """요약을 시작한다. 지난 요약(실패·상한 초과·멈춘 실행)은 지운다. 처음 요청한 시각(created_at)은 둔다.

        다른 요청이 이미 요약하고 있으면(그 실행이 아직 돈다) 바꾸지 않는다. 지금 요약하는 실행 id를 준다 —
        run_id가 아니면 다른 요청이 먼저 시작한 것이다(두 탭에서 동시에 누름).
        """
        row = await (
            await self.conn.execute(
                "insert into materials as m (file_id, status, agent_run_id, total_pages,"
                " page_start, page_end, text_tokens, over_limit, overall_summary)"
                " values (%(fid)s, 'running', %(run)s, %(pages)s, 1, %(pages)s, %(tokens)s,"
                " false, null)"
                " on conflict (file_id) do update set status = 'running', agent_run_id = %(run)s,"
                " total_pages = %(pages)s, page_start = 1, page_end = %(pages)s,"
                " text_tokens = %(tokens)s, over_limit = false, overall_summary = null"
                " where not (m.status = 'running' and exists(select 1 from agent_runs r"
                " where r.id = m.agent_run_id and " + RUN_ALIVE + "))"
                " returning agent_run_id::text as run_id",
                {"fid": file_id, "run": run_id, "pages": max(pages, 1), "tokens": text_tokens},
            )
        ).fetchone()
        if row is not None:
            return row["run_id"]
        current = await (
            await self.conn.execute(
                "select agent_run_id::text as run_id from materials where file_id = %s", (file_id,)
            )
        ).fetchone()
        assert current is not None and current["run_id"] is not None
        return current["run_id"]

    async def too_long(self, file_id: str, *, pages: int, text_tokens: int) -> None:
        """글자가 상한을 넘어 요약하지 않았다고 남긴다(유료화 수요 근거, 명세 8장)."""
        await self.conn.execute(
            "insert into materials (file_id, status, total_pages, text_tokens, over_limit)"
            " values (%(fid)s, 'failed', %(pages)s, %(tokens)s, true)"
            " on conflict (file_id) do update set status = 'failed', agent_run_id = null,"
            " total_pages = %(pages)s, page_start = null, page_end = null,"
            " text_tokens = %(tokens)s, over_limit = true, overall_summary = null",
            {"fid": file_id, "pages": pages, "tokens": text_tokens},
        )

    async def save_summary(self, file_id: str, *, run_id: str, summary: str) -> bool:
        """요약을 저장한다. 그새 다른 요약이 시작됐으면(이 실행이 아니면) 덮어쓰지 않고 False다."""
        row = await (
            await self.conn.execute(
                "update materials set status = 'succeeded', overall_summary = %s"
                " where file_id = %s and agent_run_id = %s returning file_id",
                (summary, file_id, run_id),
            )
        ).fetchone()
        return row is not None

    async def fail(self, file_id: str, *, run_id: str) -> None:
        """이 실행의 요약이 실패했다. 다른 실행이 이어받았으면 그대로 둔다."""
        await self.conn.execute(
            "update materials set status = 'failed'"
            " where file_id = %s and agent_run_id = %s and status = 'running'",
            (file_id, run_id),
        )

    async def list(
        self, user_id: str, *, course_id: str | None, limit: int, after: Cursor | None
    ) -> tuple[list[MaterialItem], str | None]:
        """요약을 요청한 내 강의자료(최신순). 과목을 주면 그 과목만."""
        sql = _FILE + " and m.file_id is not null"
        params: dict[str, Any] = {"uid": user_id, "limit": limit + 1}
        if course_id is not None:
            sql += " and f.lms_course_id = %(course)s"
            params["course"] = course_id
        if after is not None:
            sql += " and (m.created_at, f.id::text) < (%(at)s, %(id)s)"
            params["at"], params["id"] = after.value, after.id
        sql += " order by m.created_at desc, f.id::text desc limit %(limit)s"
        rows = await (await self.conn.execute(sql, params)).fetchall()
        page = rows[:limit]
        items = [
            MaterialItem(
                file_id=row["file_id"],
                file_name=row["original_name"],
                course=_course(row),
                created_at=row["created_at"].astimezone(KST),
                status=_status(row),  # type: ignore[arg-type]
            )
            for row in page
        ]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = encode_cursor(
                Cursor(scope=MATERIALS_SCOPE, value=last["created_at"], id=last["file_id"])
            )
        return items, next_cursor


Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
MaterialRepos = Callable[[], AbstractAsyncContextManager[MaterialRepository]]


def material_repos(connect: Connect) -> MaterialRepos:
    """연결을 빌렸다 돌려주는 저장소 공급자(블록이 끝나면 커밋). 저장소를 기다리는 동안 연결을 쥐지 않는다."""

    @asynccontextmanager
    async def repos() -> AsyncIterator[MaterialRepository]:
        async with connect() as conn:
            yield MaterialRepository(conn)

    return repos


def get_material_repos(request: Request) -> MaterialRepos:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return material_repos(pool.connection)


MaterialReposDep = Annotated[MaterialRepos, Depends(get_material_repos)]
