"""출석 마감 하루 전 알림(lecture_due, F-55 뒤, 11/27)을 실제 스키마에 대고 확인한다: 만들기·문구 고치기·지우기,
끈 종류, 연결 끊기, 알림함 링크(과목의 강의 탭)와 푸시 주소.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from app.eligibility import KST
from app.repositories.lms import LmsRepository
from app.repositories.notifications import (
    LECTURE_TITLE,
    LectureNotice,
    NotificationRepository,
)
from app.repositories.push import PushRepository
from tests.db_world import DATABASE_URL, connect, make_user
from tests.lms_samples import DATABASE, MACHINE_LEARNING

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=KST)
DUE = date(2026, 12, 4)  # 알림은 12-03 09:00


@pytest.fixture
async def world() -> Any:
    """LearningX를 연결하고 두 과목을 듣는 학생. 트랜잭션은 끝에 되돌린다."""
    conn = await connect()
    try:
        lms = LmsRepository(conn)
        me = await make_user(conn)
        await lms.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1)
        await lms.save_courses(me, [DATABASE, MACHINE_LEARNING], now=NOW)
        rows = await (
            await conn.execute(
                "select id::text as id, canvas_course_id from lms_courses where user_id = %s",
                (me,),
            )
        ).fetchall()
        courses = {row["canvas_course_id"]: row["id"] for row in rows}
        yield {
            "conn": conn,
            "lms": lms,
            "notes": NotificationRepository(conn),
            "me": me,
            "db": courses[DATABASE["id"]],
            "ml": courses[MACHINE_LEARNING["id"]],
        }
    finally:
        await conn.rollback()
        await conn.close()


async def _rows(world: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await (
        await world["conn"].execute(
            "select dedupe_key, lms_course_id::text as course, title, body, status,"
            " to_char(scheduled_at at time zone 'Asia/Seoul', 'MM-DD HH24:MI') as at"
            " from notifications where user_id = %s and type = 'lecture_due' order by dedupe_key",
            (world["me"],),
        )
    ).fetchall()
    return [dict(row) for row in rows]


def _notice(
    course: str, body: str = "데이터베이스 · 6주차 강의 1부를 아직 안 들었어요", day: date = DUE
):
    return LectureNotice(course_id=course, day=day, body=body)


async def test_a_lecture_left_unwatched_is_announced_the_morning_before_its_deadline(
    world: dict[str, Any],
) -> None:
    kept = await world["notes"].set_lecture_notices(
        world["me"], [world["db"]], [_notice(world["db"])], now=NOW
    )

    assert kept == 1
    assert await _rows(world) == [
        {
            "dedupe_key": f"lecture_due:{world['db']}:2026-12-04",
            "course": world["db"],
            "title": LECTURE_TITLE,
            "body": "데이터베이스 · 6주차 강의 1부를 아직 안 들었어요",
            "status": "pending",
            "at": "12-03 09:00",
        }
    ]


async def test_reading_again_fixes_the_text_and_never_doubles_the_row(
    world: dict[str, Any],
) -> None:
    notes, me, db = world["notes"], world["me"], world["db"]
    await notes.set_lecture_notices(me, [db], [_notice(db)], now=NOW)
    await notes.set_lecture_notices(
        me, [db], [_notice(db, "데이터베이스 · 6주차 강의 1부 외 1개를 아직 안 들었어요")], now=NOW
    )

    rows = await _rows(world)
    assert len(rows) == 1
    assert rows[0]["body"] == "데이터베이스 · 6주차 강의 1부 외 1개를 아직 안 들었어요"


async def test_watching_or_a_moved_deadline_removes_the_pending_notice(
    world: dict[str, Any],
) -> None:
    notes, me, db = world["notes"], world["me"], world["db"]
    await notes.set_lecture_notices(me, [db], [_notice(db)], now=NOW)

    # 마감이 하루 밀렸다: 옛 날짜의 알림은 지우고 새 날짜로
    await notes.set_lecture_notices(me, [db], [_notice(db, day=DUE + timedelta(days=1))], now=NOW)
    assert [row["at"] for row in await _rows(world)] == ["12-04 09:00"]

    # 다 들었다
    assert await notes.set_lecture_notices(me, [db], [], now=NOW) == 0
    assert await _rows(world) == []


async def test_a_notice_whose_morning_has_passed_is_not_made(world: dict[str, Any]) -> None:
    notes, me, db = world["notes"], world["me"], world["db"]
    late = datetime(2026, 12, 3, 9, 30, tzinfo=KST)  # 알림 시각(12-03 09:00)이 지났다

    assert await notes.set_lecture_notices(me, [db], [_notice(db)], now=late) == 0
    assert await _rows(world) == []


async def test_only_the_courses_just_read_are_touched(world: dict[str, Any]) -> None:
    """못 읽은 과목의 알림은 그대로 둔다 — 이번에 읽은 과목만 맞춘다."""
    notes, me, db, ml = world["notes"], world["me"], world["db"], world["ml"]
    await notes.set_lecture_notices(
        me,
        [db, ml],
        [_notice(db), _notice(ml, "기계학습 · 3주차 강의를 아직 안 들었어요")],
        now=NOW,
    )

    await notes.set_lecture_notices(me, [db], [], now=NOW)  # 데이터베이스만 읽었다(다 들음)

    assert [row["course"] for row in await _rows(world)] == [ml]


async def test_a_sent_notice_stays_in_the_inbox(world: dict[str, Any]) -> None:
    notes, me, db = world["notes"], world["me"], world["db"]
    await notes.set_lecture_notices(me, [db], [_notice(db)], now=NOW)
    sent = await notes.send(now=datetime(2026, 12, 3, 9, 5, tzinfo=KST))
    assert sent.result.sent == 1

    await notes.set_lecture_notices(me, [db], [], now=NOW)  # 그 뒤에 다 들었다

    assert [row["status"] for row in await _rows(world)] == ["succeeded"]


async def test_a_muted_kind_makes_nothing_and_clears_what_was_pending(
    world: dict[str, Any],
) -> None:
    notes, me, db, conn = world["notes"], world["me"], world["db"], world["conn"]
    await notes.set_lecture_notices(me, [db], [_notice(db)], now=NOW)
    await conn.execute(
        "insert into user_settings (user_id, muted_notification_types) values (%s, %s)",
        (me, ["lecture_due"]),
    )

    assert await notes.set_lecture_notices(me, [db], [_notice(db)], now=NOW) == 0
    assert await _rows(world) == []


@pytest.mark.parametrize("stop", ["disconnect", "blocked_token"])
async def test_a_stopped_sync_drops_the_pending_lecture_notices(
    world: dict[str, Any], stop: str
) -> None:
    """연결을 끊거나 토큰이 막히면 동기화가 멈춰 다 들었는지 다시 볼 수 없다 — 보내지 않은 출석 마감 알림을 지운다."""
    notes, me, db, conn = world["notes"], world["me"], world["db"], world["conn"]
    await notes.set_lecture_notices(me, [db], [_notice(db)], now=NOW)
    await conn.execute(
        "insert into notifications (user_id, type, title, scheduled_at, dedupe_key)"
        " values (%s, 'new_assignment', '새 과제', %s, 'new_assignment:asg:x')",
        (me, NOW),
    )

    if stop == "disconnect":
        assert await world["lms"].delete_connection(me) is True
    else:
        await world["lms"].mark_error(me, "토큰이 만료되었거나 삭제되었어요.")

    assert await _rows(world) == []
    left = await (
        await conn.execute("select type from notifications where user_id = %s", (me,))
    ).fetchall()
    assert [row["type"] for row in left] == ["new_assignment"]  # 다른 알림은 그대로


async def test_the_inbox_and_the_push_open_the_lecture_tab(world: dict[str, Any]) -> None:
    notes, me, db, conn = world["notes"], world["me"], world["db"], world["conn"]
    await notes.set_lecture_notices(me, [db], [_notice(db)], now=NOW)
    morning = datetime(2026, 12, 3, 9, 5, tzinfo=KST)

    listing = await notes.listing(me, now=morning)
    link = listing.items[0].link
    assert listing.items[0].type == "lecture_due"
    assert link is not None and (link.type, link.id, link.course_id) == ("lms_course", db, db)

    sent = await notes.send(now=morning)
    await conn.execute(
        "insert into push_subscriptions (user_id, endpoint, p256dh, auth) values (%s, %s, 'p', 'a')",
        (me, f"https://push.example/{me}"),
    )
    targets = await PushRepository(conn).targets(sent.ids)
    assert [target.payload.url for target in targets] == [f"/academics/{db}?tab=lectures"]
