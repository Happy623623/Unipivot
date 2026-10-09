"""저장한 공지 가져오기를 실제 스키마에 대고 확인한다: 새 글 → 그대로 → 수정된 글(S10), 캠퍼스·빠진 파일 규칙,
상태(숨김·만료), 추출 실패, LLM 오류. DATABASE_URL이 있을 때만 돈다.

공고·출처 행은 트랜잭션을 되돌려 지우고, 실행 로그는 이 파일만 쓰는 scenario_code로 골라 지운다."""

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from app.crawl.importer import RETRY_HINT, ImportOptions, ensure_source, import_notice
from app.crawl.saved import load_folder
from app.eligibility import KST
from app.extraction import ExtractionAgent
from app.extraction.prompt import READ_TEXT, SUBMIT
from app.extraction.store import content_hash
from tests import hanyang_pages, samples
from tests.hanyang_pages import POSTER, save_notice
from tests.llm_fakes import ScriptedLlm, call
from tests.samples import hp

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]
MODEL = "gemini-3.8-flash"
GUIDE = samples.hwpx(hp("가. 직전 학기 평점평균 3.0 이상인 재학생"))
SCENARIO = f"test-{uuid.uuid4().hex[:12]}"  # 이 파일이 남긴 실행 로그만 지우려고 붙인다


def options(**values: Any) -> ImportOptions:
    return ImportOptions(scenario=SCENARIO, **values)


async def cleanup(conn: psycopg.AsyncConnection, log_conn: psycopg.AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()
    await log_conn.execute("delete from agent_runs where scenario_code = %s", (SCENARIO,))
    await log_conn.close()


async def connect(autocommit: bool = False) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row, autocommit=autocommit, prepare_threshold=None
    )


async def _rows(conn: psycopg.AsyncConnection, sql: str, *params: object) -> list[dict]:
    return await (await conn.execute(sql, params)).fetchall()


def submit(deadline: str, **extra: Any) -> Any:
    return call(
        SUBMIT,
        requirements=[
            {
                "clause_no": 1,
                "field": "gpa_last_semester",
                "operator": "gte",
                "value_json": "3.0",
                "evidence_text": "직전 학기 평점평균 3.0 이상",
                "is_ambiguous": False,
            }
        ],
        documents=[],
        deadline=deadline,
        confidence=0.9,
        needs_review=False,
        **extra,
    )


def read_and_submit(deadline: str) -> tuple[Any, Any]:
    """첨부 1(선발요강)을 읽고 제출한다. 근거 문장이 읽은 원문에 있어야 제출이 통과한다."""
    return call(READ_TEXT, attachment_no=1, reason="자격이 선발요강에 있어서 읽음"), submit(
        deadline
    )


def page(body: str, **options: Any) -> str:
    options.setdefault("files", ("1. 선발요강.hwpx",))
    poster = f'<p><img alt="포스터" src="./{hanyang_pages.FILES}/poster.jpg"></p>'
    return hanyang_pages.detail(body=body + poster, **options)


def agent(*replies: Any) -> ExtractionAgent:
    return ExtractionAgent(ScriptedLlm(*replies), model=MODEL)


def no_requirements() -> Any:
    return call(SUBMIT, requirements=[], documents=[], confidence=0.8, needs_review=False)


async def test_new_unchanged_and_modified_notice(tmp_path: Path) -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        source_id = await ensure_source(conn)
        assert await ensure_source(conn) == source_id  # 출처 행은 하나
        folder = save_notice(
            tmp_path / "장학",
            page("<p>신청 기간: 10. 24.(금) 18:00까지</p>"),
            {"1. 선발요강.hwpx": GUIDE},
            {"poster.jpg": POSTER},
        )
        saved = load_folder(folder)
        first = await import_notice(
            conn,
            log_conn,
            source_id,
            saved,
            agent(
                call(READ_TEXT, attachment_no=1, reason="자격이 선발요강에 있어서 읽음"),
                submit("2026-10-24T18:00"),
            ),
            options(),
        )
        assert (first.status, first.version, first.unjudged) == ("new", 1, False)
        (row,) = await _rows(
            conn, "select * from opportunities where id = %s", first.opportunity_id
        )
        notice = saved.notice_input()
        assert {key: row[key] for key in ("source_type", "external_id", "category", "title")} == {
            "source_type": "school_notice",
            "external_id": "119702",
            "category": "scholarship",
            "title": "2026학년도 2학기 ○○장학생 선발 안내",
        }
        assert (row["organizer"], row["original_url"]) == (
            "학생지원팀",
            "https://www.hanyang.ac.kr/notice/url/4a4/1d396",
        )
        assert row["raw_text"] == saved.body() and row["raw_text"].startswith("[게시판 정보]")
        assert row["content_hash"] == content_hash(notice.body, notice.attachments)
        assert str(row["extraction_run_id"]) == first.run_id
        assert row["deadline_at"] == datetime(2026, 10, 24, 18, 0, tzinfo=KST)
        attachments = await _rows(
            conn,
            "select seq, file_name, mime_type, extract_method, extract_error,"
            " source_url is not null as has_url, length(sha256) as hash_len"
            " from opportunity_attachments where opportunity_id = %s order by seq",
            first.opportunity_id,
        )
        assert attachments == [
            {
                "seq": 1,
                "file_name": "1. 선발요강.hwpx",
                "mime_type": "application/hwp+zip",
                "extract_method": "hwpx_text",
                "extract_error": None,
                "has_url": True,
                "hash_len": 64,
            },
            {
                "seq": 2,
                "file_name": "poster.jpg",  # 본문 이미지: 학교 주소는 모르고, 읽지 않았다
                "mime_type": "image/jpeg",
                "extract_method": None,
                "extract_error": None,
                "has_url": False,
                "hash_len": 64,
            },
        ]
        (run,) = await _rows(log_conn, "select * from agent_runs where id = %s", first.run_id)
        assert (run["trigger_type"], run["status"], run["scenario_code"]) == (
            "batch_crawl",
            "succeeded",
            SCENARIO,
        )
        assert first.cost_usd == run["cost_usd"] > 0

        # 같은 폴더를 다시 가져오면 모델을 부르지 않는다(답을 준비하지 않은 가짜 모델)
        again = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert (again.status, again.opportunity_id, again.unjudged) == (
            "unchanged",
            first.opportunity_id,
            False,
        )

        # 제목만 바뀐 글: 다시 추출하지 않고 제목만 맞춘다
        save_notice(
            folder,
            page("<p>신청 기간: 10. 24.(금) 18:00까지</p>", title="[ERICA] ○○장학생 선발 안내"),
            {},
        )
        renamed = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert renamed.status == "unchanged"
        (row,) = await _rows(
            conn, "select title from opportunities where id = %s", first.opportunity_id
        )
        assert row["title"] == "[ERICA] ○○장학생 선발 안내"

        # 공지 수정(마감 연장, S10): 다시 추출하고 요건 버전을 올린다
        save_notice(folder, page("<p>신청 기간: 10. 31.(금) 18:00까지(연장)</p>"), {})
        changed = await import_notice(
            conn,
            log_conn,
            source_id,
            load_folder(folder),
            agent(
                call(READ_TEXT, attachment_no=1, reason="연장 공지라 자격을 다시 확인"),
                submit("2026-10-31T18:00"),
            ),
            options(),
        )
        assert (changed.status, changed.version, changed.opportunity_id) == (
            "updated",
            2,
            first.opportunity_id,
        )
        (row,) = await _rows(
            conn, "select * from opportunities where id = %s", first.opportunity_id
        )
        assert row["deadline_at"] == datetime(2026, 10, 31, 18, 0, tzinfo=KST)
        assert (row["requirements_version"], str(row["extraction_run_id"])) == (2, changed.run_id)
        assert "(연장)" in row["raw_text"]
        (count,) = await _rows(
            conn,
            "select count(*) as attachments,"
            " (select count(*) from requirements where opportunity_id = %s) as requirements"
            " from opportunity_attachments where opportunity_id = %s",
            first.opportunity_id,
            first.opportunity_id,
        )
        assert count == {"attachments": 2, "requirements": 1}  # 다시 만들었고 늘지 않았다

        # --force: 내용이 같아도 다시 추출한다
        forced = await import_notice(
            conn,
            log_conn,
            source_id,
            load_folder(folder),
            agent(*read_and_submit("2026-10-31T18:00")),
            options(force=True),
        )
        assert (forced.status, forced.version) == ("updated", 3)
    finally:
        await cleanup(conn, log_conn)


async def test_campus_and_missing_file_rules(tmp_path: Path) -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        source_id = await ensure_source(conn)
        seoul = save_notice(
            tmp_path / "서울", page("<p>서울캠퍼스 학생</p>", entry_id=1, campus="서울"), {}
        )
        result = await import_notice(conn, log_conn, source_id, load_folder(seoul), agent())
        assert (result.status, result.message) == ("skipped", "서울캠퍼스 공지라 건너뜀")

        unmarked = save_notice(
            tmp_path / "표시 없음",
            page("<p>본문</p>", entry_id=2, campus="안함", files=()),
            {},
            {"poster.jpg": POSTER},
        )
        result = await import_notice(conn, log_conn, source_id, load_folder(unmarked), agent())
        assert result.status == "skipped" and "--include-unmarked" in result.message
        result = await import_notice(
            conn,
            log_conn,
            source_id,
            load_folder(unmarked),
            agent(no_requirements()),
            options(include_unmarked=True),
        )
        assert result.status == "new"
        # 한 번 가져온 공지는 그 뒤로 플래그 없이도 따라간다(수정된 글)
        save_notice(unmarked, page("<p>본문 수정</p>", entry_id=2, campus="안함", files=()), {})
        result = await import_notice(
            conn, log_conn, source_id, load_folder(unmarked), agent(no_requirements()), options()
        )
        assert result.status == "updated"

        partial = save_notice(
            tmp_path / "첨부 빠짐",
            page("<p>본문</p>", entry_id=3, files=("1. 선발요강.hwpx", "2. 신청서.hwp")),
            {"1. 선발요강.hwpx": GUIDE},
            {"poster.jpg": POSTER},
        )
        result = await import_notice(conn, log_conn, source_id, load_folder(partial), agent())
        assert result.status == "error" and "2. 신청서.hwp(폴더에 없어요)" in result.message
        result = await import_notice(
            conn,
            log_conn,
            source_id,
            load_folder(partial),
            agent(*read_and_submit("2026-10-24")),
            options(allow_missing=True),
        )
        assert result.status == "new"
        assert result.extraction.needs_review
        assert "가져오지 못해 읽지 않은 첨부: 2" in result.extraction.review_reasons
        rows = await _rows(
            conn,
            "select seq, file_name, extract_error, extracted_at is not null as done,"
            " sha256 is null as no_hash from opportunity_attachments"
            " where opportunity_id = %s order by seq",
            result.opportunity_id,
        )
        assert rows[1] == {
            "seq": 2,
            "file_name": "2. 신청서.hwp",
            "extract_error": "파일을 가져오지 못해 읽지 않았어요(폴더에 없어요)",
            "done": True,
            "no_hash": True,
        }
        (row,) = await _rows(
            conn, "select needs_review from opportunities where id = %s", result.opportunity_id
        )
        assert row["needs_review"] is True
        # 그 뒤 평소처럼(플래그 없이) 가져와도 내용이 같으면 오류가 아니다
        again = await import_notice(conn, log_conn, source_id, load_folder(partial), agent())
        assert again.status == "unchanged"
    finally:
        await cleanup(conn, log_conn)


async def test_status_follows_the_board(tmp_path: Path) -> None:
    """캠퍼스가 서울로 바뀌면 숨기고 돌아오면 다시 보인다. 만료된 공고는 마감이 미뤄졌을 때만 살린다.
    같은 파일을 새 이름·주소로 다시 올리면 첨부 이름·주소만 맞춘다."""
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        source_id = await ensure_source(conn)
        folder = save_notice(
            tmp_path / "공통",
            page("<p>본문</p>", entry_id=5, campus="한양"),
            {"1. 선발요강.hwpx": GUIDE},
            {"poster.jpg": POSTER},
        )
        first = await import_notice(
            conn, log_conn, source_id, load_folder(folder), agent(no_requirements()), options()
        )
        assert first.status == "new"

        # 같은 파일을 학교가 새 이름·주소로 다시 올렸다: 다시 추출하지 않고 첨부 행만 맞춘다
        reposted = page(
            "<p>본문</p>", entry_id=5, campus="한양", files=("1. 선발요강(재게시).hwpx",)
        )
        save_notice(folder, reposted, {"1. 선발요강(재게시).hwpx": GUIDE})
        (folder / "1. 선발요강.hwpx").unlink()
        result = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert result.status == "unchanged"
        (row,) = await _rows(
            conn,
            "select file_name, source_url from opportunity_attachments"
            " where opportunity_id = %s and seq = 1",
            first.opportunity_id,
        )
        assert row["file_name"] == "1. 선발요강(재게시).hwpx"
        assert row["source_url"] == hanyang_pages.file_url(
            "1. 선발요강(재게시).hwpx", "uuid-1"
        ).replace("&amp;", "&")

        # 만료된 공고가 수정됐지만 마감이 여전히 지났으면 그대로 만료(날짜는 오늘 기준)
        await conn.execute(
            "update opportunities set status = 'expired' where id = %s", (first.opportunity_id,)
        )
        today = datetime.now(KST).date()
        posted = today - timedelta(days=60)
        files = ("1. 선발요강(재게시).hwpx",)
        dated = {
            "campus": "한양",
            "files": files,
            "posted": f"{posted.year}. {posted.month}. {posted.day}",
        }
        save_notice(folder, page("<p>문의처 변경</p>", entry_id=5, **dated), {})
        past = (today - timedelta(days=30)).isoformat()
        result = await import_notice(
            conn, log_conn, source_id, load_folder(folder), agent(*read_and_submit(past)), options()
        )
        assert result.status == "updated" and "다시 보이게" not in result.message
        assert await _status(conn, first.opportunity_id) == "expired"
        # 마감 연장(S10): 다시 활성. 만료 판단은 만료 작업이 다시 한다
        save_notice(folder, page("<p>마감 연장</p>", entry_id=5, **dated), {})
        future = (today + timedelta(days=30)).isoformat()
        result = await import_notice(
            conn,
            log_conn,
            source_id,
            load_folder(folder),
            agent(*read_and_submit(future)),
            options(),
        )
        assert (result.status, await _status(conn, first.opportunity_id)) == ("updated", "active")
        assert "다시 보이게 함" in result.message

        # 캠퍼스가 서울로 바뀌면 숨긴다. 다음부터는 그냥 건너뛴다
        save_notice(folder, page("<p>마감 연장</p>", entry_id=5, **{**dated, "campus": "서울"}), {})
        result = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert (result.status, result.message) == (
            "skipped",
            "서울캠퍼스 공지로 바뀌어 피드에서 숨김(status = hidden)",
        )
        (row,) = await _rows(
            conn, "select status::text from opportunities where id = %s", first.opportunity_id
        )
        assert row["status"] == "hidden"
        result = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert result.message == "서울캠퍼스 공지라 건너뜀"
        # 다시 공통(한양)으로 돌아왔다. 내용이 숨기기 전과 같아도 다시 보이게 한다
        save_notice(folder, page("<p>마감 연장</p>", entry_id=5, **dated), {})
        result = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert result.status == "unchanged" and "다시 보이게 함" in result.message
        assert await _status(conn, first.opportunity_id) == "active"
    finally:
        await cleanup(conn, log_conn)


async def test_unchanged_import_leaves_expired_alone(tmp_path: Path) -> None:
    """내용이 같으면 만료를 되돌리지 않는다(만료 작업과 번갈아 바뀌지 않게). 숨김만 되돌린다."""
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        source_id = await ensure_source(conn)
        folder = save_notice(
            tmp_path / "상시",
            page("<p>상시 모집</p>", entry_id=8, files=()),
            {},
            {"poster.jpg": POSTER},
        )
        first = await import_notice(
            conn, log_conn, source_id, load_folder(folder), agent(no_requirements()), options()
        )
        await conn.execute(
            "update opportunities set status = 'expired' where id = %s", (first.opportunity_id,)
        )
        result = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert result.message == "내용이 같아 다시 추출하지 않음"
        assert await _status(conn, first.opportunity_id) == "expired"
    finally:
        await cleanup(conn, log_conn)


async def test_reordered_identical_attachments_keep_unique_urls(tmp_path: Path) -> None:
    """내용이 같은 첨부 둘의 순서만 바뀌면 내용 해시는 같다. 주소를 맞바꿔도 유일 제약에 걸리지 않는다."""
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        source_id = await ensure_source(conn)
        folder = save_notice(
            tmp_path / "양식",
            page("<p>양식</p>", entry_id=7, files=("학부 신청서.hwp", "대학원 신청서.hwp")),
            {"학부 신청서.hwp": b"same form", "대학원 신청서.hwp": b"same form"},
            {"poster.jpg": POSTER},
        )
        first = await import_notice(
            conn, log_conn, source_id, load_folder(folder), agent(no_requirements()), options()
        )
        html = page("<p>양식</p>", entry_id=7, files=("대학원 신청서.hwp", "학부 신청서.hwp"))
        save_notice(
            folder,
            html.replace("uuid-1", "uuid-x")
            .replace("uuid-2", "uuid-1")
            .replace("uuid-x", "uuid-2"),
            {},
        )
        result = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert result.status == "unchanged"
        rows = await _rows(
            conn,
            "select seq, file_name, source_url from opportunity_attachments"
            " where opportunity_id = %s and seq <= 2 order by seq",
            first.opportunity_id,
        )
        assert [row["file_name"] for row in rows] == ["대학원 신청서.hwp", "학부 신청서.hwp"]
        assert rows[0]["source_url"].endswith("uuid-2?status=0&download=true")
    finally:
        await cleanup(conn, log_conn)


async def _status(conn: psycopg.AsyncConnection, opportunity_id: str) -> str:
    (row,) = await _rows(
        conn, "select status::text from opportunities where id = %s", opportunity_id
    )
    return row["status"]


async def test_failed_extraction_is_reported_until_forced(tmp_path: Path) -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        source_id = await ensure_source(conn)
        folder = save_notice(
            tmp_path / "장학",
            page("<p>본문</p>", entry_id=6),
            {"1. 선발요강.hwpx": GUIDE},
            {"poster.jpg": POSTER},
        )
        # 모델이 끝까지 제출하지 않았다(글로만 두 번 답함)
        failed = await import_notice(
            conn, log_conn, source_id, load_folder(folder), agent("요건은…", "그러니까…"), options()
        )
        assert (failed.status, failed.unjudged, failed.message) == ("new", True, RETRY_HINT)
        assert not failed.extraction.succeeded
        again = await import_notice(conn, log_conn, source_id, load_folder(folder), agent())
        assert (again.status, again.unjudged) == ("unchanged", True)
        assert again.message == f"내용이 같아 다시 추출하지 않음. {RETRY_HINT}"
        forced = await import_notice(
            conn,
            log_conn,
            source_id,
            load_folder(folder),
            agent(*read_and_submit("2026-10-24")),
            options(force=True),
        )
        assert (forced.status, forced.unjudged) == ("updated", False)
    finally:
        await cleanup(conn, log_conn)


class FailingLlm:
    provider = "google"

    async def generate(self, **_: Any) -> Any:
        raise RuntimeError("429 RESOURCE_EXHAUSTED")


async def test_llm_error_writes_nothing(tmp_path: Path) -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    scenario = f"{SCENARIO}-llm"
    try:
        source_id = await ensure_source(conn)
        folder = save_notice(
            tmp_path / "장학",
            page("<p>본문</p>", entry_id=4),
            {"1. 선발요강.hwpx": GUIDE},
            {"poster.jpg": POSTER},
        )
        with pytest.raises(RuntimeError, match="RESOURCE_EXHAUSTED"):
            await import_notice(
                conn,
                log_conn,
                source_id,
                load_folder(folder),
                ExtractionAgent(FailingLlm(), model=MODEL),
                ImportOptions(scenario=scenario),
            )
        assert await _rows(conn, "select id from opportunities where external_id = '4'") == []
        (run,) = await _rows(
            log_conn,
            "select status, error_message from agent_runs where scenario_code = %s",
            scenario,
        )
        assert run["status"] == "failed" and "RESOURCE_EXHAUSTED" in run["error_message"]
    finally:
        await log_conn.execute("delete from agent_runs where scenario_code = %s", (scenario,))
        await cleanup(conn, log_conn)
