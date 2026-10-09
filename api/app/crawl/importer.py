"""저장한 한양대 공지를 DB에 넣고, 새 글·수정된 글만 요건 추출을 돌린다(S1-4 2부, A안).

공지마다 이 순서다.
1. 캠퍼스: 서울만이면 건너뛴다(이미 가져온 공지가 서울로 바뀌었으면 숨긴다). 표시가 없으면(캠퍼스 게시
   "안함") 처음 가져올 때 include_unmarked가 있어야 한다. 한 번 가져온 공지는 그 뒤로 묻지 않는다
2. 변경 확인: content_hash(본문 + 첨부 파일 sha256)가 DB 값과 같으면 제목·부서·분류·주소와 첨부 이름·주소만
   맞추고 끝낸다. 지난 추출이 실패해 판정에서 빠진 공고면 알려 준다(force로 다시 추출)
3. 파일: 가져오지 못한 첨부·본문 이미지가 있으면 allow_missing일 때만 가져오고, 그 첨부는 extract_error를
   남겨 원문 확인 필요로 둔다
4. 요건 추출: 에이전트를 돌린다(agent_runs.trigger_type = batch_crawl)
5. 저장: 한 트랜잭션으로 공고 행을 넣거나 고치고, 첨부 행을 다시 만들고, 추출 결과를 저장한다
LLM 호출 오류로 실행이 실패하면 공고에는 아무것도 쓰지 않는다. 다음에 가져올 때 다시 돈다.
요건 버전이 바뀐 공고를 모든 사용자로 다시 판정하는 일은 피드 판정(S1-5)이 한다.

상태: 학교 공지의 숨김(hidden)은 가져오기만 쓴다(신고 숨김은 공유 포스터에만 있다, PRD F-17).
서울로 바뀌어 숨긴 공지가 ERICA·공통으로 돌아오면 다시 보이게 하고, 만료(expired)된 공지는 내용이 바뀌었고
마감이 지나지 않았을 때만(마감 없음 포함) 다시 활성으로 돌린다(S10 마감 연장). 병합(merged)은 건드리지 않는다.
"""

import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Literal

from psycopg import AsyncConnection

from app.agent_log import agent_run
from app.crawl.hanyang import BOARD_URL, SOURCE_NAME
from app.crawl.saved import SavedNotice
from app.extraction.agent import ExtractionAgent
from app.extraction.models import ExtractionResult
from app.extraction.store import content_hash, save_extraction

SOURCE_TYPE = "school_notice"
RETRY_HINT = "지난 추출이 실패해 판정에서 빠져 있어요. --force로 다시 추출하세요"
RESTORED = "숨김·만료였던 공고를 다시 보이게 함(status = active)"

Status = Literal["new", "updated", "unchanged", "skipped", "error"]


@dataclass(frozen=True)
class ImportOptions:
    include_unmarked: bool = False  # 캠퍼스 게시가 "안함"인 공지도 가져온다(처음 가져올 때)
    allow_missing: bool = False  # 가져오지 못한 첨부·본문 이미지가 있어도 가져온다
    force: bool = False  # 내용이 같아도 다시 추출한다
    scenario: str | None = None  # agent_runs.scenario_code. 시나리오 실행(S10 등)을 구분한다


@dataclass(frozen=True)
class ImportResult:
    status: Status
    message: str = ""
    opportunity_id: str | None = None
    run_id: str | None = None
    version: int | None = None  # 저장한 뒤의 requirements_version
    extraction: ExtractionResult | None = None
    cost_usd: Decimal = Decimal(0)
    unjudged: bool = False  # 추출에 실패해 판정에서 빠진 공고(extraction_run_id가 null)


async def ensure_source(conn: AsyncConnection) -> str:
    """sources의 한양대 공지사항 행. 없으면 만든다."""
    row = await (
        await conn.execute(
            "select id from sources where type = %s and base_url = %s order by id limit 1",
            (SOURCE_TYPE, BOARD_URL),
        )
    ).fetchone()
    if row is None:
        row = await (
            await conn.execute(
                "insert into sources (type, name, base_url) values (%s, %s, %s) returning id",
                (SOURCE_TYPE, SOURCE_NAME, BOARD_URL),
            )
        ).fetchone()
    return str(row["id"])


async def mark_collected(conn: AsyncConnection, source_id: str) -> None:
    await conn.execute("update sources set last_collected_at = now() where id = %s", (source_id,))


async def import_notice(
    conn: AsyncConnection,
    log_conn: AsyncConnection,
    source_id: str,
    saved: SavedNotice,
    agent: ExtractionAgent,
    options: ImportOptions | None = None,
) -> ImportResult:
    """conn은 데이터, log_conn은 실행 로그(autocommit)용이다. LLM 호출 오류는 그대로 올라간다."""
    options = options or ImportOptions()
    page = saved.page
    existing = await _existing(conn, source_id, page.entry_id)
    if page.scope == "seoul":
        if existing and await _hide(conn, str(existing["id"])):
            return ImportResult(
                "skipped",
                "서울캠퍼스 공지로 바뀌어 피드에서 숨김(status = hidden)",
                opportunity_id=str(existing["id"]),
            )
        return ImportResult("skipped", "서울캠퍼스 공지라 건너뜀")
    if page.scope == "unmarked" and existing is None and not options.include_unmarked:
        return ImportResult(
            "skipped",
            f"캠퍼스 표시가 없어 건너뜀(캠퍼스 게시: {page.campus or '없음'})."
            " ERICA 학생 공지가 맞으면 --include-unmarked로 가져온다",
        )

    notice = saved.notice_input()
    digest = content_hash(notice.body, notice.attachments)
    if existing and existing["content_hash"] == digest and not options.force:
        opportunity_id = str(existing["id"])
        async with conn.transaction():
            await _refresh_listing(conn, opportunity_id, saved)
            await _refresh_attachments(conn, opportunity_id, saved)
            restored = await _restore_status(conn, opportunity_id, changed=False)
        unjudged = existing["extraction_run_id"] is None
        message = "내용이 같아 다시 추출하지 않음"
        message += f". {RESTORED}" if restored else ""
        message += f". {RETRY_HINT}" if unjudged else ""
        return ImportResult("unchanged", message, opportunity_id=opportunity_id, unjudged=unjudged)
    if saved.missing and not options.allow_missing:
        names = ", ".join(f"{file.seq}. {file.name}({file.problem})" for file in saved.missing)
        return ImportResult(
            "error",
            f"가져오지 못한 파일: {names}. 고치고 다시 실행하거나, 없이 가져오려면 --allow-missing",
        )

    async with agent_run(log_conn, trigger="batch_crawl", scenario_code=options.scenario) as run:
        extraction = await agent.run(notice, run)
    if saved.missing:
        extraction = _note_missing(extraction, saved)
    async with conn.transaction():
        opportunity_id = await _upsert(conn, source_id, saved, notice.body)
        ids = await _replace_attachments(conn, opportunity_id, saved, extraction)
        extraction = replace(
            extraction,
            attachments=tuple(
                replace(outcome, id=ids[outcome.seq]) for outcome in extraction.attachments
            ),
        )
        version = await save_extraction(
            conn, opportunity_id, extraction, run_id=run.id, content_hash=digest
        )
        restored = await _restore_status(conn, opportunity_id, changed=True)
    notes = [RESTORED] if restored else []
    notes += [] if extraction.succeeded else [RETRY_HINT]
    return ImportResult(
        "new" if existing is None else "updated",
        ". ".join(notes),
        opportunity_id=opportunity_id,
        run_id=run.id,
        version=version,
        extraction=extraction,
        cost_usd=run.cost_usd,
        unjudged=not extraction.succeeded,
    )


async def _existing(conn: AsyncConnection, source_id: str, entry_id: str) -> dict[str, Any] | None:
    return await (
        await conn.execute(
            "select id, content_hash, extraction_run_id from opportunities"
            " where source_id = %s and external_id = %s",
            (source_id, entry_id),
        )
    ).fetchone()


async def _hide(conn: AsyncConnection, opportunity_id: str) -> bool:
    cursor = await conn.execute(
        "update opportunities set status = 'hidden' where id = %s and status = 'active'",
        (opportunity_id,),
    )
    return cursor.rowcount == 1


_RESTORE_HIDDEN = "update opportunities set status = 'active' where id = %s and status = 'hidden'"
_RESTORE_HIDDEN_OR_EXPIRED = (
    "update opportunities set status = 'active' where id = %s and (status = 'hidden'"
    " or (status = 'expired' and (deadline_at is null or deadline_at > now())))"
)


async def _restore_status(conn: AsyncConnection, opportunity_id: str, *, changed: bool) -> bool:
    """ERICA 학생에게 보일 공지가 숨김이면 다시 활성으로 돌린다. 만료는 내용이 바뀌었고(마감 연장 등)
    마감이 지나지 않았을 때만 돌린다. 내용이 같은데 돌리면 만료 작업과 번갈아 상태가 바뀐다."""
    sql = _RESTORE_HIDDEN_OR_EXPIRED if changed else _RESTORE_HIDDEN
    cursor = await conn.execute(sql, (opportunity_id,))
    return cursor.rowcount == 1


def _listing(saved: SavedNotice) -> dict[str, Any]:
    page = saved.page
    return {
        "category": page.opportunity_category,
        "title": page.title,
        "organizer": page.department,
        "url": page.permalink,
    }


async def _refresh_listing(conn: AsyncConnection, opportunity_id: str, saved: SavedNotice) -> None:
    """내용이 같아도 제목·부서·분류·주소는 게시판 값으로 맞춘다. 같으면 쓰지 않는다(updated_at 유지)."""
    await conn.execute(
        "update opportunities set category = %(category)s::opportunity_category,"
        " title = %(title)s, organizer = %(organizer)s, original_url = %(url)s"
        " where id = %(id)s and (category, title, organizer, original_url) is distinct from"
        " (%(category)s::opportunity_category, %(title)s, %(organizer)s, %(url)s)",
        {**_listing(saved), "id": opportunity_id},
    )


async def _refresh_attachments(
    conn: AsyncConnection, opportunity_id: str, saved: SavedNotice
) -> None:
    """내용(파일)이 같아도 학교가 같은 파일을 새 이름·주소로 다시 올렸을 수 있다. 이름·주소만 맞춘다.
    두 행이 주소를 맞바꾸면 (opportunity_id, source_url) 유일 제약에 걸리므로 바뀌는 행의 주소를 먼저 비운다."""
    rows = await (
        await conn.execute(
            "select seq, file_name, source_url from opportunity_attachments"
            " where opportunity_id = %s",
            (opportunity_id,),
        )
    ).fetchall()
    current = {row["seq"]: (row["file_name"], row["source_url"]) for row in rows}
    changed = [
        file
        for file in saved.files
        if file.seq in current and current[file.seq] != (file.name, file.source_url)
    ]
    if not changed:
        return
    await conn.execute(
        "update opportunity_attachments set source_url = null"
        " where opportunity_id = %s and seq = any(%s)",
        (opportunity_id, [file.seq for file in changed]),
    )
    for file in changed:
        await conn.execute(
            "update opportunity_attachments set file_name = %s, source_url = %s"
            " where opportunity_id = %s and seq = %s",
            (file.name, file.source_url, opportunity_id, file.seq),
        )


async def _upsert(conn: AsyncConnection, source_id: str, saved: SavedNotice, body: str) -> str:
    """공고 행. 상태는 여기서 바꾸지 않는다(_restore_status)."""
    row = await (
        await conn.execute(
            "insert into opportunities (source_id, source_type, external_id, category, title,"
            " organizer, original_url, raw_text) values (%(source_id)s, 'school_notice',"
            " %(entry_id)s, %(category)s::opportunity_category, %(title)s, %(organizer)s,"
            " %(url)s, %(raw_text)s)"
            " on conflict (source_id, external_id) do update set category = excluded.category,"
            " title = excluded.title, organizer = excluded.organizer,"
            " original_url = excluded.original_url, raw_text = excluded.raw_text"
            " returning id",
            {
                **_listing(saved),
                "source_id": source_id,
                "entry_id": saved.page.entry_id,
                "raw_text": body,
            },
        )
    ).fetchone()
    return str(row["id"])


async def _replace_attachments(
    conn: AsyncConnection, opportunity_id: str, saved: SavedNotice, extraction: ExtractionResult
) -> dict[int, str]:
    """첨부 행을 페이지 순서대로 다시 만든다. 첨부 번호 → 행 id."""
    await conn.execute(
        "delete from opportunity_attachments where opportunity_id = %s", (opportunity_id,)
    )
    outcomes = {outcome.seq: outcome for outcome in extraction.attachments}
    ids: dict[int, str] = {}
    for file in saved.files:
        if file.data is None:  # 가져오지 못한 파일: 실패 사유를 남겨 원문 확인 필요가 보이게 한다
            values = (
                opportunity_id, file.seq, file.name, None, file.source_url, None,
                f"파일을 가져오지 못해 읽지 않았어요({file.problem})", True,
            )  # fmt: skip
        else:
            outcome = outcomes.get(file.seq)
            values = (
                opportunity_id, file.seq, file.name, outcome.mime_type if outcome else None,
                file.source_url, hashlib.sha256(file.data).hexdigest(), None, False,
            )  # fmt: skip
        row = await (
            await conn.execute(
                "insert into opportunity_attachments (opportunity_id, seq, file_name, mime_type,"
                " source_url, sha256, extract_error, extracted_at) values"
                " (%s, %s, %s, %s, %s, %s, %s, case when %s then now() end) returning id",
                values,
            )
        ).fetchone()
        ids[file.seq] = str(row["id"])
    return ids


def _note_missing(extraction: ExtractionResult, saved: SavedNotice) -> ExtractionResult:
    numbers = ", ".join(str(file.seq) for file in saved.missing)
    return replace(
        extraction,
        needs_review=True,
        review_reasons=(*extraction.review_reasons, f"가져오지 못해 읽지 않은 첨부: {numbers}"),
    )
