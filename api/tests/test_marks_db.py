"""관심 표시(F-45) 통합 테스트: 피드·집계·상세의 표시, 공개 범위, 표시 바꾸기, 탈퇴. DATABASE_URL이 있을 때만 돈다.
테스트마다 트랜잭션을 되돌린다."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest

from app.config import Settings, get_settings
from app.db import get_conn
from app.main import create_app
from app.repositories.opportunities import FeedQuery, OpportunityRepository, decode_cursor
from app.schemas.opportunities import OpportunityItem
from tests.conftest import make_token
from tests.db_world import DATABASE_URL, build, connect, titles

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


async def test_not_interested_leaves_feed_and_counts() -> None:
    conn = await connect()
    try:
        world, me, other = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now)
        before = await repo.feed_counts(me, now=now)
        c, d = world.ids["교내 C"], world.ids["기타 D"]
        # 다른 학생의 표시는 내 목록·집계·상세와 상관없다
        assert await repo.set_mark(other, world.ids["장학 A"], "not_interested", now=now) == now
        assert await repo.set_mark(other, c, "not_interested", now=now) == now

        assert await repo.set_mark(me, d, "not_interested", now=now) == now
        assert await repo.set_mark(me, c, "interested", now=now) == now
        page = await repo.feed_page(me, FeedQuery(), now=now)
        assert "기타 D" not in titles(page.items, world)  # 관심 없음은 추천 목록에서 빠진다
        marks = {
            title: item.my_mark
            for title, item in zip(titles(page.items, world), page.items, strict=True)
        }
        assert marks["교내 C"] == "interested" and marks["장학 A"] is None
        counts = await repo.feed_counts(me, now=now)
        assert counts.model_dump() == {  # 기타 D(원문 확인 필요, D-1)만 빠진다
            **before.model_dump(),
            "undetermined": before.undetermined - 1,
            "needs_review": before.needs_review - 1,
            "deadline_soon": before.deadline_soon - 1,
        }

        everything = await repo.feed_page(me, FeedQuery(include_not_interested=True), now=now)
        hidden = [item for item in everything.items if item.my_mark == "not_interested"]
        assert titles(hidden, world) == ["기타 D"] and len(everything.items) == len(page.items) + 1
        assert await repo.feed_counts(me, now=now) == counts  # 집계는 목록 옵션과 상관없다

        # 표시는 사용자마다다. 내가 숨긴 공고는 다른 학생에게 그대로고, 그 학생이 숨긴 공고만 빠진다
        await repo.refresh_judgments(other, now=now)
        theirs = await repo.feed_page(other, FeedQuery(), now=now)
        assert "기타 D" in titles(theirs.items, world)
        assert not {"장학 A", "교내 C"} & set(titles(theirs.items, world))
        assert all(item.my_mark is None for item in theirs.items)

        # 상세에도 내 표시가 보이고, 표시를 지우면 목록과 집계가 돌아온다(상세를 연 C·D는 지원 가능이
        # 아니라 새 공고 수가 바뀌지 않는다)
        shown = {t: await repo.detail(me, world.ids[t], now=now) for t in ("기타 D", "교내 C")}
        assert {t: detail.my_mark for t, detail in shown.items() if detail} == {
            "기타 D": "not_interested",
            "교내 C": "interested",
        }
        await repo.clear_mark(me, c)
        assert (await repo.detail(me, c, now=now)).my_mark is None  # type: ignore[union-attr]
        page = await repo.feed_page(me, FeedQuery(), now=now)
        assert "기타 D" not in titles(page.items, world)  # 다른 공고의 표시는 그대로다
        await repo.clear_mark(me, d)
        await repo.clear_mark(me, d)  # 없는 표시를 지워도 그대로
        page = await repo.feed_page(me, FeedQuery(), now=now)
        assert "기타 D" in titles(page.items, world)
        assert await repo.feed_counts(me, now=now) == before
        row = await (
            await conn.execute(
                "select count(*) as n from opportunity_marks where user_id = %s", (other,)
            )
        ).fetchone()
        assert row == {"n": 2}  # 내 표시를 지워도 다른 학생의 표시는 남는다
    finally:
        await conn.rollback()
        await conn.close()


async def test_marks_follow_the_detail_visibility() -> None:
    """표시는 상세를 열 수 있는 공고에만: 남의 포스터·수강하지 않는 과목 공지·숨김 공고는 None."""
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        for title in ("남의 포스터 H", "다른 과목 K", "숨김 L"):
            assert await repo.set_mark(me, world.ids[title], "interested", now=now) is None
        assert await repo.set_mark(me, world.ids["만료 M"], "interested", now=now) == now
        assert await repo.set_mark(me, world.ids["내 포스터 I"], "not_interested", now=now) == now
        # 준비한 공고는 숨김이 되어도 본인에게 보이므로 표시할 수 있다
        a = world.ids["장학 A"]
        await conn.execute("update opportunities set status = 'hidden' where id = %s", (a,))
        assert await repo.set_mark(me, a, "interested", now=now) == now
        rows = await (
            await conn.execute(
                "select o.title, m.mark from opportunity_marks m join opportunities o"
                " on o.id = m.opportunity_id where m.user_id = %s order by o.title",
                (me,),
            )
        ).fetchall()
        assert [(row["title"], row["mark"]) for row in rows] == [
            ("내 포스터 I", "not_interested"),
            ("만료 M", "interested"),
            ("장학 A", "interested"),
        ]
        # 마감 공고는 include_expired 목록에서 내 표시와 함께 보인다
        await repo.refresh_judgments(me, now=now, include_expired=True)
        expired = await repo.feed_page(me, FeedQuery(include_expired=True), now=now)
        assert {
            t: i.my_mark for t, i in zip(titles(expired.items, world), expired.items, strict=True)
        }["만료 M"] == "interested"

        # 수강 중인 과목의 공지는 표시할 수 있고, 수강을 끝내면 준비한 공고만 표시할 수 있다
        j = world.ids["과목 공지 J"]
        assert await repo.set_mark(me, j, "interested", now=now) == now
        await conn.execute("update lms_courses set is_active = false where user_id = %s", (me,))
        assert await repo.set_mark(me, j, "not_interested", now=now) is None
        await conn.execute(
            "insert into prep_plans (user_id, opportunity_id) values (%s, %s)", (me, j)
        )
        assert await repo.set_mark(me, j, "not_interested", now=now) == now
        # 병합된 공고도 준비했으면 표시할 수 있다
        await conn.execute("update opportunities set status = 'merged' where id = %s", (a,))
        assert await repo.set_mark(me, a, "not_interested", now=now) == now

        # 첫 요청이 표시여도 프로필 행을 이름과 함께 만든다
        newbie = str(uuid.uuid4())
        await conn.execute("insert into auth.users (id) values (%s)", (newbie,))
        b = world.ids["장학 B"]
        assert await repo.set_mark(newbie, b, "interested", now=now, display_name="새 학생") == now
        row = await (
            await conn.execute("select display_name from profiles where id = %s", (newbie,))
        ).fetchone()
        assert row == {"display_name": "새 학생"}
    finally:
        await conn.rollback()
        await conn.close()


def removed_from_counts(item: OpportunityItem) -> dict[str, int]:
    """공고 하나를 숨기면 요약 숫자에서 빠지는 칸. 웹 lib/feedCounts.ts의 countDelta와 같은 규칙이다."""
    status, display = item.eligibility.status, item.eligibility.display_status
    soon = status != "ineligible" and item.d_day is not None and 0 <= item.d_day <= 3
    return {
        "eligible": int(status == "eligible"),
        "new_eligible": int(status == "eligible" and item.is_new),
        "undetermined": int(status == "undetermined"),
        "missing_info": int(display == "missing_info"),
        "needs_review": int(display == "needs_review"),
        "ineligible": int(status == "ineligible"),
        "deadline_soon": int(soon),
    }


async def test_hiding_takes_a_posting_out_of_its_count_buckets() -> None:
    """공고마다 숨기면 그 공고가 들어 있던 숫자 칸만 1씩 준다. 홈은 같은 규칙으로 숫자를 고친다."""
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now)
        before = (await repo.feed_counts(me, now=now)).model_dump()
        page = await repo.feed_page(me, FeedQuery(limit=50), now=now)
        touched: set[str] = set()
        for title, item in zip(titles(page.items, world), page.items, strict=True):
            await repo.set_mark(me, item.id, "not_interested", now=now)
            after = (await repo.feed_counts(me, now=now)).model_dump()
            expected = removed_from_counts(item)
            assert {key: before[key] - after[key] for key in before} == expected, title
            touched |= {key for key, value in expected.items() if value}
            await repo.clear_mark(me, item.id)
        assert touched == set(before)  # 일곱 칸을 모두 거쳤다
        assert (await repo.feed_counts(me, now=now)).model_dump() == before
    finally:
        await conn.rollback()
        await conn.close()


async def test_paging_with_hidden_postings() -> None:
    """한 쪽에 하나씩 넘겨도 관심 없음 공고는 include_not_interested일 때만 나오고 빠지거나 겹치는 공고가
    없다. 숨기기 전에 받은 커서도 그 뒤부터 이어진다."""
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        await repo.refresh_judgments(me, now=now)

        async def walk(query: FeedQuery) -> list[str]:
            seen: list[str] = []
            while True:
                page = await repo.feed_page(me, query, now=now)
                seen += titles(page.items, world)
                if page.next_cursor is None:
                    return seen
                query = replace(query, cursor=decode_cursor(page.next_cursor))

        ineligible_only = frozenset({"ineligible"})
        everything = await walk(FeedQuery(limit=1))
        ineligible = await walk(FeedQuery(limit=1, eligibility=ineligible_only))
        assert "장학 B" in everything and "장학 B" in ineligible

        query = FeedQuery(limit=1)  # 장학 B가 마지막인 쪽까지 받은 커서
        while True:
            page = await repo.feed_page(me, query, now=now)
            assert page.next_cursor is not None
            query = replace(query, cursor=decode_cursor(page.next_cursor))
            if titles(page.items, world) == ["장학 B"]:
                break
        await repo.set_mark(me, world.ids["장학 B"], "not_interested", now=now)
        assert await walk(query) == everything[everything.index("장학 B") + 1 :]

        assert await walk(FeedQuery(limit=1)) == [t for t in everything if t != "장학 B"]
        assert await walk(FeedQuery(limit=1, include_not_interested=True)) == everything
        assert await walk(FeedQuery(limit=1, eligibility=ineligible_only)) == [
            t for t in ineligible if t != "장학 B"
        ]
        both = FeedQuery(limit=1, eligibility=ineligible_only, include_not_interested=True)
        assert await walk(both) == ineligible
    finally:
        await conn.rollback()
        await conn.close()


async def test_marks_wait_for_a_feed_request() -> None:
    """피드 요청이 프로필 행을 잠근 동안 표시 바꾸기는 기다린다. 피드 응답 하나의 목록과 숫자가 같은
    표시를 본다. 연결 둘이 서로의 행을 봐야 해서 사용자 행만 커밋하고 끝나면 지운다."""
    user_id = str(uuid.uuid4())
    setup = await connect()
    await setup.execute("insert into auth.users (id) values (%s)", (user_id,))
    await setup.execute("insert into profiles (id) values (%s)", (user_id,))
    await setup.commit()
    feed_conn, mark_conn = await connect(), await connect()
    try:
        await OpportunityRepository(feed_conn).refresh_judgments(user_id, now=datetime.now(UTC))
        repo, posting = OpportunityRepository(mark_conn), str(uuid.uuid4())
        await mark_conn.execute("set lock_timeout = '200ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            await repo.set_mark(user_id, posting, "interested", now=datetime.now(UTC))
        await mark_conn.rollback()
        await mark_conn.execute("set lock_timeout = '200ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            await repo.clear_mark(user_id, posting)
        await mark_conn.rollback()
        await feed_conn.rollback()  # 피드 요청이 끝나면 바로 된다
        await mark_conn.execute("set lock_timeout = '2s'")
        await repo.clear_mark(user_id, posting)
    finally:
        for conn in (feed_conn, mark_conn):
            await conn.rollback()
            await conn.close()
        await setup.execute("delete from auth.users where id = %s", (user_id,))
        await setup.commit()
        await setup.close()


async def test_changing_a_mark_keeps_one_row_and_its_time() -> None:
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        b = world.ids["장학 B"]
        later = now + timedelta(hours=1)
        assert await repo.set_mark(me, b, "interested", now=now) == now
        assert await repo.set_mark(me, b, "interested", now=later) == now  # 같은 표시는 처음 시각
        assert await repo.set_mark(me, b, "not_interested", now=later) == later  # 바꾸면 새 시각
        rows = await (
            await conn.execute("select mark from opportunity_marks where user_id = %s", (me,))
        ).fetchall()
        assert rows == [{"mark": "not_interested"}]
        with pytest.raises(psycopg.errors.CheckViolation):
            await conn.execute(
                "update opportunity_marks set mark = 'maybe' where user_id = %s", (me,)
            )
    finally:
        await conn.rollback()
        await conn.close()


async def test_profile_deletion_removes_marks() -> None:
    """탈퇴(DELETE /me)는 profiles를 지운다. 표시도 같이 지워진다(on delete cascade)."""
    conn = await connect()
    try:
        world, me, _ = await build(conn)
        repo, now = OpportunityRepository(conn), world.now
        await repo.set_mark(me, world.ids["장학 B"], "interested", now=now)
        await conn.execute("delete from profiles where id = %s", (me,))
        row = await (await conn.execute("select count(*) as n from opportunity_marks")).fetchone()
        assert row == {"n": 0}
    finally:
        await conn.rollback()
        await conn.close()


async def test_mark_api_round_trip(settings: Settings) -> None:
    """라우터부터 DB까지: 숨기기 → 피드·집계에서 빠짐 → 숨김 탭(include_not_interested) → 다시 보기."""
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
        b = world.ids["장학 B"]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as http:
            first = (await http.get("/api/v1/opportunities")).json()
            res = await http.put(f"/api/v1/opportunities/{b}/mark", json={"mark": "not_interested"})
            assert res.status_code == 200 and res.json()["mark"] == "not_interested"
            assert res.json()["marked_at"].endswith("+09:00")
            feed = (await http.get("/api/v1/opportunities")).json()
            assert b not in [item["id"] for item in feed["items"]]
            assert feed["counts"]["ineligible"] == first["counts"]["ineligible"] - 1
            hidden = (
                await http.get("/api/v1/opportunities", params={"include_not_interested": "true"})
            ).json()
            assert [i["my_mark"] for i in hidden["items"] if i["id"] == b] == ["not_interested"]
            res = await http.put(
                f"/api/v1/opportunities/{world.ids['남의 포스터 H']}/mark",
                json={"mark": "interested"},
            )
            assert res.status_code == 404
            assert (await http.delete(f"/api/v1/opportunities/{b}/mark")).status_code == 204
            back = (await http.get("/api/v1/opportunities")).json()
            assert b in [item["id"] for item in back["items"]] and back["counts"] == first["counts"]
    finally:
        await conn.rollback()
        await conn.close()
