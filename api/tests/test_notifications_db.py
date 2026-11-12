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
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import jobs
from app.eligibility import ENGINE_VERSION, KST
from app.eval.world import connect
from app.repositories.notifications import (
    NOTIFY_HOUR,
    PROFILE_DAILY,
    NotificationRepository,
)
from app.repositories.opportunities import OpportunityRepository, Refresh
from tests.db_world import DATABASE_URL

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=KST)  # 알림 시각(09:00) 전
ASKED = (
    "region",
    "age",
    "enrollment_status",
)  # 서로 다른 물어볼 항목 셋(정보 필요 알림은 항목마다 하나)


@dataclass
class World:
    conn: psycopg.AsyncConnection
    run: str
    users: list[str] = field(default_factory=list)
    ids: dict[str, str] = field(default_factory=dict)

    @property
    def repo(self) -> NotificationRepository:
        return NotificationRepository(self.conn)

    async def user(self, *, consented: bool = True, **settings: Any) -> str:
        """사용자 하나. consented면 약관·개인정보 동의를 마쳤다(예약 작업은 동의한 사용자만 판정한다)."""
        user_id = str(uuid.uuid4())
        self.users.append(user_id)
        await self.conn.execute("insert into auth.users (id) values (%s)", (user_id,))
        agreed = NOW if consented else None
        await self.conn.execute(
            "insert into profiles (id, display_name, terms_agreed_at, privacy_agreed_at)"
            " values (%s, '알림 학생', %s, %s)",
            (user_id, agreed, agreed),
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

    async def requirement(
        self, opportunity_id: str, field: str, operator: str, value: Any, *, version: int = 1
    ) -> None:
        """요건 한 줄. version이 1보다 크면 공고의 요건 버전을 그 값으로 둔다(다시 추출한 셈)."""
        await self.conn.execute(
            "insert into requirements (opportunity_id, clause_no, field, operator, value)"
            " values (%s, 1, %s, %s, %s)",
            (opportunity_id, field, operator, Jsonb(value)),
        )
        if version > 1:
            await self.conn.execute(
                "update opportunities set requirements_version = %s where id = %s",
                (version, opportunity_id),
            )

    async def status(self, user_id: str, opportunity_id: str) -> str | None:
        """저장된 판정. 없으면 None."""
        row = await (
            await self.conn.execute(
                "select status::text as status from eligibility_results"
                " where user_id = %s and opportunity_id = %s",
                (user_id, opportunity_id),
            )
        ).fetchone()
        return row["status"] if row else None

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


# ── 예약 앞에서 판정 다시 계산 (jobs.schedule_notifications) ──────────────


async def _tx_conn() -> psycopg.AsyncConnection:
    """요청 풀처럼 autocommit이 아닌 연결(블록이 끝날 때 커밋·롤백한다)."""
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row, prepare_threshold=None
    )


async def _morning(
    built: World, repo_type: type[OpportunityRepository] = OpportunityRepository
) -> None:
    """예약 작업을 운영처럼 돌린다. 요청·스케줄러처럼 autocommit이 아닌 연결 하나를 두 저장소에 함께
    주고, 블록이 끝날 때 확정한다. 그래야 사용자마다 따로 확정하는지(세이브포인트가 아닌지) 볼 수 있다."""
    async with await _tx_conn() as conn:
        await jobs.schedule_notifications(NotificationRepository(conn), repo_type(conn), now=NOW)


async def test_the_morning_job_judges_a_student_who_has_not_opened_the_feed() -> None:
    """판정은 피드·상세를 열 때 계산된다. 예약 작업이 그 전에 다시 계산하지 않으면 공고가 들어온 뒤
    앱을 열지 않은 학생에게는 새 공고·정보 필요 알림이 가지 않는다(PRD 6장)."""
    async with world() as built:
        student = await built.user()
        await built.opportunity("새 장학", days=None)  # 요건 없음, 원문 확인 필요 아님 → 지원 가능
        needs_gpa = await built.opportunity("평점 장학", days=None)
        await built.requirement(needs_gpa, "gpa_last_semester", "gte", 3.0)  # 평점을 안 넣었다
        await built.repo.schedule(now=NOW)
        assert await built.keys(student) == []  # 저장된 판정이 없으면 저장소는 예약하지 않는다

        await _morning(built)
        assert await built.keys(student) == [
            "new_eligible|새 장학|10-15 09:00|pending",
            "profile_needed|평점 장학|10-15 09:00|pending",
        ]


async def test_the_morning_job_does_not_announce_with_an_old_judgment() -> None:
    """요건을 다시 추출하면(요건 버전이 오르면) 저장된 판정은 낡은 것이다. 예약은 다시 계산한 판정을
    보고, 옛 '지원 가능'으로 새 공고 알림을 만들지 않는다."""
    async with world() as built:
        student = await built.user()
        await built.conn.execute(
            "update profiles set gpa_last_semester = 3.0 where id = %s", (student,)
        )
        opportunity = await built.opportunity("다시 추출한 장학", days=None)
        await built.conn.execute(  # 요건 버전 1, 지금 엔진으로 낸 '지원 가능'
            "insert into eligibility_results (user_id, opportunity_id, status, condition_results,"
            " requirements_version, engine_version) values (%s, %s, 'eligible', '[]'::jsonb, 1, %s)",
            (student, opportunity, ENGINE_VERSION),
        )
        await built.requirement(opportunity, "gpa_last_semester", "gte", 4.0, version=2)

        await _morning(built)
        assert await built.status(student, opportunity) == "ineligible"
        assert await built.keys(student) == []


async def test_a_student_whose_judgment_fails_does_not_stop_the_others() -> None:
    """한 사용자의 판정이 저장한 뒤에 터져도 그 사용자의 트랜잭션만 되돌리고(저장한 판정도) 나머지는 예약한다."""
    async with world() as built:
        broken, fine = await built.user(), await built.user()
        opportunity = await built.opportunity("새 장학", days=None)

        class Flaky(OpportunityRepository):
            async def _upsert(
                self, user_id: str, payload: list[dict[str, Any]], now: datetime
            ) -> None:
                await super()._upsert(user_id, payload, now)
                if user_id == broken:
                    await self.conn.execute("select 1 / 0")

        await _morning(built, Flaky)
        assert await built.status(broken, opportunity) is None
        assert await built.keys(broken) == []
        assert await built.keys(fine) == ["new_eligible|새 장학|10-15 09:00|pending"]


async def test_the_morning_job_commits_each_student_before_the_next() -> None:
    """사용자마다 따로 확정한다. 다음 사용자를 판정할 때 앞 사용자의 판정은 이미 보이고 프로필 잠금도
    풀려 있다. 한 트랜잭션에 모두 넣으면 작업이 끝날 때까지 그 사용자의 프로필 저장·탈퇴가 기다린다."""
    async with world() as built:
        # 예약 작업은 사용자를 id 순으로 본다
        first, second = sorted([await built.user(), await built.user()])
        opportunity = await built.opportunity("새 장학", days=None)
        seen: list[tuple[str | None, bool]] = []

        class Watching(OpportunityRepository):
            async def refresh_judgments(self, user_id: str, **kwargs: Any) -> Refresh:
                if user_id == second:
                    try:  # 다른 연결이 앞 사용자의 프로필을 바로 잠글 수 있나(탈퇴가 하는 잠금)
                        await built.conn.execute(
                            "select 1 from profiles where id = %s for update nowait", (first,)
                        )
                        free = True
                    except psycopg.errors.LockNotAvailable:
                        free = False
                    seen.append((await built.status(first, opportunity), free))
                return await super().refresh_judgments(user_id, **kwargs)

        await _morning(built, Watching)
        assert seen == [("eligible", True)]


async def test_the_morning_job_stops_when_the_connection_is_lost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """연결이 끊기면 남은 사용자도 모두 실패하므로 멈추고 오류를 올린다(사용자마다 실패를 쌓지 않는다).
    앞 사용자의 판정은 이미 확정돼 남는다."""
    async with world() as built:
        first, second = sorted([await built.user(), await built.user()])
        opportunity = await built.opportunity("새 장학", days=None)

        class Cut(OpportunityRepository):
            async def refresh_judgments(self, user_id: str, **kwargs: Any) -> Refresh:
                if user_id == second:  # 이 사용자를 판정하는 중에 연결이 끊긴다
                    await built.conn.execute(
                        "select pg_terminate_backend(%s)", (self.conn.info.backend_pid,)
                    )
                return await super().refresh_judgments(user_id, **kwargs)

        with pytest.raises(psycopg.OperationalError):
            await _morning(built, Cut)
        assert "판정을 다시 계산하지 못했어요" not in caplog.text
        assert await built.status(first, opportunity) == "eligible"


async def test_a_student_who_has_not_agreed_yet_is_not_judged() -> None:
    """약관·개인정보 동의 전에는 판정하지 않는다. 프로필을 저장할 수 없고 앱을 쓰기 전이다."""
    async with world() as built:
        waiting = await built.user(consented=False)
        opportunity = await built.opportunity("새 장학", days=None)

        await _morning(built)
        assert await built.status(waiting, opportunity) is None
        assert await built.keys(waiting) == []


async def test_a_student_who_left_during_the_job_is_not_brought_back() -> None:
    """목록을 읽은 뒤 탈퇴한 학생(프로필은 지워 확정했고 로그인 계정은 아직 남음, app/account.py 3·4)의
    프로필을 판정하며 다시 만들지 않는다."""
    async with world() as built:
        leaving = await built.user()
        await built.opportunity("새 장학", days=None)

        class Leaving(OpportunityRepository):
            async def refresh_judgments(self, user_id: str, **kwargs: Any) -> Refresh:
                if user_id == leaving:
                    await built.conn.execute("delete from profiles where id = %s", (user_id,))
                return await super().refresh_judgments(user_id, **kwargs)

        await _morning(built, Leaving)
        row = await (
            await built.conn.execute(
                "select count(*) as count from profiles where id = %s", (leaving,)
            )
        ).fetchone()
        assert row is not None and row["count"] == 0


async def test_a_student_who_turned_off_every_opportunity_alert_is_not_judged() -> None:
    """공고 알림 세 종류를 모두 끈 학생은 받을 알림이 없으니 판정하지 않는다. 하나라도 켜 두면 한다."""
    async with world() as built:
        quiet = await built.user(
            muted_notification_types=["new_eligible", "deadline_soon", "profile_needed"]
        )
        partly = await built.user(muted_notification_types=["new_eligible"])
        opportunity = await built.opportunity("새 장학", days=None)

        await _morning(built)
        assert await built.status(quiet, opportunity) is None
        assert await built.status(partly, opportunity) == "eligible"
        assert await built.keys(partly) == []  # 새 공고 알림은 껐고, 마감이 없어 마감 임박도 없다


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
        ids = [item.id for item in due]
        assert await built.repo.mark_sent(ids, now=sent_at) == ids  # 넘긴 순서대로

        again = await built.repo.mark_sent(ids, now=sent_at + timedelta(days=1))
        assert again == []  # 이미 닫힌 알림은 푸시 대상에서도 빠진다
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
    """ERD: profile_needed 하루 1건 제한은 발송 배치가 건다. 넘는 알림은 다음 날 알림 시각(09:00)으로
    미룬다 — 알림함에도 그때 나오고(PRD F-33: 하루 1건), 다음 날 0시에 푸시가 나가지 않는다."""
    async with world() as built:
        student = await built.user()
        for index, field in enumerate(ASKED):  # 묻는 항목이 셋이라 알림도 셋(항목 단위로 묶는다)
            opportunity = await built.opportunity(f"정보 필요 {index}", days=10)
            await built.judge(student, opportunity, "undetermined", [field])
            await built.view(student, opportunity)
        await built.repo.schedule(now=NOW)

        first = (await built.repo.send(now=NOW + timedelta(days=1))).result
        assert (first.due, first.sent, first.skipped) == (3, PROFILE_DAILY, 3 - PROFILE_DAILY)
        later = (await built.repo.send(now=NOW + timedelta(days=1, hours=1))).result
        assert (later.due, later.sent) == (0, 0)  # 미뤘으니 같은 날에는 다시 보지 않는다
        assert await built.repo.unread(student, now=NOW + timedelta(days=1, hours=1)) == 1
        early = (await built.repo.send(now=NOW + timedelta(days=2))).result
        assert early.sent == 0  # 다음 날도 알림 시각 전(08:00)에는 보내지 않는다
        tomorrow = (await built.repo.send(now=NOW + timedelta(days=2, hours=2))).result
        assert tomorrow.sent == PROFILE_DAILY
        assert sorted(await built.bodies(student)) == [
            "정보 필요 0 · 거주지역을 입력하면 판정할 수 있어요",
            "정보 필요 1 · 나이를 입력하면 판정할 수 있어요",
            "정보 필요 2 · 학적 상태를 입력하면 판정할 수 있어요",
        ]


async def test_profile_notices_over_the_limit_do_not_hold_up_other_notices() -> None:
    """한도에 걸린 정보 필요 알림이 발송 묶음을 채워도 다른 알림은 나간다. 정보 필요 알림은 맨 뒤에 보고,
    한도를 넘은 행은 다음 날로 미뤄 묶음에 다시 들어오지 않는다. 전에는 그런 행이 묶음(500건)보다 많으면
    마감 임박·새 과제 알림이 계속 나가지 못했다 — 여기서는 묶음을 2건으로 줄여 본다."""
    async with world() as built:
        asking, waiting = await built.user(), await built.user()
        for index, field in enumerate(ASKED):
            opportunity = await built.opportunity(f"정보 필요 {index}", days=10)
            await built.judge(asking, opportunity, "undetermined", [field])
        await built.repo.schedule(now=NOW)  # 10-15 09:00에 정보 필요 3건
        fresh = await built.opportunity("새 장학", days=None)  # 마감이 없어 마감 임박 알림은 없다
        await built.judge(waiting, fresh, "eligible")
        await built.repo.schedule(now=NOW + timedelta(hours=4))  # 10-16 09:00에 새 공고 1건
        sent_at = NOW + timedelta(days=1, hours=4)  # 10-16 12:00

        await built.repo.send(now=sent_at, limit=2)
        assert await built.keys(waiting) == ["new_eligible|새 장학|10-16 09:00|succeeded"]
        second = (await built.repo.send(now=sent_at, limit=2)).result
        assert (second.due, second.sent, second.skipped) == (2, 0, 2)  # 한도에 걸려 미룬다
        assert (await built.repo.send(now=sent_at, limit=2)).result.due == 0
        later = [line for line in await built.keys(asking) if line.endswith("10-17 09:00|pending")]
        assert len(later) == 2


async def test_a_late_send_does_not_move_a_notice_that_was_just_sent() -> None:
    """겹친 발송: 늦은 쪽이 보낼 목록을 읽은 뒤 먼저 쪽이 그 알림을 보내고 확정하면, 늦은 쪽에는 한도를
    넘은 정보 필요 알림으로 보인다. 그래도 이미 보낸 알림은 다음 날로 옮기지 않는다(알림함에서 사라진다)."""
    async with world() as built:
        student = await built.user()
        opportunity = await built.opportunity("정보 필요", days=10)
        await built.judge(student, opportunity, "undetermined", ["region"])
        await built.repo.schedule(now=NOW)
        early, late = await _tx_conn(), await _tx_conn()

        class Late(NotificationRepository):
            async def sent_today(self, *, now: datetime, kind: str) -> dict[str, int]:
                # 늦은 쪽이 보낼 목록을 읽은 뒤, 먼저 쪽이 그 알림을 보내고 확정했다
                await NotificationRepository(early).send(now=now)
                await early.commit()
                return await super().sent_today(now=now, kind=kind)

        try:
            result = (await Late(late).send(now=NOW + timedelta(days=1))).result
            await late.commit()
        finally:
            await early.close()
            await late.close()
        # 남이 닫은 알림은 sent·skipped 어디에도 세지 않는다(명세 12장)
        assert (result.due, result.sent, result.skipped) == (1, 0, 0)
        assert await built.keys(student) == ["profile_needed|정보 필요|10-15 09:00|succeeded"]


async def test_a_deferred_profile_notice_goes_out_before_newer_ones() -> None:
    """미룬 정보 필요 알림은 다음 날 09:00에 새로 생긴 것과 시각이 같아진다. 그래도 먼저 만든 것부터
    보낸다 — 번호(id) 순이면 날마다 새 알림에 밀려 마감까지 못 나갈 수 있다."""
    async with world() as built:
        student = await built.user()
        older = await built.opportunity("먼저 생긴 공고", days=10)
        newer = await built.opportunity("나중 생긴 공고", days=10)
        low, high = sorted([uuid.uuid4(), uuid.uuid4()])  # 먼저 만든 알림의 번호가 더 크다
        at = NOW + timedelta(days=1, hours=1)  # 10-16 09:00
        for notification, opportunity, created in (
            (high, older, NOW - timedelta(days=1)),  # 어제 한도에 걸려 미뤄진 알림
            (low, newer, NOW + timedelta(days=1)),  # 오늘 아침 새로 만든 알림
        ):
            await built.conn.execute(
                "insert into notifications (id, user_id, type, opportunity_id, title, body,"
                " scheduled_at, dedupe_key, created_at) values (%s, %s, 'profile_needed', %s,"
                " '프로필 정보가 필요해요', '본문', %s, 'profile_needed:opp:' || %s, %s)",
                (notification, student, opportunity, at, opportunity, created),
            )

        await built.repo.send(now=at + timedelta(hours=1))
        assert await built.keys(student) == [
            "profile_needed|먼저 생긴 공고|10-16 09:00|succeeded",
            "profile_needed|나중 생긴 공고|10-17 09:00|pending",
        ]


# ── 정보 필요 알림은 항목 단위로 (11/19) ─────────────────────────────────────


async def test_profile_notices_are_grouped_by_the_field_they_ask_for() -> None:
    """같은 항목을 묻는 공고가 여럿이면 알림은 하나다. 대표는 마감이 가장 가까운 공고이고, 문구에 남은 수를 적는다."""
    async with world() as built:
        student = await built.user()
        for title, days in (("거주 10일", 10), ("거주 5일", 5), ("거주 마감 없음", None)):
            opportunity = await built.opportunity(title, days=days)
            await built.judge(student, opportunity, "undetermined", ["region", "age"])
        alone = await built.opportunity("나이 하나", days=20)
        await built.judge(student, alone, "undetermined", ["age"])

        result = await built.repo.schedule(now=NOW)

        assert result.by_type["profile_needed"] == 2  # 공고는 넷, 묻는 첫 항목은 둘
        assert [line for line in await built.keys(student) if "profile_needed" in line] == [
            "profile_needed|나이 하나|10-15 09:00|pending",
            "profile_needed|거주 5일|10-15 09:00|pending",
        ]
        assert sorted(await built.bodies(student)) == [
            "거주 5일 외 2개 · 거주지역을 입력하면 판정할 수 있어요",
            "나이 하나 · 나이를 입력하면 판정할 수 있어요",
        ]
        keys = await built.conn.execute(
            "select dedupe_key from notifications where user_id = %s order by 1", (student,)
        )
        assert [row["dedupe_key"] for row in await keys.fetchall()] == [
            "profile_needed:field:age",
            "profile_needed:field:region",
        ]


async def test_a_grouped_notice_follows_the_count_and_leaves_when_answered() -> None:
    """공고 수가 바뀌면 아직 보내지 않은 행의 대표·문구를 고치고, 그 항목을 넣어 묶인 공고가 모두 판정되면 지운다."""
    async with world() as built:
        student = await built.user()
        near = await built.opportunity("가까운 마감", days=3)
        far = await built.opportunity("먼 마감", days=10)
        for opportunity in (near, far):
            await built.judge(student, opportunity, "undetermined", ["region"])
        await built.repo.schedule(now=NOW)
        assert await built.bodies(student) == [
            "가까운 마감 외 1개 · 거주지역을 입력하면 판정할 수 있어요"
        ]

        await built.mark(student, near, "not_interested")  # 대표를 숨겼다 → 다음 공고가 대표
        moved = await built.repo.schedule(now=NOW)
        assert (moved.created, moved.rescheduled, moved.removed) == (0, 1, 0)
        assert await built.keys(student) == ["profile_needed|먼 마감|10-15 09:00|pending"]
        assert await built.bodies(student) == ["먼 마감 · 거주지역을 입력하면 판정할 수 있어요"]
        assert (await built.repo.schedule(now=NOW)).rescheduled == 0  # 바뀐 것이 없으면 그대로

        await built.judge(student, far, "eligible")  # 거주지역을 넣어 판정됐다
        answered = await built.repo.schedule(now=NOW)
        assert answered.removed == 1
        assert [line for line in await built.keys(student) if "profile_needed" in line] == []


async def test_answering_one_field_moves_the_question_to_the_next_one() -> None:
    """거주지역을 넣었는데 그 공고가 이제 나이를 물으면, 거주지역 알림은 지우고 나이 알림을 새로 만든다."""
    async with world() as built:
        student = await built.user()
        opportunity = await built.opportunity("두 항목 장학", days=10)
        await built.judge(student, opportunity, "undetermined", ["region", "age"])
        await built.repo.schedule(now=NOW)

        await built.judge(student, opportunity, "undetermined", ["age"])  # 거주지역을 넣었다
        moved = await built.repo.schedule(now=NOW)

        assert (moved.created, moved.removed) == (1, 1)
        assert await built.bodies(student) == ["두 항목 장학 · 나이를 입력하면 판정할 수 있어요"]


async def test_a_field_is_asked_once_even_when_new_opportunities_need_it() -> None:
    """보낸 항목은 다시 묻지 않는다(항목당 1회) — 같은 항목을 묻는 공고가 새로 들어와도 알림을 만들지 않는다."""
    async with world() as built:
        student = await built.user()
        first = await built.opportunity("첫 공고", days=10)
        await built.judge(student, first, "undetermined", ["region"])
        await built.repo.schedule(now=NOW)
        await built.repo.send(now=NOW + timedelta(hours=2))
        later = await built.opportunity("나중 공고", days=10)
        await built.judge(student, later, "undetermined", ["region"])

        again = await built.repo.schedule(now=NOW + timedelta(days=1))

        assert (again.created, again.rescheduled) == (0, 0)
        assert await built.keys(student) == ["profile_needed|첫 공고|10-15 09:00|succeeded"]


async def test_old_per_opportunity_profile_notices_are_cleared() -> None:
    """공고마다 한 행이던 옛 키(profile_needed:opp:…)의 pending 행은 다음 예약이 지운다. 보낸 행은 알림함에 남는다."""
    async with world() as built:
        student = await built.user()
        opportunities = [await built.opportunity(f"옛 알림 {index}", days=10) for index in range(3)]
        for index, opportunity in enumerate(opportunities):
            await built.judge(student, opportunity, "undetermined", ["region"])
            await built.conn.execute(
                "insert into notifications (user_id, type, opportunity_id, title, body,"
                " scheduled_at, dedupe_key, status, sent_at) values (%s, 'profile_needed', %s,"
                " '프로필 정보가 필요해요', '옛 문구', %s, 'profile_needed:opp:' || %s, %s, %s)",
                (
                    student,
                    opportunity,
                    NOW - timedelta(days=1),
                    opportunity,
                    "succeeded" if index == 0 else "pending",
                    NOW - timedelta(days=1) if index == 0 else None,
                ),
            )

        result = await built.repo.schedule(now=NOW)

        assert (result.created, result.removed) == (1, 2)
        lines = await built.keys(student)
        assert "profile_needed|옛 알림 0|10-14 08:00|succeeded" in lines  # 보낸 것은 그대로
        assert sum("pending" in line for line in lines) == 1  # 항목 단위 새 행 하나


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
