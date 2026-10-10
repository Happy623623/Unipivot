"""공고 상세 통합 테스트(S1-6). DATABASE_URL이 있을 때만 돈다. 테스트마다 트랜잭션을 되돌린다.

실제 추출 실행 로그를 쓰는 테스트는 실행 로그(agent_runs)를 autocommit 연결로 남기고 끝에 지운다.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.agent_log import agent_run
from app.config import Settings, get_settings
from app.db import get_conn
from app.eligibility import KST
from app.extraction import (
    AttachmentInput,
    ExtractionAgent,
    ExtractionResult,
    Limits,
    NoticeInput,
    RequirementDraft,
)
from app.extraction.prompt import FETCH_ORIGINAL, READ_IMAGE, READ_TEXT, SUBMIT
from app.extraction.store import content_hash, save_extraction
from app.llm import ModelTurn, ToolResultTurn
from app.main import create_app
from app.repositories import opportunities as feed_module
from app.repositories.opportunities import (
    ENGINE_ERROR_SUMMARY,
    UNJUDGED_SUMMARY,
    FeedQuery,
    OpportunityRepository,
)
from app.repositories.profiles import ProfileRepository
from tests import samples
from tests.conftest import make_token
from tests.db_world import DATABASE_URL, build, connect, make_user
from tests.llm_fakes import Request, ScriptedLlm, call
from tests.samples import hp

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


async def one(conn: psycopg.AsyncConnection, query: str, *params: Any) -> dict[str, Any] | None:
    return await (await conn.execute(query, params)).fetchone()


async def test_detail_shows_judgment_documents_and_process() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        a = world.ids["장학 A"]
        documents = await (
            await conn.execute(
                "insert into opportunity_documents (opportunity_id, name, is_required, form_url)"
                " values (%s, '장학금 신청서', true, 'https://example.com/form.hwp'),"
                " (%s, '가족관계증명서', false, null) returning id",
                (a, a),
            )
        ).fetchall()
        plan = await one(
            conn, "select id from prep_plans where user_id = %s and opportunity_id = %s", me, a
        )
        assert plan is not None
        await conn.execute(
            "insert into planner_tasks (user_id, source, prep_plan_id, document_id, title,"
            " due_date, is_done) values (%s, 'prep_plan', %s, %s, '신청서 작성', %s, true),"
            " (%s, 'prep_plan', %s, null, '서류 제출', %s, false)",
            (me, plan["id"], documents[0]["id"], now.date(), me, plan["id"], now.date()),
        )
        await conn.execute(
            "insert into calendar_events (user_id, provider, opportunity_id, title, starts_at)"
            " values (%s, 'google', %s, '장학 A 마감', %s)",
            (me, a, now),
        )
        await conn.execute(
            "insert into opportunity_attachments (opportunity_id, seq, file_name, source_url,"
            " extract_method, extract_error) values"
            " (%s, 1, '2026-2 장학 안내.hwp', 'https://example.com/1', 'hwp_text', null),"
            " (%s, 2, '신청서.pdf', 'https://example.com/2', null, 'PDF를 열 수 없음'),"
            " (%s, 3, '추천서 양식.hwpx', 'https://example.com/3', null, null),"
            " (%s, 4, '본문 이미지 1.png', null, 'vision', null),"
            " (%s, 5, '스캔 공고문.pdf', 'https://example.com/5', 'vision', null)",
            (a, a, a, a, a),
        )
        steps = [  # (도구, 입력, 출력). 에이전트가 남기는 모양이고, 실행 로그 status는 모두 succeeded다
            (
                READ_TEXT,
                {"attachment_no": 1, "reason": "본문에 첨부 참조만 있음"},
                {"chars": 15000, "offset": 0, "next_offset": 12000, "sent_chars": 12000},
            ),
            (
                READ_TEXT,
                {"attachment_no": 1, "offset": 12000, "reason": "뒤에 요건이 더 있음"},
                {"chars": 15000, "offset": 12000, "sent_chars": 3000},
            ),
            (
                READ_IMAGE,
                {"attachment_no": 4, "reason": "포스터에 기간이 있음"},
                {"file_name": "본문 이미지 1.png", "sent_chars": 300},
            ),
            (  # 쪽 번호를 문자로 보내 에이전트가 1쪽부터 읽었다
                READ_IMAGE,
                {"attachment_no": 5, "start_page": "2", "reason": "스캔본이라 이미지로 읽음"},
                {"file_name": "스캔 공고문.pdf", "pages": "1–4/6", "next_start_page": 5},
            ),
            (
                READ_IMAGE,
                {"attachment_no": 5, "start_page": 5, "reason": "남은 쪽도 읽음"},
                {"file_name": "스캔 공고문.pdf", "pages": "5–6/6"},
            ),
            (
                READ_IMAGE,
                {"attachment_no": 2, "start_page": 5, "reason": "5쪽부터 이어서"},
                {"error": "PDF를 열 수 없음"},
            ),
            (
                READ_TEXT,
                {"attachment_no": 9, "reason": "없는 번호"},
                {"error": "첨부 번호가 없어요"},
            ),
            (
                FETCH_ORIGINAL,
                {"offset": 0, "reason": "본문이 잘림"},
                {"chars": 900, "offset": 0, "sent_chars": 900},
            ),
            (SUBMIT, {"requirements": [], "easy_summary": "요약"}, {"accepted": True}),
            ("extract_from_image", {}, None),
        ]
        for seq, (tool, args, output) in enumerate(steps, start=1):
            await conn.execute(
                "insert into tool_calls (run_id, seq, tool_name, input, output, status, latency_ms)"
                " values (%s, %s, %s, %s, %s, 'succeeded', %s)",
                (world.run_id, seq, tool, Jsonb(args), output and Jsonb(output), 100 * seq),
            )

        detail = await repo.detail(me, a, now=now, display_name="진서")
        assert detail is not None
        eligibility = detail.eligibility
        assert (eligibility.status, eligibility.display_status, eligibility.reason_text) == (
            "eligible",
            "eligible",
            "모든 조건 충족",
        )
        deadline = now + timedelta(days=2)
        assert eligibility.basis_date == deadline.astimezone(KST).date()  # 마감일(KST)이 기준일
        assert eligibility.evaluated_at == now and eligibility.requirements_version == 1
        assert [c.model_dump() for c in eligibility.clauses] == [
            {"clause_no": 1, "outcome": "pass", "condition_count": 1}
        ]
        condition = eligibility.conditions[0].model_dump()
        del condition["requirement_id"]
        assert condition == {
            "clause_no": 1,
            "field": "gpa_last_semester",
            "label": "직전학기 평점",
            "operator": "gte",
            "value": 3.0,
            "user_value": 3.5,
            "condition_text": "3.0 이상",
            "user_value_text": "3.50",
            "outcome": "pass",
            "unknown_reason": None,
            "evidence_text": "장학 A 근거",
            "is_ambiguous": False,
        }
        assert detail.deadline_at is not None and detail.deadline_at.utcoffset() == timedelta(
            hours=9
        )
        assert (detail.status, detail.uploaded_by_me, detail.reported_by_me) == (
            "active",
            False,
            False,
        )
        # 서류: 필수 먼저, 준비 할 일과 연결된 서류만 task_id·is_done이 있다
        assert [(d.name, d.is_required, d.is_done) for d in detail.documents] == [
            ("장학금 신청서", True, True),
            ("가족관계증명서", False, None),
        ]
        assert detail.documents[0].task_id is not None and detail.documents[1].task_id is None
        prep = detail.prep
        assert (prep.prepared, prep.prep_plan_id, prep.tasks_total, prep.tasks_done) == (
            True,
            str(plan["id"]),
            2,
            1,
        )
        assert [event.provider for event in prep.calendar_events] == ["google"]
        # 첨부: 학교 주소가 있는 행만, 읽음·실패·읽지 않음
        assert [(item.file_name, item.extract_status) for item in detail.attachments] == [
            ("2026-2 장학 안내.hwp", "succeeded"),
            ("신청서.pdf", "failed"),
            ("추천서 양식.hwpx", "skipped"),
            ("스캔 공고문.pdf", "succeeded"),
        ]
        # 처리 과정: 첨부 이름을 넣은 라벨, 이어 읽기(실제로 읽은 위치), 오류를 돌려준 호출은 실패,
        # 모델이 고른 이유
        assert [(s.label, s.status, s.chosen_by, s.note) for s in detail.process.extraction] == [
            ("첨부 '2026-2 장학 안내.hwp' 읽기", "succeeded", "agent", "본문에 첨부 참조만 있음"),
            ("첨부 '2026-2 장학 안내.hwp' 이어 읽기", "succeeded", "agent", "뒤에 요건이 더 있음"),
            (
                "첨부 '본문 이미지 1.png' 이미지로 읽기",
                "succeeded",
                "agent",
                "포스터에 기간이 있음",
            ),
            (
                "첨부 '스캔 공고문.pdf' 이미지로 읽기",
                "succeeded",
                "agent",
                "스캔본이라 이미지로 읽음",
            ),
            ("첨부 '스캔 공고문.pdf' 이미지로 이어 읽기", "succeeded", "agent", "남은 쪽도 읽음"),
            ("첨부 '신청서.pdf' 이미지로 이어 읽기", "failed", "agent", "5쪽부터 이어서"),
            ("첨부 9번 읽기", "failed", "agent", "없는 번호"),
            ("공고 원문 페이지 읽기", "succeeded", "agent", "본문이 잘림"),
            ("지원 자격 정리", "succeeded", "agent", None),
            ("extract_from_image", "succeeded", "pipeline", None),
        ]
        assert [s.latency_ms for s in detail.process.extraction][:2] == [100, 200]
        assert detail.process.evaluated_at == now and detail.process.prepare_run_id is None

        # 판정을 저장하고 조회 기록을 남긴다(다시 열면 처음 본 시각은 그대로)
        stored = await one(
            conn,
            "select status::text as status, evaluated_at from eligibility_results"
            " where user_id = %s and opportunity_id = %s",
            me,
            a,
        )
        assert stored == {"status": "eligible", "evaluated_at": now}
        later = now + timedelta(hours=1)
        await repo.detail(me, a, now=later)
        view = await one(
            conn,
            "select first_viewed_at, last_viewed_at from opportunity_views"
            " where user_id = %s and opportunity_id = %s",
            me,
            a,
        )
        assert view == {"first_viewed_at": now, "last_viewed_at": later}
        page = await repo.feed_page(me, FeedQuery(categories=("scholarship",)), now=later)
        assert not next(
            item for item in page.items if item.id == a
        ).is_new  # 연 공고는 새 공고가 아니다
    finally:
        await conn.rollback()
        await conn.close()


async def test_detail_visibility() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        ids = world.ids

        async def visible(title: str) -> bool:
            return await repo.detail(me, ids[title], now=now) is not None

        async def prepare(title: str) -> None:
            await conn.execute(
                "insert into prep_plans (user_id, opportunity_id) values (%s, %s)", (me, ids[title])
            )

        # 남의 포스터, 수강하지 않는 과목 공지, 숨김은 보이지 않는다. 마감 공고는 보인다
        assert [await visible(t) for t in ("남의 포스터 H", "다른 과목 K", "숨김 L")] == [
            False,
            False,
            False,
        ]
        expired = await repo.detail(me, ids["만료 M"], now=now)
        assert expired is not None and expired.status == "expired"
        assert await repo.detail(me, str(uuid.uuid4()), now=now) is None
        mine = await repo.detail(me, ids["내 포스터 I"], now=now)
        assert mine is not None and mine.uploaded_by_me
        course = await repo.detail(me, ids["과목 공지 J"], now=now)
        assert course is not None and course.course_name == "202620HY23525_선형대수"

        # 마감일이 지났는데 아직 마감 처리(expired)되지 않은 공고도 보인다(피드의 include_expired와 같다)
        late = await repo.detail(me, ids["지난 G"], now=now)
        assert late is not None and late.status == "active"

        # 병합된 공고는 보이지 않는다. 준비한 공고는 숨김·병합이 되어도 본인에게 보인다
        await conn.execute(
            "update opportunities set status = 'merged' where id = %s", (ids["장학 B"],)
        )
        assert not await visible("장학 B")
        await prepare("장학 B")
        merged = await repo.detail(me, ids["장학 B"], now=now)
        assert merged is not None and merged.status == "merged" and merged.prep.prepared
        await conn.execute(
            "update opportunities set status = 'hidden' where id = %s", (ids["장학 A"],)
        )
        prepared = await repo.detail(me, ids["장학 A"], now=now)
        assert prepared is not None and prepared.status == "hidden" and prepared.prep.prepared

        # 수강을 끝낸 과목의 공지는 보이지 않는다. 준비했으면 과목 이름과 함께 보인다
        await conn.execute("update lms_courses set is_active = false where user_id = %s", (me,))
        assert not await visible("과목 공지 J")
        await prepare("과목 공지 J")
        dropped = await repo.detail(me, ids["과목 공지 J"], now=now)
        assert dropped is not None and dropped.course_name == "202620HY23525_선형대수"

        # 첫 요청이 상세여도 프로필 행을 이름과 함께 만든다
        newbie = str(uuid.uuid4())
        await conn.execute("insert into auth.users (id) values (%s)", (newbie,))
        assert await repo.detail(newbie, ids["교내 C"], now=now, display_name="새 학생") is not None
        assert await one(conn, "select display_name from profiles where id = %s", newbie) == {
            "display_name": "새 학생"
        }
    finally:
        await conn.rollback()
        await conn.close()


async def test_detail_judges_with_the_current_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        profiles = ProfileRepository(conn)
        c = world.ids["교내 C"]

        # 소득 값을 넣으면 내 값이 보이고, 철회하면 판정표·저장 기록에서 바로 사라진다
        await profiles.set_income_consent(me, True)
        await profiles.update_profile(me, {"income_bracket": 6})
        detail = await repo.detail(me, c, now=now)
        assert detail is not None
        condition = detail.eligibility.conditions[0]
        assert (condition.user_value, condition.user_value_text, condition.outcome) == (
            6,
            "6구간",
            "pass",
        )
        await profiles.set_income_consent(me, False)
        await repo.refresh_judgments(me, now=now, force=True)
        detail = await repo.detail(me, c, now=now)
        assert detail is not None
        assert detail.eligibility.display_status == "missing_info"
        assert detail.eligibility.conditions[0].user_value is None
        stored = await one(
            conn,
            "select condition_results from eligibility_results"
            " where user_id = %s and opportunity_id = %s",
            me,
            c,
        )
        assert stored is not None and stored["condition_results"][0]["user_value"] is None

        # 마감 공고는 피드가 판정하지 않아도 상세가 그 자리에서 판정해 저장한다
        m = world.ids["만료 M"]
        assert (
            await one(
                conn,
                "select 1 from eligibility_results where user_id = %s and opportunity_id = %s",
                me,
                m,
            )
            is None
        )
        assert await repo.detail(me, m, now=now) is not None
        assert await one(
            conn,
            "select 1 from eligibility_results where user_id = %s and opportunity_id = %s",
            me,
            m,
        ) == {"?column?": 1}

        # 요건 추출에 실패한 공고는 판정하지 않는다
        failed = await repo.detail(me, world.ids["실패 E"], now=now)
        assert failed is not None
        assert (
            failed.eligibility.display_status,
            failed.eligibility.reason_text,
            failed.eligibility.basis_date,
            failed.eligibility.evaluated_at,
            failed.eligibility.conditions,
            failed.process.evaluated_at,
        ) == ("needs_review", UNJUDGED_SUMMARY, None, None, [], None)

        # 엔진이 오류를 내면 그 공고만 판정표 없이 원문 확인 필요로 보이고, 같은 모양으로 저장한다
        def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("엔진 오류 흉내")

        monkeypatch.setattr(feed_module, "check_eligibility", broken)
        a = world.ids["장학 A"]
        errored = await repo.detail(me, a, now=now)
        assert errored is not None
        assert (
            errored.eligibility.display_status,
            errored.eligibility.reason_text,
            errored.eligibility.conditions,
        ) == ("needs_review", ENGINE_ERROR_SUMMARY, [])
        assert errored.eligibility.basis_date == (now + timedelta(days=2)).astimezone(KST).date()
        assert await one(
            conn,
            "select reason_text from eligibility_results where user_id = %s and opportunity_id = %s",
            me,
            a,
        ) == {"reason_text": ENGINE_ERROR_SUMMARY}
    finally:
        await conn.rollback()
        await conn.close()


async def test_detail_view_record_and_feed_agree() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        a = world.ids["장학 A"]

        async def view() -> dict[str, Any] | None:
            return await one(
                conn,
                "select first_viewed_at, last_viewed_at from opportunity_views"
                " where user_id = %s and opportunity_id = %s",
                me,
                a,
            )

        # 조회 기록은 거꾸로 가지 않는다: 처음 연 시각은 그대로, 마지막 시각은 늦은 쪽이다.
        # 시각을 고정한 실행이 지난 시각으로 열어도 바뀌지 않는다
        later, earlier = now + timedelta(hours=1), now - timedelta(days=1)
        await repo.detail(me, a, now=now)
        await repo.detail(me, a, now=later)
        assert await view() == {"first_viewed_at": now, "last_viewed_at": later}
        await repo.detail(me, a, now=now)
        await repo.detail(me, a, now=earlier)
        assert await view() == {"first_viewed_at": now, "last_viewed_at": later}

        # 피드 카드와 상세는 같은 판정을 보인다(사유 한 줄, 라벨, 입력할 항목)
        await repo.refresh_judgments(me, now=now)
        page = await repo.feed_page(me, FeedQuery(limit=50), now=now)
        items = [item for item in page.items if item.id in world.ids.values()]
        assert len(items) == 8
        for item in items:
            detail = await repo.detail(me, item.id, now=now)
            assert detail is not None
            card, table = item.eligibility, detail.eligibility
            assert (table.reason_text, table.display_status, table.missing_fields) == (
                card.summary,
                card.display_status,
                card.missing_fields,
            )
    finally:
        await conn.rollback()
        await conn.close()


async def test_detail_keeps_the_extraction_order() -> None:
    """판정표는 묶음 순서, 묶음 안에서는 추출이 낸 순서(원문 순서)다. 다시 추출해도 같다."""
    conn = await connect()
    try:
        me = await make_user(conn, credits_last_semester=10)
        opportunity = await one(
            conn,
            "insert into opportunities (source_type, title) values ('school_notice', '순서 장학')"
            " returning id, now() as now",
        )
        run = await one(
            conn,
            "insert into agent_runs (trigger_type, status) values ('batch_crawl', 'succeeded')"
            " returning id",
        )
        assert opportunity is not None and run is not None
        opportunity_id, now = str(opportunity["id"]), opportunity["now"]
        order = [  # 묶음 1은 "다음 중 하나" 5개, 묶음 2는 2개
            (1, "grade", "eq", 4),
            (1, "credits_last_semester", "gte", 12),
            (1, "gpa_last_semester", "gte", 3.0),
            (1, "semesters_completed", "lte", 7),
            (1, "credits_total", "gte", 60),
            (2, "grade", "neq", 4),
            (2, "credits_last_semester", "gte", 9),
        ]
        drafts = tuple(
            RequirementDraft(no, field, op, value, None, f"근거 {no}-{field}", False)
            for no, field, op, value in reversed(order)  # 묶음 2를 먼저 내도 묶음 순서로 읽는다
        )
        result = ExtractionResult(succeeded=True, requirements=drafts, confidence=Decimal("0.9"))
        repo = OpportunityRepository(conn)
        expected = sorted(  # 묶음 번호 순, 묶음 안은 낸 순서
            [(no, field) for no, field, _, _ in reversed(order)], key=lambda item: item[0]
        )
        for attempt in range(2):  # 두 번째는 다시 추출(요건 버전 2)
            await save_extraction(
                conn, opportunity_id, result, run_id=str(run["id"]), content_hash=f"h{attempt}"
            )
            detail = await repo.detail(me, opportunity_id, now=now)
            assert detail is not None
            got = [(c.clause_no, c.field) for c in detail.eligibility.conditions]
            assert got == expected
            assert detail.eligibility.requirements_version == attempt + 1
        assert [c.condition_count for c in detail.eligibility.clauses] == [5, 2]
    finally:
        await conn.rollback()
        await conn.close()


async def test_detail_shows_review_reasons() -> None:
    """원문 확인 필요 이유(S1-6b): 추출할 때마다 새 값으로 바뀌고, 실패한 추출도 이유가 보인다.

    저장은 받은 그대로 하고, 상세는 모델이 쓴 글을 한 줄로 정리해 보인다.
    """
    conn = await connect()
    try:
        me = await make_user(conn)
        opportunity = await one(
            conn,
            "insert into opportunities (source_type, title) values ('school_notice', '이유 장학')"
            " returning id, now() as now",
        )
        run = await one(
            conn,
            "insert into agent_runs (trigger_type, status) values ('batch_crawl', 'succeeded')"
            " returning id",
        )
        assert opportunity is not None and run is not None
        opportunity_id, now, run_id = str(opportunity["id"]), opportunity["now"], str(run["id"])
        repo = OpportunityRepository(conn)

        async def save(result: ExtractionResult, digest: str) -> Any:
            await save_extraction(conn, opportunity_id, result, run_id=run_id, content_hash=digest)
            stored = await one(
                conn, "select review_reasons from opportunities where id = %s", opportunity_id
            )
            detail = await repo.detail(me, opportunity_id, now=now)
            assert stored is not None and detail is not None
            return stored["review_reasons"], detail

        # 새 공고는 이유가 없다(빈 배열)
        fresh = await repo.detail(me, opportunity_id, now=now)
        assert fresh is not None and (fresh.needs_review, fresh.review_reasons) == (False, [])

        raw = (
            "읽지 못한 첨부가 있음",
            "모델이 원문 확인 필요로 표시: 신청서는\nhttps://evil.example/form 에서 받기",
        )
        flagged = ExtractionResult(
            succeeded=True, confidence=Decimal("0.9"), needs_review=True, review_reasons=raw
        )
        stored, detail = await save(flagged, "h1")
        assert stored == list(raw)  # 저장은 그대로
        assert detail.needs_review and detail.review_reasons == [
            "읽지 못한 첨부가 있음",
            "모델이 원문 확인 필요로 표시: 신청서는 에서 받기",
        ]

        # 다시 추출해서 이유가 없어지면 비운다
        clean = ExtractionResult(succeeded=True, confidence=Decimal("0.9"))
        stored, detail = await save(clean, "h2")
        assert stored == [] and (detail.needs_review, detail.review_reasons) == (False, [])

        # 추출에 실패해도 이유는 남는다. 처리 과정은 비어 있다(실행이 공고에 이어지지 않음)
        failed = ExtractionResult(
            succeeded=False, needs_review=True, review_reasons=("제출을 받지 못함",)
        )
        stored, detail = await save(failed, "h3")
        assert stored == ["제출을 받지 못함"]
        assert (detail.needs_review, detail.review_reasons) == (True, ["제출을 받지 못함"])
        assert detail.eligibility.reason_text == UNJUDGED_SUMMARY
        assert detail.process.extraction == []
    finally:
        await conn.rollback()
        await conn.close()


async def test_detail_process_from_an_extraction_run() -> None:
    """요건 추출 에이전트가 실제로 남긴 실행 로그로 처리 과정을 만든다(LLM만 가짜).

    에이전트는 도구 오류와 제출 거절을 모델에 돌려주고 계속 가서 실행 로그에는 succeeded로 남는다.
    상세는 그 호출을 실패로 보인다.
    """
    conn, log_conn = await connect(), await connect(autocommit=True)
    run_ids: list[str] = []
    try:
        me = await make_user(conn)
        opportunity = await one(
            conn,
            "insert into opportunities (source_type, title) values ('school_notice', '○○장학')"
            " returning id, now() as now",
        )
        assert opportunity is not None
        opportunity_id, now = str(opportunity["id"]), opportunity["now"]
        attachment = await one(
            conn,
            "insert into opportunity_attachments (opportunity_id, seq, file_name, source_url)"
            " values (%s, 1, '선발요강.hwpx', 'https://example.ac.kr/f/1') returning id",
            opportunity_id,
        )
        assert attachment is not None
        guide = samples.hwpx(hp("가. 직전 학기 평점평균 3.0 이상"), hp("나. 경기도 거주자"))
        notice = NoticeInput(
            title="○○장학",
            body="자세한 내용은 첨부를 참조하세요.",
            attachments=(
                AttachmentInput(
                    1, "선발요강.hwpx", guide, "https://example.ac.kr/f/1", str(attachment["id"])
                ),
            ),
        )

        def read_on(request: Request) -> ModelTurn:  # 앞 결과의 next_offset부터 이어 읽는다
            last = request.turns[-1]
            assert isinstance(last, ToolResultTurn)
            offset = last.results[0].content["output"]["next_offset"]
            return call(READ_TEXT, attachment_no=1, offset=offset, reason="뒷부분도 읽음")

        requirement = {
            "clause_no": 1,
            "field": "gpa_last_semester",
            "operator": "gte",
            "value_json": "3.0",
            "evidence_text": "직전 학기 평점평균 3.0 이상",
            "is_ambiguous": False,
        }
        llm = ScriptedLlm(
            call(READ_TEXT, attachment_no=7, reason="7번 첨부에 요건이 있을 것 같음"),
            call(READ_TEXT, attachment_no=1, reason="요건이 선발요강에 있어서 읽음"),
            read_on,
            call(SUBMIT, requirements="없음", confidence=0.9),  # 목록이 아니라 거절된다
            call(SUBMIT, requirements=[requirement], confidence=0.9, needs_review=False),
        )
        agent = ExtractionAgent(llm, model="gemini-3.8-flash", limits=Limits(max_read_chars=20))
        async with agent_run(log_conn, trigger="batch_crawl") as run:
            run_ids.append(run.id)
            result = await agent.run(notice, run)
        assert result.succeeded
        digest = content_hash(notice.body, notice.attachments)
        await save_extraction(conn, opportunity_id, result, run_id=run.id, content_hash=digest)

        detail = await OpportunityRepository(conn).detail(me, opportunity_id, now=now)
        assert detail is not None
        assert [(s.tool, s.label, s.status, s.note) for s in detail.process.extraction] == [
            (READ_TEXT, "첨부 7번 읽기", "failed", "7번 첨부에 요건이 있을 것 같음"),
            (READ_TEXT, "첨부 '선발요강.hwpx' 읽기", "succeeded", "요건이 선발요강에 있어서 읽음"),
            (READ_TEXT, "첨부 '선발요강.hwpx' 이어 읽기", "succeeded", "뒷부분도 읽음"),
            (SUBMIT, "지원 자격 정리", "failed", None),
            (SUBMIT, "지원 자격 정리", "succeeded", None),
        ]
        logged = await (
            await log_conn.execute(
                "select status::text as status from tool_calls where run_id = %s order by seq",
                (run.id,),
            )
        ).fetchall()
        assert [row["status"] for row in logged] == ["succeeded"] * 5
        assert all(step.latency_ms is not None for step in detail.process.extraction)
        assert [(a.file_name, a.extract_status) for a in detail.attachments] == [
            ("선발요강.hwpx", "succeeded")
        ]
        assert [c.field for c in detail.eligibility.conditions] == ["gpa_last_semester"]
        # 다 읽었고 고친 제출도 아니라 원문 확인 필요 이유가 없다
        assert (detail.needs_review, detail.review_reasons) == (False, [])
    finally:
        await conn.rollback()
        await conn.close()
        await log_conn.execute("delete from agent_runs where id = any(%s::uuid[])", (run_ids,))
        await log_conn.close()


async def test_detail_endpoint_over_http(settings: Settings) -> None:
    """라우터부터 DB까지 실제 코드로 돈다. 요청마다 이 테스트의 연결(되돌릴 트랜잭션)을 쓴다."""
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        async def same_conn() -> AsyncIterator[psycopg.AsyncConnection]:
            yield conn

        app.dependency_overrides[get_conn] = same_conn
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {make_token(sub=me)}"}
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as http:
            res = await http.get(f"/api/v1/opportunities/{world.ids['교내 C']}")
            assert res.status_code == 200
            body = res.json()
            assert body["deadline_at"].endswith("+09:00")
            assert body["eligibility"]["evaluated_at"].endswith("+09:00")
            assert body["eligibility"]["missing_fields"] == ["income_bracket"]
            assert body["eligibility"]["conditions"][0]["label"] == "학자금 지원구간"
            res = await http.get(f"/api/v1/opportunities/{world.ids['남의 포스터 H']}")
            assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"
            # 상세를 연 공고는 피드에서 새 공고가 아니다
            res = await http.get(
                "/api/v1/opportunities", params={"category": "school_program", "limit": 50}
            )
            flags = {
                item["title"]: item["is_new"]
                for item in res.json()["items"]
                if item["id"] in world.ids.values()
            }
            assert flags == {"교내 C": False, "과목 공지 J": True}
    finally:
        await conn.rollback()
        await conn.close()
