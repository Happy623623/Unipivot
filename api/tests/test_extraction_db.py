"""요건 추출 + 실행 로그 + 저장을 실제 스키마(마이그레이션)에 대고 확인한다. DATABASE_URL이 있을 때만 돈다."""

import json
import os
import uuid
import zipfile
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import psycopg
import pytest
from psycopg.rows import dict_row

from app.agent_log import agent_run
from app.eligibility import KST, Department
from app.extraction import (
    AttachmentInput,
    ExtractionAgent,
    ExtractionResult,
    NoticeInput,
    RequirementDraft,
)
from app.extraction.prompt import READ_TEXT, SUBMIT
from app.extraction.store import content_hash, load_departments, save_extraction
from app.pricing import cost_usd
from tests import samples
from tests.llm_fakes import ScriptedLlm, call
from tests.samples import hp

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


async def connect(autocommit: bool = False) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row, autocommit=autocommit, prepare_threshold=None
    )


def _docx() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


async def _rows(conn: psycopg.AsyncConnection, sql: str, *params: object) -> list[dict]:
    return await (await conn.execute(sql, params)).fetchall()


async def _counts(conn: psycopg.AsyncConnection, opportunity_id: str) -> dict:
    (row,) = await _rows(
        conn,
        "select (select count(*) from requirements where opportunity_id = %s) as reqs,"
        " (select count(*) from opportunity_documents where opportunity_id = %s) as docs",
        opportunity_id,
        opportunity_id,
    )
    return row


async def test_extract_log_and_store_round_trip() -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    run_ids: list[str] = []
    try:
        (opportunity,) = await _rows(
            conn,
            "insert into opportunities (source_type, title) values ('school_notice', '○○장학')"
            " returning id",
        )
        opportunity_id = str(opportunity["id"])
        guide_row, form_row = await _rows(
            conn,
            "insert into opportunity_attachments (opportunity_id, seq, file_name, source_url)"
            " values (%s, 1, '선발요강.hwpx', 'https://example.ac.kr/f/1'),"
            " (%s, 2, '신청서.docx', 'https://example.ac.kr/f/2') returning id",
            opportunity_id,
            opportunity_id,
        )
        guide = samples.hwpx(hp("가. 직전 학기 평점평균 3.0 이상"), hp("나. 경기도 거주자"))
        notice = NoticeInput(
            title="○○장학",
            body="자세한 내용은 첨부를 참조하세요.",
            attachments=(
                AttachmentInput(
                    1, "선발요강.hwpx", guide, "https://example.ac.kr/f/1", str(guide_row["id"])
                ),
                AttachmentInput(
                    2, "신청서.docx", _docx(), "https://example.ac.kr/f/2", str(form_row["id"])
                ),
            ),
        )
        llm = ScriptedLlm(
            call(READ_TEXT, attachment_no=1, reason="요건이 선발요강에 있어서 읽음"),
            call(
                SUBMIT,
                requirements=[
                    {
                        "clause_no": 1,
                        "field": "gpa_last_semester",
                        "operator": "gte",
                        "value_json": "3.0",
                        "evidence_text": "직전 학기 평점평균 3.0 이상",
                        "is_ambiguous": False,
                    },
                    {
                        "clause_no": 2,
                        "field": "region",
                        "operator": "in",
                        "value_json": json.dumps(["경기도"], ensure_ascii=False),
                        "basis": "unspecified",
                        "evidence_text": "경기도 거주자",
                        "is_ambiguous": False,
                    },
                ],
                documents=[{"name": "장학금 신청서", "is_required": True, "form_attachment_no": 2}],
                deadline="2026-10-24T18:00",
                confidence=0.9,
                needs_review=False,
            ),
        )
        async with agent_run(log_conn, trigger="batch_crawl") as run:
            run_ids.append(run.id)
            result = await ExtractionAgent(llm, model="gemini-3.8-flash").run(notice, run)
        digest = content_hash(notice.body, notice.attachments)
        assert (
            await save_extraction(conn, opportunity_id, result, run_id=run.id, content_hash=digest)
            == 1
        )

        requirements = await _rows(
            conn,
            "select clause_no, field, operator::text as operator, value, basis, is_ambiguous"
            " from requirements where opportunity_id = %s order by clause_no",
            opportunity_id,
        )
        assert requirements == [
            {
                "clause_no": 1,
                "field": "gpa_last_semester",
                "operator": "gte",
                "value": 3.0,
                "basis": None,
                "is_ambiguous": False,
            },
            {
                "clause_no": 2,
                "field": "region",
                "operator": "in",
                "value": ["경기도"],
                "basis": "unspecified",
                "is_ambiguous": False,
            },
        ]
        documents = await _rows(
            conn,
            "select name, form_url from opportunity_documents where opportunity_id = %s",
            opportunity_id,
        )
        assert documents == [{"name": "장학금 신청서", "form_url": "https://example.ac.kr/f/2"}]
        (saved,) = await _rows(conn, "select * from opportunities where id = %s", opportunity_id)
        assert saved["deadline_at"] == datetime(2026, 10, 24, 18, 0, tzinfo=KST)
        assert (str(saved["extraction_run_id"]), saved["content_hash"]) == (run.id, digest)
        assert saved["needs_review"] is True  # 신청서.docx를 못 읽었다
        assert saved["review_reasons"] == ["읽지 못한 첨부가 있음"]  # 이유도 함께 남는다(S1-6b)
        assert saved["extraction_confidence"] == Decimal("0.90")
        attachments = await _rows(
            conn,
            "select seq, extract_method, extract_error, mime_type, sha256, extracted_at is not null as done"
            " from opportunity_attachments where opportunity_id = %s order by seq",
            opportunity_id,
        )
        assert [
            (a["seq"], a["extract_method"], a["extract_error"], a["done"]) for a in attachments
        ] == [
            (1, "hwpx_text", None, True),
            (2, None, "DOCX는 아직 못 읽어요", True),
        ]
        assert (
            attachments[0]["mime_type"] == "application/hwp+zip"
            and len(attachments[0]["sha256"]) == 64
        )

        # 실행 로그: 도구 호출과 이유, LLM 호출 비용(단가표)
        tools = await _rows(
            log_conn,
            "select tool_name, status, input from tool_calls where run_id = %s order by seq",
            run.id,
        )
        assert [(t["tool_name"], t["status"]) for t in tools] == [
            (READ_TEXT, "succeeded"),
            (SUBMIT, "succeeded"),
        ]
        assert tools[0]["input"]["reason"] == "요건이 선발요강에 있어서 읽음"
        (finished,) = await _rows(log_conn, "select * from agent_runs where id = %s", run.id)
        assert (finished["status"], finished["input_tokens"], finished["output_tokens"]) == (
            "succeeded",
            2000,
            400,
        )
        each = cost_usd("google", "gemini-3.8-flash", 1000, 200, datetime.now(KST).date())
        assert (
            finished["cost_usd"] == 2 * each
        )  # 단가표로 계산(2026년은 100만 토큰당 0.75/3.75 USD)

        # 다시 추출: 요건·서류·날짜를 새 값으로 바꾸고 버전을 올린다. 새 마감일이 없으면 비운다
        again = ExtractionResult(
            succeeded=True,
            requirements=(
                RequirementDraft(
                    1, "other", "eq", {"text": "봉사 20시간"}, None, "봉사 20시간", True
                ),
            ),
            confidence=Decimal("0.70"),
            needs_review=True,
            review_reasons=("모호한 요건이 있음",),
        )
        version = await save_extraction(
            conn, opportunity_id, again, run_id=run.id, content_hash="h2"
        )
        assert version == 2
        (saved,) = await _rows(conn, "select * from opportunities where id = %s", opportunity_id)
        assert (saved["requirements_version"], saved["deadline_at"]) == (2, None)
        assert saved["review_reasons"] == ["모호한 요건이 있음"]  # 이유도 새 값으로 바꾼다
        assert await _counts(conn, opportunity_id) == {"reqs": 1, "docs": 0}

        # 실패한 추출: 바뀐 공고를 옛 요건으로 판정하지 않게 요건을 비우고 판정 대상에서 뺀다
        failed = ExtractionResult(
            succeeded=False, needs_review=True, review_reasons=("제출을 받지 못함",)
        )
        version = await save_extraction(
            conn, opportunity_id, failed, run_id=None, content_hash="h3"
        )
        assert version == 3  # 전 판정 결과(버전 2)는 낡은 결과가 된다
        (saved,) = await _rows(conn, "select * from opportunities where id = %s", opportunity_id)
        assert (saved["content_hash"], saved["needs_review"], saved["extraction_run_id"]) == (
            "h3",
            True,
            None,
        )
        assert saved["review_reasons"] == ["제출을 받지 못함"]
        assert await _counts(conn, opportunity_id) == {"reqs": 0, "docs": 0}
    finally:
        await conn.rollback()
        await conn.close()
        await log_conn.execute("delete from agent_runs where id = any(%s::uuid[])", (run_ids,))
        await log_conn.close()


async def test_first_failure_leaves_the_notice_unjudged() -> None:
    conn = await connect()
    try:
        (row,) = await _rows(
            conn,
            "insert into opportunities (source_type, title) values ('school_notice', 'x') returning id",
        )
        failed = ExtractionResult(succeeded=False, needs_review=True)
        assert (
            await save_extraction(conn, str(row["id"]), failed, run_id=None, content_hash="h") == 1
        )
        (saved,) = await _rows(conn, "select * from opportunities where id = %s", row["id"])
        assert (saved["extraction_run_id"], saved["needs_review"]) == (
            None,
            True,
        )  # 판정하지 않는다
        assert saved["review_reasons"] == []  # 이유 없이 만든 결과는 빈 배열로 남는다
        with pytest.raises(LookupError):
            await save_extraction(conn, str(uuid.uuid4()), failed, run_id=None, content_hash="h")
    finally:
        await conn.rollback()
        await conn.close()


async def test_load_departments_for_the_prompt() -> None:
    conn = await connect()
    try:
        await conn.execute(
            "insert into departments (name, college, field_group, sort_order, is_active) values"
            " ('나중학과', '테스트대학', '공학계열', 2, true), ('먼저학과', '테스트대학', '인문계열', 1, true),"
            " ('폐지학과', '테스트대학', '공학계열', 0, false)"
        )
        departments = await load_departments(conn)
        names = [department.name for department in departments]
        assert names.index("먼저학과") < names.index("나중학과") and "폐지학과" not in names
        assert Department("먼저학과", "테스트대학", "인문계열") in departments
    finally:
        await conn.rollback()
        await conn.close()
