"""알림 예약·발송·알림함 통합 테스트(F-33·F-35). DATABASE_URL이 있을 때만 돈다.

예약 규칙(누구에게 무엇을 언제)이 이 PR의 핵심이라 여기서 하나씩 본다.
실제 Supabase DB로는 돌리지 않는다(사용자·공고를 만들고 지운다).
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from app.eligibility import KST
from app.eval.world import connect
from app.repositories.notifications import (
    NOTIFY_HOUR,
    PROFILE_DAILY,
    NotificationRepository,
)
from tests.db_world import DATABASE_URL

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=KST)  # 알림 시각(09:00) 전


@dataclass
class World:
    conn: psycopg.AsyncConnection
    run: str
    users: list[str] = field(default_factory=list)
    ids: dict[str, str] = field(default_factory=dict)

    @property
    def repo(self) -> NotificationRepository:
        return NotificationRepository(self.conn)

    async def user(self, **settings: Any) -> str:
        user_id = str(uuid.uuid4())
        self.users.append(user_id)
        await self.conn.execute("insert into auth.users (id) values (%s)", (user_id,))
        await self.conn.execute(
            "insert into profiles (id, display_name) values (%s, '알림 학생')", (user_id,)
        )
        if settings:
            names = ", ".join(("user_id", *settings))
            marks = ", ".join(["%s"] * (len(settings) + 1))
            await self.conn.execute(
                f"insert into user_settings ({names}) values ({marks})",
                (user_id, *settings.values()),
            )
        return user_id

    async def opportunity(self, title: str, *, days: float | None = 10, **columns: Any) -> str:
        values: dict[str, Any] = {
            "source_type": "school_notice",
            "category": "scholarship",
            "title": title,
            "deadline_at": None if days is None else NOW + timedelta(days=days),
            "extraction_run_id": self.run,
            **columns,
        }
        names = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        row = await (
            await self.conn.execute(
                f"insert into opportunities ({names}) values ({marks}) returning id::text as id",
                tuple(values.values()),
            )
        ).fetchone()
        assert row is not None
        self.ids[title] = row["id"]
        return str(row["id"])

    async def judge(
        self, user_id: str, opportunity_id: str, status: str, missing: Sequence[str] = ()
    ) -> None:
        await self.conn.execute(
            "insert into eligibility_results (user_id, opportunity_id, status, condition_results,"
            " missing_fields) values (%s, %s, %s, '[]'::jsonb, %s)"
            " on conflict (user_id, opportunity_id) do update set status = excluded.status,"
            " missing_fields = excluded.missing_fields",
            (user_id, opportunity_id, status, list(missing)),
        )

    async def mark(self, user_id: str, opportunity_id: str, mark: str) -> None:
        await self.conn.execute(
            "insert into opportunity_marks (user_id, opportunity_id, mark) values (%s, %s, %s)",
            (user_id, opportunity_id, mark),
        )

    async def prepare(self, user_id: str, opportunity_id: str) -> None:
        await self.conn.execute(
            "insert into prep_plans (user_id, opportunity_id) values (%s, %s)",
            (user_id, opportunity_id),
        )

    async def view(self, user_id: str, opportunity_id: str) -> None:
        await self.conn.execute(
            "insert into opportunity_views (user_id, opportunity_id) values (%s, %s)",
            (user_id, opportunity_id),
        )

    async def subscribe(self, user_id: str) -> None:
        await self.conn.execute(
            "insert into push_subscriptions (user_id, endpoint, p256dh, auth)"
            " values (%s, %s, 'p', 'a')",
            (user_id, f"https://push.example/{user_id}"),
        )

    async def keys(self, user_id: str) -> list[str]:
        """그 사용자의 알림을 (종류, 대상 제목, KST 시각) 글로 본다."""
        rows = await (
            await self.conn.execute(
                "select n.type, o.title, n.status,"
                " to_char(n.scheduled_at at time zone 'Asia/Seoul', 'MM-DD HH24:MI') as at,"
                " n.body from notifications n left join opportunities o on o.id = n.opportunity_id"
                " where n.user_id = %s order by n.scheduled_at, n.dedupe_key",
                (user_id,),
            )
        ).fetchall()
        return [f"{row['type']}|{row['title']}|{row['at']}|{row['status']}" for row in rows]

    async def bodies(self, user_id: str) -> list[str]:
        rows = await (
            await self.conn.execute(
                "select body from notifications where user_id = %s order by dedupe_key", (user_id,)
            )
        ).fetchall()
        return [row["body"] for row in rows]


@asynccontextmanager
async def world() -> AsyncIterator[World]:
    """사용자·공고를 만들고 끝나면 지운다. 알림은 공고·사용자와 함께 지워진다(cascade)."""
    conn = await connect(DATABASE_URL)
    run = await (
        await conn.execute(
            "insert into agent_runs (trigger_type, status) values ('batch_crawl', 'succeeded')"
            " returning id::text as id"
        )
    ).fetchone()
    assert run is not None
    built = World(conn, run["id"])
    try:
        yield built
    finally:
        await conn.execute("delete from opportunities where extraction_run_id = %s", (run["id"],))
        await conn.execute("delete from auth.users where id = any(%s::uuid[])", (built.users,))
        await conn.close()


# ── 예약: 누구에게 ──────────────────────────────────────────────────────────


async def test_the_deadline_notice_goes_to_eligible_and_prepared_opportunities() -> None:
    """적격이거나 준비한 공고만이다. 부적격인데 "그래도 준비하기"로 준비한 공고도 알려 준다."""
    async with world() as built:
        student = await built.user()
        eligible = await built.opportunity("적격 장학", days=10)
        prepared = await built.opportunity("그래도 준비한 장학", days=10)
        ineligible = await built.opportunity("부적격 장학", days=10)
        undetermined = await built.opportunity("판정 불가 장학", days=10)
        await built.judge(student, eligible, "eligible")
        await built.judge(student, prepared, "ineligible")
        await built.prepare(student, prepared)
        await built.judge(student, ineligible, "ineligible")
        await built.judge(student, undetermined, "undetermined", ["grade"])

        await built.repo.schedule(now=NOW)
        titles = {
            line.split("|")[1] for line in await built.keys(student) if "deadline_soon" in line
        }
        assert titles == {"적격 장학", "그래도 준비한 장학"}


async def test_hidden_opportunities_and_muted_types_make_no_row() -> None:
    """숨긴 공고는 공고 알림에서 빠지고(F-45), 설정에서 끈 종류는 행을 만들지 않는다(ERD)."""
    async with world() as built:
        student = await built.user()
        muted = await built.user(muted_notification_types=["deadline_soon"])
        hidden = await built.opportunity("숨긴 장학", days=10)
        plain = await built.opportunity("보이는 장학", days=10)
        for user in (student, muted):
            for opportunity in (hidden, plain):
                await built.judge(user, opportunity, "eligible")
                await built.view(user, opportunity)  # 새 공고 알림은 빼고 본다
        await built.mark(student, hidden, "not_interested")

        # 만들지 않는 것과 만들었다가 지우는 것은 다르다. removed가 0이어야 "만들지 않았다"다
        result = await built.repo.schedule(now=NOW)
        assert result.removed == 0
        assert [line.split("|")[1] for line in await built.keys(student)] == [
            "보이는 장학",
            "보이는 장학",
        ]
        assert await built.keys(muted) == []  # 끈 종류라 행이 없다


async def test_a_poster_only_notifies_the_student_who_uploaded_it() -> None:
    async with world() as built:
        owner, other = await built.user(), await built.user()
        poster = await built.opportunity(
            "내 포스터", days=10, source_type="poster", category="contest", uploaded_by=owner
        )
        for user in (owner, other):
            await built.judge(user, poster, "eligible")
        result = await built.repo.schedule(now=NOW)
        assert result.removed == 0  # 만들었다가 지운 것이 아니라 아예 만들지 않는다
        assert len(await built.keys(owner)) == 3  # 새 공고 + D-3 + D-1
        assert await built.keys(other) == []


# ── 예약: 언제 ─────────────────────────────────────────────────────────────


async def test_the_times_are_kst_nine_in_the_morning() -> None:
    async with world() as built:
        student = await built.user()
        opportunity = await built.opportunity("아홉시 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)
        times = [line.split("|")[2] for line in await built.keys(student)]
        assert NOTIFY_HOUR == 9
        assert times == ["10-15 09:00", "10-22 09:00", "10-24 09:00"]  # 새 공고 · D-3 · D-1


async def test_a_notice_whose_day_has_passed_is_not_created() -> None:
    """마감 이틀 전에 들어온 공고가 D-3·D-1을 한꺼번에 받으면 안 된다."""
    async with world() as built:
        student = await built.user()
        soon = await built.opportunity("내일 마감", days=1.5)
        await built.judge(student, soon, "eligible")
        await built.repo.schedule(now=NOW)
        deadlines = [line for line in await built.keys(student) if "deadline" in line]
        assert len(deadlines) == 1  # D-1만. D-3은 이미 지났다
        assert "D-1" in " ".join(await built.bodies(student))
        assert "D-3" not in " ".join(await built.bodies(student))


async def test_a_new_opportunity_is_announced_the_next_morning() -> None:
    """09시 전에 예약하면 오늘 09시, 지난 뒤면 내일 09시다."""
    async with world() as built:
        student = await built.user()
        opportunity = await built.opportunity("새 장학", days=30)
        await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)  # 08:00
        assert "new_eligible|새 장학|10-15 09:00|pending" in await built.keys(student)

        other = await built.user()
        await built.judge(other, opportunity, "eligible")
        await built.repo.schedule(now=NOW.replace(hour=10))  # 09시가 지났다
        assert "new_eligible|새 장학|10-16 09:00|pending" in await built.keys(other)


# ── 예약: 다시 돌릴 때 ─────────────────────────────────────────────────────


async def test_running_twice_makes_nothing_new() -> None:
    async with world() as built:
        student = await built.user()
        opportunity = await built.opportunity("한 번 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        first = await built.repo.schedule(now=NOW)
        before = await built.keys(student)
        again = await built.repo.schedule(now=NOW)
        assert (first.created, again.created, again.rescheduled, again.removed) == (3, 0, 0, 0)
        assert await built.keys(student) == before


async def test_a_moved_deadline_only_moves_the_pending_rows() -> None:
    """마감이 바뀌면 아직 보내지 않은 알림의 시각만 고친다(명세 10장)."""
    async with world() as built:
        student = await built.user()
        opportunity = await built.opportunity("미뤄진 장학", days=4.5)
        await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)  # 마감 10-19 20:00 → D-3 10-16, D-1 10-18
        assert "deadline_soon|미뤄진 장학|10-16 09:00|pending" in await built.keys(student)

        sent = NOW + timedelta(days=2)  # D-3 아침이 지났다
        await built.repo.send(now=sent)
        assert "deadline_soon|미뤄진 장학|10-16 09:00|succeeded" in await built.keys(student)

        await built.conn.execute(
            "update opportunities set deadline_at = deadline_at + interval '5 days' where id = %s",
            (opportunity,),
        )
        moved = await built.repo.schedule(now=sent)
        assert moved.rescheduled == 1  # 아직 안 보낸 D-1만 옮긴다
        lines = await built.keys(student)
        assert "deadline_soon|미뤄진 장학|10-16 09:00|succeeded" in lines  # 보낸 것은 그대로
        assert "deadline_soon|미뤄진 장학|10-23 09:00|pending" in lines  # 마감 10-24 20:00


async def test_rows_that_lost_their_reason_are_removed() -> None:
    """준비를 취소하거나 숨기거나 마감이 지나면 아직 안 보낸 알림을 지운다."""
    async with world() as built:
        student = await built.user()
        cancelled = await built.opportunity("취소할 장학", days=10)
        hidden = await built.opportunity("숨길 장학", days=10)
        seen = await built.opportunity("열어 볼 장학", days=10)
        for opportunity in (cancelled, hidden, seen):
            await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)
        assert len(await built.keys(student)) == 9  # 공고 3개 × (새 공고 + D-3 + D-1)

        await built.judge(student, cancelled, "ineligible")  # 판정이 바뀌었다
        await built.mark(student, hidden, "not_interested")
        await built.view(student, seen)  # 상세를 열었다 → 새 공고 알림은 뜻이 없다
        removed = (await built.repo.schedule(now=NOW)).removed
        assert removed == 7  # 취소 3 + 숨김 3 + 열어 본 공고의 새 공고 알림 1
        lines = await built.keys(student)
        assert [line.split("|")[:2] for line in lines] == [
            ["deadline_soon", "열어 볼 장학"],
            ["deadline_soon", "열어 볼 장학"],
        ]


# ── 발송 ───────────────────────────────────────────────────────────────────


async def test_sending_closes_the_row_even_without_a_push_subscription() -> None:
    """푸시를 못 보내도 알림함에는 남아야 한다(ERD: 푸시만 건너뛴다)."""
    async with world() as built:
        plain = await built.user()
        subscribed = await built.user()
        await built.subscribe(subscribed)
        opportunity = await built.opportunity("발송 장학", days=10)
        for user in (plain, subscribed):
            await built.judge(user, opportunity, "eligible")
        await built.repo.schedule(now=NOW)

        sent = await built.repo.send(now=NOW + timedelta(days=1))
        result = sent.result
        assert (result.due, result.sent, result.skipped) == (2, 2, 0)  # 새 공고 알림 2건
        assert result.pushable == 1  # 구독이 있는 사용자만
        # 보낸 알림 번호도 함께 온다(푸시 발송이 이 번호로 구독을 찾는다, F-33)
        assert len(sent.ids) == 2
        assert all("succeeded" in line for line in await built.keys(plain) if "new_" in line)


async def test_a_notification_is_never_closed_twice() -> None:
    """두 배치가 겹쳐 돌아도 보낸 알림을 다시 보낸 것으로 바꾸지 않는다(하루 한도가 틀어진다)."""
    async with world() as built:
        student = await built.user()
        opportunity = await built.opportunity("한 번만 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)
        sent_at = NOW + timedelta(days=1)
        due = await built.repo.due(now=sent_at)
        assert await built.repo.mark_sent([item.id for item in due], now=sent_at) == len(due)

        again = await built.repo.mark_sent(
            [item.id for item in due], now=sent_at + timedelta(days=1)
        )
        assert again == 0
        rows = await (
            await built.conn.execute(
                "select to_char(sent_at at time zone 'Asia/Seoul', 'MM-DD') as day"
                " from notifications where user_id = %s and sent_at is not null",
                (student,),
            )
        ).fetchall()
        assert {row["day"] for row in rows} == {"10-16"}  # 처음 보낸 날 그대로


async def test_a_hidden_opportunity_is_checked_again_before_sending() -> None:
    """예약한 뒤 숨겼으면 보내지 않고 둔다(명세 10장)."""
    async with world() as built:
        student = await built.user()
        opportunity = await built.opportunity("예약 뒤 숨길 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)
        await built.mark(student, opportunity, "not_interested")

        result = (await built.repo.send(now=NOW + timedelta(days=1))).result
        assert (result.sent, result.skipped) == (0, 1)
        assert all("pending" in line for line in await built.keys(student))


async def test_only_one_profile_notice_goes_out_a_day() -> None:
    """ERD: profile_needed 하루 1건 제한은 발송 배치가 건다."""
    async with world() as built:
        student = await built.user()
        for index in range(3):
            opportunity = await built.opportunity(f"정보 필요 {index}", days=10)
            await built.judge(student, opportunity, "undetermined", ["region"])
            await built.view(student, opportunity)
        await built.repo.schedule(now=NOW)

        first = (await built.repo.send(now=NOW + timedelta(days=1))).result
        assert (first.due, first.sent, first.skipped) == (3, PROFILE_DAILY, 3 - PROFILE_DAILY)
        later = (await built.repo.send(now=NOW + timedelta(days=1, hours=1))).result
        assert later.sent == 0  # 같은 날에는 더 보내지 않는다
        tomorrow = (await built.repo.send(now=NOW + timedelta(days=2))).result
        assert tomorrow.sent == PROFILE_DAILY
        assert "거주지역을 입력하면 판정할 수 있어요" in (await built.bodies(student))[0]


# ── 알림함 ─────────────────────────────────────────────────────────────────


async def test_the_inbox_shows_past_notifications_newest_first() -> None:
    async with world() as built:
        student = await built.user()
        other = await built.user()
        opportunity = await built.opportunity("알림함 장학", days=10)
        for user in (student, other):
            await built.judge(user, opportunity, "eligible")
        await built.repo.schedule(now=NOW)

        before = await built.repo.listing(student, now=NOW)  # 09시 전 → 아직 아무것도 안 보인다
        assert (before.items, before.unread_count) == ([], 0)

        later = NOW + timedelta(days=30)
        box = await built.repo.listing(student, now=later)
        assert [item.type for item in box.items] == [
            "deadline_soon",
            "deadline_soon",
            "new_eligible",
        ]
        assert [item.scheduled_at for item in box.items] == sorted(
            (item.scheduled_at for item in box.items), reverse=True
        )
        assert box.unread_count == 3
        assert all(item.link is not None and item.link.type == "opportunity" for item in box.items)
        assert all(item.scheduled_at.utcoffset() == timedelta(hours=9) for item in box.items)

        # 남의 알림은 섞이지 않는다
        assert len((await built.repo.listing(other, now=later)).items) == 3


async def test_the_inbox_pages_with_a_cursor() -> None:
    async with world() as built:
        student = await built.user()
        for index in range(3):
            opportunity = await built.opportunity(f"쪽 {index}", days=10 + index)
            await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)
        later = NOW + timedelta(days=40)

        first = await built.repo.listing(student, now=later, limit=5)
        assert len(first.items) == 5 and first.next_cursor is not None
        second = await built.repo.listing(student, now=later, limit=5, cursor=first.next_cursor)
        assert len(second.items) == 4 and second.next_cursor is None
        ids = [item.id for item in first.items + second.items]
        assert len(set(ids)) == 9  # 겹치지도 빠지지도 않는다
        with pytest.raises(ValueError):  # 조건이 다른 목록의 cursor는 쓸 수 없다
            await built.repo.listing(student, now=later, unread_only=True, cursor=first.next_cursor)


async def test_reading_marks_only_mine_and_only_what_has_arrived() -> None:
    async with world() as built:
        student = await built.user()
        other = await built.user()
        early = await built.opportunity("지금 알림", days=10)
        late = await built.opportunity("나중 알림", days=40)
        for user in (student, other):
            for opportunity in (early, late):
                await built.judge(user, opportunity, "eligible")
                await built.view(user, opportunity)
        await built.repo.schedule(now=NOW)

        middle = NOW + timedelta(days=9)  # 지금 알림의 D-3만 지났다
        box = await built.repo.listing(student, now=middle)
        assert len(box.items) == 1
        assert await built.repo.read(student, now=middle) == 0
        assert (await built.repo.listing(other, now=middle)).unread_count == 1  # 남의 것은 그대로
        later = NOW + timedelta(days=40)
        assert (await built.repo.listing(student, now=later)).unread_count == 3  # 아직 안 온 것들

        picked = (await built.repo.listing(student, now=later)).items[0]
        assert await built.repo.read(student, now=later, ids=[uuid.UUID(picked.id)]) == 2
