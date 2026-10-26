"""웹 푸시 구독 SQL과 발송 대상 (F-33). DATABASE_URL이 있을 때만 돈다.

구독 주소(endpoint)가 유일 키라서 "같은 브라우저를 다른 사람이 쓰면 주인이 바뀐다". 그 규칙과
발송 대상 고르기(푸시를 끈 사람·구독 없는 사람 빼기)를 실제 스키마에 대고 본다.
"""

import asyncio
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest
import respx
from psycopg.rows import dict_row

from app.push.keys import b64u, generate_keys, load_keys
from app.push.send import PushResult, PushSender, PushTarget
from app.repositories.notifications import NotificationRepository
from app.repositories.push import PushRepository
from app.routers.internal import send_notifications
from tests.db_world import DATABASE_URL
from tests.test_notifications_db import NOW, world

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

ENDPOINT = "https://push.example.com/fcm/send/one"
# 시험용 Canvas 번호(녹화·시나리오가 쓰는 번호대와 겹치지 않게 둔다)
TEST_COURSE_ID = 888_023
TEST_TOPIC_ID = 888_964
OTHER_ENDPOINT = "https://push.example.com/fcm/send/two"


def _keys() -> tuple[str, str]:
    _, public = generate_keys()
    return public, b64u(b"0123456789abcdef")


async def _save(repo: PushRepository, user_id: str, endpoint: str = ENDPOINT) -> bool:
    p256dh, auth = _keys()
    return await repo.save(
        user_id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent="Chrome 129"
    )


async def test_the_same_browser_subscribing_twice_is_one_row() -> None:
    async with world() as built:
        repo, student = PushRepository(built.conn), await built.user()

        first = await _save(repo, student)
        again = await _save(repo, student)

        assert (first, again) == (True, False)  # 두 번째는 키만 갱신한다
        assert await repo.count(student) == 1


async def test_another_user_on_the_same_browser_takes_the_subscription_over() -> None:
    """한 브라우저를 두 사람이 번갈아 쓰는 경우다. 푸시는 지금 로그인한 사람에게 가야 한다."""
    async with world() as built:
        repo = PushRepository(built.conn)
        first_user, second_user = await built.user(), await built.user()
        await _save(repo, first_user)

        await _save(repo, second_user)

        assert await repo.count(first_user) == 0
        assert await repo.count(second_user) == 1


async def test_i_can_only_remove_my_own_subscription() -> None:
    async with world() as built:
        repo = PushRepository(built.conn)
        mine, theirs = await built.user(), await built.user()
        await _save(repo, mine)

        assert await repo.remove(theirs, ENDPOINT) == 0  # 남의 주소는 지워지지 않는다
        assert await repo.remove(mine, ENDPOINT) == 1
        assert await repo.count(mine) == 0


async def test_gone_subscriptions_are_dropped_whoever_owns_them() -> None:
    """푸시 서비스가 404·410을 주면 그 구독은 끝난 것이다(사용자를 가리지 않는다)."""
    async with world() as built:
        repo = PushRepository(built.conn)
        student, other = await built.user(), await built.user()
        await _save(repo, student, ENDPOINT)
        await _save(repo, other, OTHER_ENDPOINT)

        dropped = await repo.drop_endpoints([ENDPOINT, OTHER_ENDPOINT, "https://push/none"])

        assert dropped == 2
        assert (await repo.count(student), await repo.count(other)) == (0, 0)
        assert await repo.drop_endpoints([]) == 0


async def _notification(built: Any, user_id: str, **columns: Any) -> str:
    values = {
        "user_id": user_id,
        "type": "new_eligible",
        "title": "지원할 수 있는 공고가 있어요",
        "body": "발송 장학",
        "scheduled_at": NOW,
        "dedupe_key": f"new_eligible:test:{user_id}:{len(columns)}",
        **columns,
    }
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    row = await (
        await built.conn.execute(
            f"insert into notifications ({names}) values ({marks}) returning id::text as id",
            tuple(values.values()),
        )
    ).fetchone()
    return str(row["id"])


async def test_a_notification_with_two_browsers_is_one_target() -> None:
    async with world() as built:
        repo, student = PushRepository(built.conn), await built.user()
        opportunity = await built.opportunity("발송 장학", days=10)
        await _save(repo, student, ENDPOINT)
        await _save(repo, student, OTHER_ENDPOINT)
        notification = await _notification(built, student, opportunity_id=opportunity)

        targets = await repo.targets([notification])

        assert len(targets) == 1
        target = targets[0]
        assert {one.endpoint for one in target.subscriptions} == {ENDPOINT, OTHER_ENDPOINT}
        assert target.payload.notification_id == notification
        assert target.payload.type == "new_eligible"
        # 누르면 갈 주소는 공고 상세다(명세 10장)
        assert target.payload.url == f"/opportunities/{opportunity}"


async def test_a_user_who_turned_push_off_is_not_a_target() -> None:
    async with world() as built:
        repo = PushRepository(built.conn)
        quiet = await built.user(push_enabled=False)
        loud = await built.user()
        await _save(repo, quiet, ENDPOINT)
        await _save(repo, loud, OTHER_ENDPOINT)
        quiet_notice = await _notification(built, quiet)
        loud_notice = await _notification(built, loud)

        targets = await repo.targets([quiet_notice, loud_notice])

        assert [one.payload.notification_id for one in targets] == [loud_notice]


async def test_a_user_without_a_subscription_is_not_a_target() -> None:
    async with world() as built:
        repo, student = PushRepository(built.conn), await built.user()
        notification = await _notification(built, student)

        assert await repo.targets([notification]) == []
        assert await repo.targets([]) == []


async def test_an_lms_notification_points_at_the_course_tab() -> None:
    """공지·자료 알림은 과목 탭으로 간다. 과목 번호는 내 과목 행에서 찾는다(명세 10장)."""
    async with world() as built:
        repo, student = PushRepository(built.conn), await built.user()
        await _save(repo, student)
        course = await (
            await built.conn.execute(
                "insert into lms_courses (user_id, canvas_course_id, name)"
                " values (%s, %s, '202620HY23525_데이터베이스') returning id::text as id",
                (student, TEST_COURSE_ID),
            )
        ).fetchone()
        # 공지는 과목 공통 표라 사용자를 지워도 남는다(ERD 3-2). 이 시험용 번호를 먼저 치운다
        await built.conn.execute(
            "delete from lms_announcements where canvas_topic_id = %s", (TEST_TOPIC_ID,)
        )
        announcement = await (
            await built.conn.execute(
                "insert into lms_announcements (canvas_course_id, canvas_topic_id, title)"
                " values (%s, %s, '휴강 안내') returning id::text as id",
                (TEST_COURSE_ID, TEST_TOPIC_ID),
            )
        ).fetchone()
        notification = await _notification(
            built,
            student,
            type="schedule_change",
            lms_announcement_id=announcement["id"],
            title="데이터베이스 수업 일정이 바뀌었어요",
        )

        try:
            targets = await repo.targets([notification])
            assert targets[0].payload.url == f"/academics/{course['id']}?tab=announcements"
        finally:
            # 공지는 과목 공통 표라 사용자를 지워도 남는다. 다음 시험에 남기지 않는다
            await built.conn.execute(
                "delete from lms_announcements where canvas_topic_id = %s", (TEST_TOPIC_ID,)
            )


# ── 발송 작업 전체 (F-33) ───────────────────────────────────────────────────


async def _job(built: Any, sender: Any, now: Any) -> Any:
    """`POST /internal/jobs/send-notifications`의 몸통을 그대로 부른다(키 검사만 건너뛴다)."""
    return await send_notifications(
        repo=NotificationRepository(built.conn),
        push_repo=PushRepository(built.conn),
        sender=sender,
        now=now,
        _=None,
    )


async def test_the_job_sends_a_push_for_every_notification_it_closes() -> None:
    async with world() as built:
        repo, student = PushRepository(built.conn), await built.user()
        opportunity = await built.opportunity("발송 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        await _save(repo, student, ENDPOINT)
        await built.repo.schedule(now=NOW)
        private, _public = generate_keys()
        sender = PushSender(load_keys(private_key=private, subject="mailto:a@b.c"))

        with respx.mock(assert_all_called=False) as router:
            route = router.post(url__startswith="https://push.example.com").mock(
                return_value=httpx.Response(201)
            )
            result = await _job(built, sender, NOW + timedelta(days=1))

        assert (result.sent, result.pushable, result.pushed) == (1, 1, 1)
        assert (result.push_failed, result.push_dropped) == (0, 0)
        assert route.called
        # 보낸 본문은 암호화돼 있다(평문 제목이 보이면 안 된다)
        body = route.calls[0].request.content
        assert "발송 장학".encode() not in body
        assert b"notification_id" not in body


async def test_a_gone_subscription_is_deleted_by_the_job() -> None:
    async with world() as built:
        repo, student = PushRepository(built.conn), await built.user()
        opportunity = await built.opportunity("발송 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        await _save(repo, student, ENDPOINT)
        await built.repo.schedule(now=NOW)
        private, _public = generate_keys()
        sender = PushSender(load_keys(private_key=private, subject="mailto:a@b.c"))

        with respx.mock(assert_all_called=False) as router:
            router.post(url__startswith="https://push.example.com").mock(
                return_value=httpx.Response(410)
            )
            result = await _job(built, sender, NOW + timedelta(days=1))

        assert (result.sent, result.pushed, result.push_dropped) == (1, 0, 1)
        assert await repo.count(student) == 0  # 구독을 지웠다
        # 알림함 행은 남는다(F-35: 푸시를 못 받아도 알림함에는 쌓인다).
        # 마감 임박 알림은 아직 보낼 때가 아니라 pending이다
        lines = await built.keys(student)
        assert [line for line in lines if "new_eligible" in line] == [
            "new_eligible|발송 장학|10-15 09:00|succeeded"
        ]


async def test_without_vapid_keys_the_job_only_closes_the_rows() -> None:
    async with world() as built:
        repo, student = PushRepository(built.conn), await built.user()
        opportunity = await built.opportunity("발송 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        await _save(repo, student, ENDPOINT)
        await built.repo.schedule(now=NOW)

        with respx.mock(assert_all_called=False) as router:
            route = router.post(url__startswith="https://push.example.com").mock(
                return_value=httpx.Response(201)
            )
            result = await _job(built, PushSender(None), NOW + timedelta(days=1))

        assert (result.sent, result.pushable, result.pushed) == (1, 1, 0)
        assert not route.called  # 설정이 비면 푸시 서비스를 부르지 않는다
        assert await repo.count(student) == 1  # 구독은 그대로 둔다


# ── 두 발송이 겹칠 때 (배포 중 인스턴스 둘, 스케줄러와 수동 호출) ──────────────


async def _tx_conn() -> psycopg.AsyncConnection:
    """요청 풀처럼 autocommit이 아닌 연결(블록이 끝날 때 커밋·롤백한다)."""
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row, prepare_threshold=None
    )


async def _wait_until_blocked(watcher: psycopg.AsyncConnection, pid: int) -> None:
    """그 연결이 다른 트랜잭션의 행 잠금을 기다리기 시작할 때까지 본다(최대 10초)."""
    for _ in range(200):
        row = await (
            await watcher.execute(
                "select wait_event_type from pg_stat_activity where pid = %s", (pid,)
            )
        ).fetchone()
        if row and row["wait_event_type"] == "Lock":
            return
        await asyncio.sleep(0.05)
    raise AssertionError("두 번째 발송이 잠금을 기다리지 않았다")


async def test_of_two_overlapping_sends_only_the_one_that_closed_the_row_pushes_it() -> None:
    """두 발송이 같은 알림을 골라도 행을 닫은 쪽만 그 번호를 돌려준다(푸시 대상).

    늦은 쪽의 UPDATE는 먼저 쪽이 끝날 때까지 기다렸다가 `status = 'pending'`을 다시 보고 건너뛴다.
    """
    async with world() as built:
        student = await built.user()
        await _save(PushRepository(built.conn), student, ENDPOINT)
        opportunity = await built.opportunity("겹친 발송 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)
        sent_at = NOW + timedelta(days=1)

        first, second = await _tx_conn(), await _tx_conn()
        late: asyncio.Task[Any] | None = None
        try:
            one = await NotificationRepository(first).send(now=sent_at)  # 닫았지만 아직 확정 전
            late = asyncio.create_task(NotificationRepository(second).send(now=sent_at))
            await _wait_until_blocked(built.conn, second.info.backend_pid)
            await first.commit()
            two = await late
            await second.commit()

            assert (one.result.due, one.result.sent, one.result.pushable) == (1, 1, 1)
            assert len(one.ids) == 1
            assert (two.result.due, two.result.sent, two.result.pushable) == (1, 0, 0)
            assert two.ids == []  # 같은 푸시를 두 번 보내지 않는다
        finally:
            if late is not None and not late.done():
                late.cancel()
                await asyncio.gather(late, return_exceptions=True)
            await first.close()
            await second.close()


class _CheckingSender:
    """푸시를 보내는 순간 그 알림이 이미 확정(커밋)됐는지 다른 연결로 본다. 멈춤도 흉내 낸다."""

    def __init__(self, watcher: psycopg.AsyncConnection, *, stop: bool = False) -> None:
        self.watcher = watcher
        self.stop = stop
        self.seen: list[str] = []

    async def send(self, targets: Sequence[PushTarget]) -> PushResult:
        for target in targets:
            row = await (
                await self.watcher.execute(
                    "select status::text as status from notifications where id = %s",
                    (target.payload.notification_id,),
                )
            ).fetchone()
            assert row is not None
            self.seen.append(row["status"])
        if self.stop:  # 배포 중 옛 인스턴스가 꺼지며 작업이 취소된 것과 같다
            raise asyncio.CancelledError
        return PushResult(sent=len(targets))


async def test_the_job_commits_the_closed_rows_before_pushing() -> None:
    """푸시보다 행 확정이 먼저다. 그래서 푸시 도중 작업이 멈춰(롤백) 다음 발송이 같은 푸시를 또 보내지 않는다."""
    async with world() as built:
        student = await built.user()
        await _save(PushRepository(built.conn), student, ENDPOINT)
        opportunity = await built.opportunity("확정 먼저 장학", days=10)
        await built.judge(student, opportunity, "eligible")
        await built.repo.schedule(now=NOW)
        sent_at = NOW + timedelta(days=1)

        stopping = _CheckingSender(built.conn, stop=True)
        conn = await _tx_conn()
        try:
            with pytest.raises(asyncio.CancelledError):
                await send_notifications(
                    repo=NotificationRepository(conn),
                    push_repo=PushRepository(conn),
                    sender=stopping,  # type: ignore[arg-type]
                    now=sent_at,
                    _=None,
                )
            await conn.rollback()  # 풀 연결은 예외가 나면 블록을 나가며 롤백한다
        finally:
            await conn.close()
        assert stopping.seen == ["succeeded"]  # 푸시를 보낼 때 다른 연결에서도 이미 닫혀 보였다

        again = _CheckingSender(built.conn)
        result = await _job(built, again, sent_at + timedelta(minutes=5))
        assert (result.due, result.sent) == (0, 0)
        assert again.seen == []  # 다음 발송은 다시 보내지 않는다
