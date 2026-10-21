"""추천 사유(F-24)와 대체 공고(F-23)의 SQL. DATABASE_URL이 있을 때만 돈다. 테스트마다 트랜잭션을 되돌린다."""

import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.repositories.opportunities import FeedQuery, OpportunityRepository
from tests.db_world import DATABASE_URL, World, build, connect, titles

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


async def documents(conn: psycopg.AsyncConnection, opportunity_id: str, count: int) -> None:
    for number in range(count):
        await conn.execute(
            "insert into opportunity_documents (opportunity_id, name) values (%s, %s)",
            (opportunity_id, f"서류 {number + 1}"),
        )


async def optional_documents(
    conn: psycopg.AsyncConnection, opportunity_id: str, count: int
) -> None:
    for number in range(count):
        await conn.execute(
            "insert into opportunity_documents (opportunity_id, name, is_required)"
            " values (%s, %s, false)",
            (opportunity_id, f"선택 서류 {number + 1}"),
        )


async def requirement(
    conn: psycopg.AsyncConnection,
    opportunity_id: str,
    clause_no: int,
    field: str,
    operator: str,
    value: object,
    basis: str | None = None,
) -> None:
    await conn.execute(
        "insert into requirements (opportunity_id, clause_no, field, operator, value, basis,"
        " evidence_text, created_at)"
        " values (%s, %s, %s, %s, %s, %s, '근거', now() + %s * interval '1 microsecond')",
        (opportunity_id, clause_no, field, operator, Jsonb(value), basis, clause_no),
    )


async def scholarships(conn: psycopg.AsyncConnection, world: World, me: str) -> None:
    """장학 B(지원 어려움, 서류 2개)의 대체 후보. 내 프로필: 인공지능학과 3학년, 직전학기 10학점·3.5."""
    await documents(conn, world.ids["장학 B"], 2)
    grade = ((1, "grade", "eq", 3),)
    eligible_n = await world.add("장학 N", days=30, requirements=grade, needs_review=True)
    await documents(conn, eligible_n, 2)
    await optional_documents(conn, eligible_n, 1)  # 선택 서류는 세지 않는다(세면 S가 앞선다)
    await documents(conn, await world.add("장학 O", days=15), 1)  # 조건 없음 → 지원 가능
    await documents(conn, await world.add("장학 S", days=5, requirements=grade), 3)
    dismissed = await world.add("장학 P", days=3, requirements=grade)
    await documents(conn, dismissed, 2)
    await conn.execute(
        "insert into opportunity_marks (user_id, opportunity_id, mark) values (%s, %s, 'not_interested')",
        (me, dismissed),
    )
    await world.add("장학 Q", days=6, requirements=((1, "income_bracket", "lte", 8),))  # 정보 필요
    await world.add(
        "교내 R", days=8, category="school_program", requirements=grade
    )  # 다른 카테고리
    await world.add(
        "만료 T", days=-2, status="expired", requirements=((1, "credits_last_semester", "gte", 12),)
    )
    await world.add("지난 V", days=-1, requirements=grade)  # 마감이 지남


async def test_feed_items_say_which_conditions_matched() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        mixed = await world.add("추천 U", days=9, category="etc")
        await requirement(
            conn, mixed, 1, "department", "in", ["소프트웨어융합대학"], basis="college"
        )
        await requirement(conn, mixed, 2, "grade", "eq", 3)
        await requirement(conn, mixed, 3, "gpa_last_semester", "gte", 3.0)
        await requirement(conn, mixed, 4, "credits_last_semester", "gte", 5)
        await requirement(conn, mixed, 5, "other", "eq", {"text": "면접 통과자"})
        either = await world.add("하나만 W", days=11, category="etc")
        await requirement(conn, either, 1, "grade", "eq", 1)  # 같은 조항 중 하나만 맞아도 된다
        await requirement(conn, either, 1, "department", "in", ["인공지능학과"], basis="department")
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now)
        page = await repo.feed_page(me, FeedQuery(), now=now)
        reasons = dict(
            zip(titles(page.items, world), (i.recommend_reason for i in page.items), strict=True)
        )
        assert reasons["장학 A"] == "직전학기 평점 조건이 맞아요"
        assert reasons["장학 B"] is None  # 지원 어려움
        assert reasons["교내 C"] is None  # 맞는 조건이 아직 없다(정보 필요)
        assert reasons["기타 D"] is None  # 기타 조건은 이름이 없다
        assert reasons["실패 E"] is None and reasons["상시 F"] is None  # 추출 실패·조건 없음
        # 원문 순서, 학과 조건은 비교 단위, 기타 조건은 빼고 셋까지
        assert reasons["추천 U"] == "단과대학·학년·직전학기 평점 외 1개 조건은 맞아요"
        assert reasons["하나만 W"] == "학과 조건이 맞아요"  # 맞지 않은 학년은 쓰지 않는다
    finally:
        await conn.rollback()
        await conn.close()


async def test_alternatives_pick_eligible_same_category_by_document_count() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        await scholarships(conn, world, me)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now, include_expired=True)
        found = await repo.alternatives(me, world.ids["장학 B"], now=now)
        assert found is not None
        # 서류 수가 2개에 가까운 순(N 2개 → S 3개·O 1개는 마감이 이른 S 먼저), 셋까지라 A(0개)는 빠진다.
        # 관심 없음 P·정보 필요 Q·다른 카테고리 R·마감 지난 V·기준 공고 B는 후보가 아니다
        assert titles(found, world) == ["장학 N", "장학 S", "장학 O"]
        assert found[0].recommend_reason == "학년 조건이 맞아요"  # 피드 아이템과 같은 모양
        assert found[
            0
        ].needs_review  # 원문 확인 필요인 지원 가능 공고도 후보다(화면이 배지를 붙인다)
        assert all(item.eligibility.display_status == "eligible" for item in found)
    finally:
        await conn.rollback()
        await conn.close()


async def test_alternatives_only_for_an_ineligible_opportunity_i_can_open() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        await scholarships(conn, world, me)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now, include_expired=True)
        assert await repo.alternatives(me, world.ids["장학 A"], now=now) == []  # 지원 가능
        assert await repo.alternatives(me, world.ids["교내 C"], now=now) == []  # 정보 필요
        assert await repo.alternatives(me, world.ids["실패 E"], now=now) == []  # 추출 실패
        # 마감 공고도 상세가 열리니 고른다(후보는 마감 전 공고만). T는 서류가 없어 A(0개)가 먼저
        expired = await repo.alternatives(me, world.ids["만료 T"], now=now)
        assert expired is not None and titles(expired, world) == ["장학 A", "장학 O", "장학 N"]
        assert await repo.alternatives(me, world.ids["남의 포스터 H"], now=now) is None
        assert await repo.alternatives(me, world.ids["숨김 L"], now=now) is None
        assert await repo.alternatives(me, world.ids["다른 과목 K"], now=now) is None
        assert await repo.alternatives(me, str(uuid.uuid4()), now=now) is None
    finally:
        await conn.rollback()
        await conn.close()


async def test_alternatives_include_a_hidden_opportunity_i_prepared() -> None:
    """준비한 공고는 숨김이 되어도 본인에게 열린다. 그 공고가 지원 어려움이면 대체 공고를 준다."""
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        await scholarships(conn, world, me)
        hidden = await world.add(
            "숨긴 장학 X", days=12, status="hidden", requirements=((1, "grade", "eq", 4),)
        )
        await conn.execute(
            "insert into prep_plans (user_id, opportunity_id) values (%s, %s)", (me, hidden)
        )
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now)  # 숨김 공고는 피드의 다시 판정에 안 들어간다
        found = await repo.alternatives(me, hidden, now=now)  # 그 자리에서 판정한다
        assert found is not None and titles(found, world) == ["장학 A", "장학 O", "장학 N"]
    finally:
        await conn.rollback()
        await conn.close()


async def test_alternatives_judge_the_target_even_when_its_judgment_was_cleared() -> None:
    """프로필을 저장하면(force) 마감 공고의 판정이 지워진다. 상세를 거치지 않고 불러도 그 자리에서 판정한다."""
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        await scholarships(conn, world, me)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now, force=True)
        found = await repo.alternatives(me, world.ids["만료 T"], now=now)
        assert found is not None and titles(found, world) == ["장학 A", "장학 O", "장학 N"]
        stored = await (
            await conn.execute(
                "select status::text as status from eligibility_results"
                " where user_id = %s and opportunity_id = %s",
                (me, world.ids["만료 T"]),
            )
        ).fetchone()
        assert stored == {"status": "ineligible"}  # 상세처럼 판정을 저장한다
    finally:
        await conn.rollback()
        await conn.close()


async def test_alternatives_break_ties_by_id() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        await documents(conn, world.ids["장학 B"], 1)
        same = [await world.add(f"같은 {n}", days=20, category="scholarship") for n in "YZW"]
        for opportunity_id in same:
            await documents(conn, opportunity_id, 1)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now)
        found = await repo.alternatives(me, world.ids["장학 B"], now=now)
        assert found is not None and [item.id for item in found] == sorted(same)
    finally:
        await conn.rollback()
        await conn.close()
