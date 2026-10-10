"""피드·판정 저장 통합 테스트(S1-5). DATABASE_URL이 있을 때만 돈다. 테스트마다 트랜잭션을 되돌린다."""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.db import get_conn
from app.eligibility import KST
from app.main import create_app
from app.repositories import opportunities as feed_module
from app.repositories.opportunities import (
    ENGINE_ERROR_SUMMARY,
    UNJUDGED_SUMMARY,
    FeedQuery,
    OpportunityRepository,
    decode_cursor,
)
from app.repositories.profiles import ProfileRepository
from app.schemas.opportunities import OpportunityItem
from tests.conftest import make_token

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]
COURSE = 777_001  # 수강 중인 과목
Requirement = tuple[int, str, str, Any]  # (clause_no, field, operator, value)


async def connect() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row, prepare_threshold=None
    )


async def make_user(conn: psycopg.AsyncConnection, **profile: Any) -> str:
    user_id = str(uuid.uuid4())
    await conn.execute("insert into auth.users (id) values (%s)", (user_id,))
    repo = ProfileRepository(conn)
    await repo.ensure(user_id, "테스트 학생")
    await repo.save_consent(user_id, "2026-10-07", agree_income_info=False)
    if profile:
        await repo.update_profile(user_id, profile)
    return user_id


async def judged_titles(conn: psycopg.AsyncConnection, user_id: str) -> set[str]:
    """이 사용자의 판정이 저장된 공고 제목."""
    rows = await (
        await conn.execute(
            "select o.title from eligibility_results e join opportunities o"
            " on o.id = e.opportunity_id where e.user_id = %s",
            (user_id,),
        )
    ).fetchall()
    return {row["title"] for row in rows}


class World:
    """한 트랜잭션 안의 공고 묶음. now는 트랜잭션 시작 시각(DB now())이다."""

    def __init__(self, conn: psycopg.AsyncConnection, now: datetime, run_id: str) -> None:
        self.conn, self.now, self.run_id = conn, now, run_id
        self.ids: dict[str, str] = {}

    @classmethod
    async def start(cls, conn: psycopg.AsyncConnection) -> "World":
        run = await (
            await conn.execute(
                "insert into agent_runs (trigger_type, status) values ('batch_crawl', 'succeeded')"
                " returning id, started_at as now"
            )
        ).fetchone()
        assert run is not None
        return cls(conn, run["now"], str(run["id"]))

    async def add(
        self,
        title: str,
        *,
        days: float | None,
        requirements: tuple[Requirement, ...] = (),
        extracted: bool = True,
        **columns: Any,
    ) -> str:
        values = {
            "source_type": "school_notice",
            "category": "scholarship",
            "title": title,
            "organizer": "학생지원팀",
            "easy_summary": f"{title} 쉬운 설명",
            "deadline_at": None if days is None else self.now + timedelta(days=days),
            "extraction_run_id": self.run_id if extracted else None,
            **columns,
        }
        names = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        row = await (
            await self.conn.execute(
                f"insert into opportunities ({names}) values ({marks}) returning id",
                tuple(values.values()),
            )
        ).fetchone()
        assert row is not None
        opportunity_id = str(row["id"])
        for clause_no, field, operator, value in requirements:
            await self.conn.execute(
                "insert into requirements (opportunity_id, clause_no, field, operator, value,"
                " evidence_text) values (%s, %s, %s, %s, %s, %s)",
                (opportunity_id, clause_no, field, operator, Jsonb(value), f"{title} 근거"),
            )
        self.ids[title] = opportunity_id
        return opportunity_id


async def build(conn: psycopg.AsyncConnection) -> tuple[World, str, str]:
    """사용자 둘과 공고 13개. 보이는 활성 공고는 8개다."""
    await conn.execute(
        "insert into departments (name, college, field_group) values"
        " ('인공지능학과', '소프트웨어융합대학', '공학계열') on conflict do nothing"
    )
    me = await make_user(
        conn,
        department="인공지능학과",
        grade=3,
        credits_last_semester=10,
        gpa_last_semester=3.5,
    )
    other = await make_user(conn)
    await conn.execute(
        "insert into lms_courses (user_id, canvas_course_id, name) values (%s, %s, %s)",
        (me, COURSE, "202620HY23525_선형대수"),
    )
    world = await World.start(conn)
    old = world.now - timedelta(days=40)
    await world.add("장학 A", days=2, requirements=((1, "gpa_last_semester", "gte", 3.0),))
    await world.add("장학 B", days=10, requirements=((1, "credits_last_semester", "gte", 12),))
    await world.add(
        "교내 C",
        days=5,
        category="school_program",
        requirements=((1, "income_bracket", "lte", 8),),
    )
    await world.add(
        "기타 D",
        days=1,
        category="etc",
        requirements=((1, "other", "eq", {"text": "면접 통과자"}),),
    )
    await world.add("실패 E", days=3, extracted=False, needs_review=True)
    await world.add("상시 F", days=None, category="activity", created_at=old)
    await world.add("지난 G", days=-1)
    await world.add("남의 포스터 H", days=20, source_type="poster", uploaded_by=other)
    await world.add(
        "내 포스터 I", days=20, category="contest", source_type="poster", uploaded_by=me
    )
    await world.add(
        "과목 공지 J",
        days=7,
        category="school_program",
        source_type="lms_announcement",
        visible_canvas_course_id=COURSE,
    )
    await world.add(
        "다른 과목 K", days=7, source_type="lms_announcement", visible_canvas_course_id=888
    )
    await world.add("숨김 L", days=4, status="hidden")
    await world.add("만료 M", days=-3, status="expired")
    await conn.execute(
        "insert into prep_plans (user_id, opportunity_id) values (%s, %s)",
        (me, world.ids["장학 A"]),
    )
    await conn.execute(
        "insert into opportunity_views (user_id, opportunity_id) values (%s, %s)",
        (me, world.ids["장학 B"]),
    )
    return world, me, other


def titles(items: list[OpportunityItem], world: World) -> list[str]:
    names = {opportunity_id: title for title, opportunity_id in world.ids.items()}
    return [names[item.id] for item in items]


async def test_feed_lists_judged_opportunities_with_counts() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        first = await repo.refresh_judgments(me, now=now)
        assert (first.judged, first.changed) == (7, 0)  # A·B·C·D·F·I·J (E는 추출 실패)
        assert (await repo.refresh_judgments(me, now=now)).judged == 0  # 낡은 판정이 없다
        # 프로필 행이 아직 없는 사용자(첫 요청이 피드)는 이름과 함께 행을 만들고 빈 프로필로 판정한다
        newbie = str(uuid.uuid4())
        await conn.execute("insert into auth.users (id) values (%s)", (newbie,))
        fresh = await repo.refresh_judgments(newbie, now=now, display_name="새 학생")
        assert fresh.judged == 5  # A·B·C·D·F
        name = await (
            await conn.execute("select display_name from profiles where id = %s", (newbie,))
        ).fetchone()
        assert name == {"display_name": "새 학생"}

        page = await repo.feed_page(me, FeedQuery(), now=now)
        assert titles(page.items, world) == [
            "기타 D",
            "장학 A",
            "실패 E",
            "교내 C",
            "과목 공지 J",
            "장학 B",
            "내 포스터 I",
            "상시 F",  # 마감일 없는 공고는 맨 뒤
        ]
        assert page.next_cursor is None
        by_title = dict(zip(titles(page.items, world), page.items, strict=True))
        a, b, c, d, e, f = (
            by_title[t] for t in ("장학 A", "장학 B", "교내 C", "기타 D", "실패 E", "상시 F")
        )
        assert (a.eligibility.display_status, a.eligibility.summary, a.d_day) == (
            "eligible",
            "모든 조건 충족",
            2,
        )
        assert (a.prepared, a.is_new, b.is_new, f.is_new) == (True, True, False, False)
        assert a.deadline_at is not None and a.deadline_at.utcoffset() == timedelta(hours=9)
        assert (b.eligibility.display_status, b.eligibility.summary) == (
            "ineligible",
            "직전학기 이수학점: 12학점 이상 (현재 10학점)",
        )
        assert (c.eligibility.display_status, c.eligibility.missing_fields) == (
            "missing_info",
            ["income_bracket"],
        )
        assert c.eligibility.summary == "학자금 지원구간 입력 필요"
        assert (d.eligibility.display_status, d.eligibility.summary) == (
            "needs_review",
            "원문 확인 필요: 면접 통과자",
        )
        assert (e.eligibility.status, e.eligibility.display_status, e.eligibility.summary) == (
            "undetermined",
            "needs_review",
            UNJUDGED_SUMMARY,
        )
        assert e.needs_review and (f.d_day, f.deadline_at) == (None, None)
        assert by_title["내 포스터 I"].uploaded_by_me
        assert by_title["과목 공지 J"].course_name == "202620HY23525_선형대수"

        counts = await repo.feed_counts(me, now=now)
        assert counts.model_dump() == {
            "eligible": 4,  # A·F·I·J
            "new_eligible": 3,  # A·I·J (F는 40일 전에 등록)
            "undetermined": 3,  # C·D·E
            "missing_info": 1,
            "needs_review": 2,
            "ineligible": 1,  # B
            "deadline_soon": 3,  # D-1·D-2·D-3 (지원 어려움 제외)
        }

        home = await repo.feed_page(
            me, FeedQuery(eligibility=frozenset({"eligible", "undetermined"})), now=now
        )
        assert "장학 B" not in titles(home.items, world) and len(home.items) == 7
        rest = await repo.feed_page(me, FeedQuery(eligibility=frozenset({"ineligible"})), now=now)
        assert titles(rest.items, world) == ["장학 B"]
        scholarships = await repo.feed_page(me, FeedQuery(categories=("scholarship",)), now=now)
        assert titles(scholarships.items, world) == ["장학 A", "실패 E", "장학 B"]
        posters = await repo.feed_page(me, FeedQuery(source_types=("poster",)), now=now)
        assert titles(posters.items, world) == ["내 포스터 I"]  # 남의 포스터는 안 보인다

        assert (await repo.refresh_judgments(me, now=now, include_expired=True)).judged == 2
        everything = await repo.feed_page(me, FeedQuery(include_expired=True), now=now)
        assert titles(everything.items, world)[:2] == ["만료 M", "지난 G"]
        assert len(everything.items) == 10 and everything.items[0].d_day == -3
        assert await repo.feed_counts(me, now=now) == counts  # 집계는 지난 공고를 세지 않는다
    finally:
        await conn.rollback()
        await conn.close()


async def test_cursor_pages_follow_the_sort_order() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now)
        # 정렬 값이 없는 행: 마감일 없는 공고 둘(F·B), 등록 시각 없는 공고 둘(B·C)
        b, c = world.ids["장학 B"], world.ids["교내 C"]
        await conn.execute("update opportunities set deadline_at = null where id = %s", (b,))
        await conn.execute(
            "update opportunities set created_at = null where id = any(%s::uuid[])", ([b, c],)
        )
        for sort in ("deadline", "recent"):
            full = await repo.feed_page(me, FeedQuery(sort=sort, limit=50), now=now)
            for limit in (1, 3):  # 1이면 값이 없는 행에서도 cursor가 생긴다
                seen: list[str] = []
                cursor = None
                while True:
                    query = FeedQuery(sort=sort, limit=limit, cursor=cursor)
                    page = await repo.feed_page(me, query, now=now)
                    seen += [item.id for item in page.items]
                    if page.next_cursor is None:
                        break
                    cursor = decode_cursor(page.next_cursor)
                    assert cursor.scope == query.scope()
                assert seen == [item.id for item in full.items] and len(seen) == 8
        deadline = await repo.feed_page(me, FeedQuery(limit=50), now=now)
        assert set(titles(deadline.items, world)[-2:]) == {"상시 F", "장학 B"}
        recent = await repo.feed_page(me, FeedQuery(sort="recent", limit=50), now=now)
        assert titles(recent.items, world)[-3] == "상시 F"  # 가장 먼저 등록, 그 뒤는 B·C
        assert {item.id: item.is_new for item in recent.items[-2:]} == {b: False, c: False}
    finally:
        await conn.rollback()
        await conn.close()


async def test_rejudges_only_stale_results(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        profiles = ProfileRepository(conn)
        await repo.refresh_judgments(me, now=now, include_expired=True)
        assert {"지난 G", "만료 M"} <= await judged_titles(conn, me)

        # 프로필 저장: 활성 공고를 모두 다시 판정해 라벨이 바뀐 공고를 세고, 지난 공고의 판정은 지운다
        await profiles.update_profile(me, {"credits_last_semester": 13})
        result = await repo.refresh_judgments(me, now=now, force=True)
        assert (result.judged, result.changed) == (7, 1)  # 장학 B: 지원 어려움 → 지원 가능
        assert await judged_titles(conn, me) == {
            "장학 A",
            "장학 B",
            "교내 C",
            "기타 D",
            "상시 F",
            "내 포스터 I",
            "과목 공지 J",
        }
        assert (await repo.refresh_judgments(me, now=now, include_expired=True)).judged == 2

        # 재추출(요건 버전 증가): 그 공고만 다시 판정한다
        c = world.ids["교내 C"]
        await conn.execute("delete from requirements where opportunity_id = %s", (c,))
        await conn.execute(
            "insert into requirements (opportunity_id, clause_no, field, operator, value)"
            " values (%s, 1, 'gpa_last_semester', 'gte', '3.0')",
            (c,),
        )
        await conn.execute(
            "update opportunities set requirements_version = requirements_version + 1"
            " where id = %s",
            (c,),
        )
        assert await repo.refresh_judgments(me, now=now) == feed_module.Refresh(judged=1, changed=1)

        # 판정 규칙·문구가 바뀌면(ENGINE_VERSION) 저장된 판정이 모두 낡은 결과다
        monkeypatch.setattr(feed_module, "ENGINE_VERSION", 2)
        assert (await repo.refresh_judgments(me, now=now)).judged == 7
        assert (await repo.refresh_judgments(me, now=now)).judged == 0

        # 기준일이 "오늘"인 공고(마감일·기준일 없음)는 날이 바뀌면 다시 판정한다
        await conn.execute(
            "update eligibility_results set evaluated_at = now() - interval '1 day'"
            " where user_id = %s and opportunity_id = %s",
            (me, world.ids["상시 F"]),
        )
        assert (await repo.refresh_judgments(me, now=now)).judged == 1

        # 재추출에 실패하면 옛 판정을 지우고 판정 불가로 보인다
        a = world.ids["장학 A"]
        await conn.execute("update opportunities set extraction_run_id = null where id = %s", (a,))
        await repo.refresh_judgments(me, now=now)
        assert "장학 A" not in await judged_titles(conn, me)
        page = await repo.feed_page(me, FeedQuery(categories=("scholarship",)), now=now)
        item = next(item for item in page.items if item.id == a)
        assert (item.eligibility.display_status, item.eligibility.summary) == (
            "needs_review",
            UNJUDGED_SUMMARY,
        )
    finally:
        await conn.rollback()
        await conn.close()


async def test_today_basis_follows_the_request_clock() -> None:
    """기준일이 "오늘"인 공고는 요청이 넘긴 시각의 날짜로 판정하고, 날이 바뀌면 다시 판정한다.

    시각을 고정한 실행(평가 러너)도 그 날짜로 판정한다. DB 시계(프로필 저장 시각)는 보지 않는다.
    """
    conn = await connect()
    try:
        world = await World.start(conn)
        today = world.now.astimezone(KST).date()
        try:
            birth = today.replace(year=today.year - 35)  # 오늘 만 35세가 된다
        except ValueError:
            pytest.skip("2월 29일에는 35년 전 같은 날짜가 없다")
        me = await make_user(conn, birth_date=birth)  # 프로필 저장 시각(DB 시계) = 오늘
        youth = await world.add("청년 N", days=None, requirements=((1, "age", "lte", 34),))
        repo = OpportunityRepository(conn)
        midnight = datetime.combine(today, time(0), KST)

        async def label(now: datetime) -> tuple[int, str]:
            refresh = await repo.refresh_judgments(me, now=now)
            page = await repo.feed_page(me, FeedQuery(), now=now)
            item = next(item for item in page.items if item.id == youth)
            return refresh.judged, item.eligibility.display_status

        assert await label(midnight - timedelta(days=30)) == (1, "eligible")  # 고정한 시각
        assert await label(midnight - timedelta(milliseconds=1)) == (1, "eligible")  # 어제
        assert await label(midnight + timedelta(hours=10)) == (1, "ineligible")  # 오늘 만 35세
        assert await label(midnight + timedelta(hours=11)) == (0, "ineligible")
    finally:
        await conn.rollback()
        await conn.close()


async def test_new_arrivals_wait_for_the_next_request() -> None:
    """판정한 뒤 같은 요청 안에서 들어온 공고는 판정 없이 보이지 않고 다음 요청에 보인다."""
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now)
        counts = await repo.feed_counts(me, now=now)
        late = await world.add("늦게 온 N", days=4, requirements=((1, "gpa_total", "gte", 3.0),))
        page = await repo.feed_page(me, FeedQuery(), now=now)
        assert late not in [item.id for item in page.items] and len(page.items) == 8
        assert await repo.feed_counts(me, now=now) == counts
        assert (await repo.refresh_judgments(me, now=now)).judged == 1
        page = await repo.feed_page(me, FeedQuery(), now=now)
        assert late in [item.id for item in page.items]
    finally:
        await conn.rollback()
        await conn.close()


async def test_income_withdrawal_and_engine_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        profiles = ProfileRepository(conn)
        await profiles.set_income_consent(me, True)
        await profiles.update_profile(me, {"income_bracket": 6})
        await repo.refresh_judgments(me, now=now, force=True)
        counts = await repo.feed_counts(me, now=now)
        assert (counts.eligible, counts.missing_info) == (5, 0)  # 교내 C가 지원 가능

        await profiles.set_income_consent(me, False)  # 철회하면 소득 값이 지워진다
        result = await repo.refresh_judgments(me, now=now, force=True)
        assert result.changed == 1
        assert (await repo.feed_counts(me, now=now)).missing_info == 1

        # 엔진이 한 공고에서 실패해도 피드는 뜨고, 그 공고만 "판정하지 못함"(원문 확인 필요)으로 남는다
        real = feed_module.check_eligibility
        calls: list[str] = []

        def broken(requirements: list[Any], *args: Any, **kwargs: Any) -> Any:
            if any(r.field == "gpa_last_semester" for r in requirements):
                calls.append("장학 A")
                raise RuntimeError("엔진 오류 흉내")
            return real(requirements, *args, **kwargs)

        monkeypatch.setattr(feed_module, "check_eligibility", broken)
        await conn.execute(
            "update opportunities set requirements_version = requirements_version + 1"
            " where id = %s",
            (world.ids["장학 A"],),
        )
        failed = await repo.refresh_judgments(me, now=now)
        assert (failed.judged, failed.changed) == (1, 1)  # 지원 가능 → 원문 확인 필요
        page = await repo.feed_page(me, FeedQuery(), now=now)
        item = next(item for item in page.items if item.id == world.ids["장학 A"])
        assert (item.eligibility.display_status, item.eligibility.summary) == (
            "needs_review",
            ENGINE_ERROR_SUMMARY,
        )
        assert len(page.items) == 8  # 나머지 공고는 그대로 보인다
        assert (await repo.refresh_judgments(me, now=now)).judged == 0
        assert calls == ["장학 A"]  # 같은 오류를 요청마다 되풀이하지 않는다
        tomorrow = now + timedelta(days=1)  # 하루에 한 번 다시 시도한다(오류를 고쳤을 수 있다)
        assert (await repo.refresh_judgments(me, now=tomorrow)).judged == 2  # 장학 A, 상시 F
        assert calls == ["장학 A"] * 2
        await repo.refresh_judgments(me, now=now, force=True)  # 프로필이 바뀌면 다시 시도한다
        assert calls == ["장학 A"] * 3
    finally:
        await conn.rollback()
        await conn.close()


async def test_withdrawn_income_leaves_no_trace_in_judgments(settings: Settings) -> None:
    """소득 동의를 빼면(설정 PATCH, 온보딩 동의 POST) 지난·숨김 공고의 판정에도 소득 값이 남지 않는다.

    라우터부터 DB까지 실제 코드로 돈다. 요청마다 이 테스트의 연결(되돌릴 트랜잭션)을 쓴다.
    """
    conn = await connect()
    try:
        me = await make_user(conn)
        world = await World.start(conn)
        income = ((1, "income_bracket", "lte", 8),)
        await world.add("소득 활성", days=5, requirements=income)
        await world.add("소득 만료", days=-3, status="expired", requirements=income)
        await world.add("소득 숨김", days=6, requirements=income)

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

            async def give_income() -> None:
                res = await http.patch("/api/v1/me/consents", json={"agree_income_info": True})
                assert res.status_code == 200
                res = await http.patch("/api/v1/me/profile", json={"income_bracket": 9})
                assert res.status_code == 200
                res = await http.get("/api/v1/opportunities", params={"include_expired": "true"})
                assert res.status_code == 200

            async def traces() -> set[str]:
                """소득 값 9가 내 값(condition_results)이나 사유에 남은 판정의 공고 제목."""
                rows = await (
                    await conn.execute(
                        "select o.title, e.reason_text, e.condition_results"
                        " from eligibility_results e join opportunities o"
                        " on o.id = e.opportunity_id where e.user_id = %s",
                        (me,),
                    )
                ).fetchall()
                return {
                    row["title"]
                    for row in rows
                    if "9구간" in (row["reason_text"] or "")
                    or any(c["user_value"] is not None for c in row["condition_results"])
                }

            await give_income()
            hidden = world.ids["소득 숨김"]
            await conn.execute(
                "update opportunities set status = 'hidden' where id = %s", (hidden,)
            )
            assert await traces() == {"소득 활성", "소득 만료", "소득 숨김"}
            res = await http.patch("/api/v1/me/consents", json={"agree_income_info": False})
            assert res.status_code == 200 and await traces() == set()

            await give_income()
            assert await traces() == {"소득 활성", "소득 만료"}
            consent = {"consent_version": "2026-10-09", "agree_terms": True, "agree_privacy": True}
            res = await http.post("/api/v1/me/consents", json=consent)  # 선택 동의를 빼고 다시 동의
            assert res.status_code == 200 and await traces() == set()
            res = await http.get("/api/v1/opportunities", params={"include_expired": "true"})
            labels = {
                item["title"]: item["eligibility"]["display_status"] for item in res.json()["items"]
            }
            assert labels == {"소득 만료": "missing_info", "소득 활성": "missing_info"}
    finally:
        await conn.rollback()
        await conn.close()


async def test_feed_lock_still_lets_rows_reference_the_profile() -> None:
    """피드가 프로필 행을 잠가도 이 사용자의 이벤트·알림 같은 행은 바로 넣는다. 프로필 수정만 기다린다.

    연결 셋이 서로의 행을 봐야 해서 사용자 행만 커밋하고 끝나면 지운다.
    """
    user_id = str(uuid.uuid4())
    setup = await connect()
    await setup.execute("insert into auth.users (id) values (%s)", (user_id,))
    await setup.execute("insert into profiles (id) values (%s)", (user_id,))
    await setup.commit()
    feed_conn, other = await connect(), await connect()
    try:
        await OpportunityRepository(feed_conn).refresh_judgments(user_id, now=datetime.now(UTC))
        await other.execute("set lock_timeout = '2s'")
        await other.execute(
            "insert into usage_events (user_id, event) values (%s, 'app_open')", (user_id,)
        )
        await other.execute("set lock_timeout = '200ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            await other.execute("update profiles set grade = 3 where id = %s", (user_id,))
    finally:
        for conn in (feed_conn, other):
            await conn.rollback()
            await conn.close()
        await setup.execute("delete from auth.users where id = %s", (user_id,))
        await setup.commit()
        await setup.close()
