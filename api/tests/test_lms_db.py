"""LearningX 연결·과목·과제 SQL(F-50·F-51)을 실제 스키마에 대고 확인한다: 토큰 저장·교체·삭제,
과목 upsert와 수강 뺀 과목 내리기, 과목 목록의 숫자와 격리, 과제 저장과 플래너·알림 맞추기.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from app.eligibility import KST
from app.lms.assignments import CanvasAssignment, assignments
from app.repositories.lms import AssignmentChanges, LmsRepository, SavedAssignment
from app.repositories.notifications import AssignmentNotice, NotificationRepository
from app.repositories.runs import RunRepository
from app.schemas.lms import SAVE_TOOL
from tests.db_world import DATABASE_URL, connect, make_user
from tests.lms_samples import (
    DATABASE,
    DB_ASSIGNMENTS,
    MACHINE_LEARNING,
    MINE,
    SEMINAR,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def world() -> Any:
    """사용자 둘과 저장소. 트랜잭션은 끝에 되돌린다."""
    conn = await connect()
    try:
        now = (await (await conn.execute("select now() as now")).fetchone())["now"]
        yield {
            "repo": LmsRepository(conn),
            "conn": conn,
            "now": now,
            "me": await make_user(conn),
            "other": await make_user(conn),
        }
    finally:
        await conn.rollback()
        await conn.close()


async def test_it_saves_the_token_and_swaps_it_on_reconnect(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    assert await repo.connection(me) is None

    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=77001, now=now)
    first = await repo.connection(me)
    assert first is not None
    assert (first.status, first.token_last4, first.access_token) == ("active", "a9f2", "enc-1")
    assert first.canvas_user_id == 77001
    assert first.last_synced_at == now

    later = now + timedelta(minutes=5)
    await repo.save_connection(me, token="enc-2", last4="b8e1", canvas_user_id=77001, now=later)
    second = await repo.connection(me)
    assert second is not None
    assert (second.access_token, second.token_last4) == ("enc-2", "b8e1")
    rows = await (
        await world["conn"].execute(
            "select count(*) as n from lms_connections where user_id = %s", (me,)
        )
    ).fetchone()
    assert rows["n"] == 1  # 한 사용자당 한 줄이다


async def test_an_error_mark_is_cleared_when_the_token_is_replaced(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.mark_error(me, "토큰이 만료되었거나 삭제되었어요.")
    broken = await repo.connection(me)
    assert broken is not None and broken.status == "error"
    assert broken.view().status == "error" and broken.view().last_error is not None

    await repo.save_connection(me, token="enc-2", last4="b8e1", canvas_user_id=1, now=now)
    fixed = await repo.connection(me)
    assert fixed is not None and (fixed.status, fixed.last_error) == ("active", None)


async def test_the_connection_status_goes_out_as_the_db_has_it(world: dict[str, Any]) -> None:
    """DB enum은 active·error·disconnected 셋이다. GET /me도 그 값을 그대로 쓰므로 뭉개지 않는다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    for status in ("active", "error", "disconnected"):
        await conn.execute(
            "update lms_connections set status = %s where user_id = %s", (status, me)
        )
        found = await repo.connection(me)
        assert found is not None and found.view().status == status


async def test_the_connection_repr_does_not_show_the_token(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-secret-1", last4="a9f2", canvas_user_id=1, now=now)
    found = await repo.connection(me)
    assert found is not None and "enc-secret-1" not in repr(found)


async def test_disconnecting_removes_the_token_but_keeps_the_courses(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.save_courses(me, MINE, now=now)

    assert await repo.delete_connection(me) is True
    assert await repo.connection(me) is None
    assert await repo.delete_connection(me) is False  # 두 번째는 지울 것이 없다
    assert len(await repo.courses(me, now=now)) == len(MINE)  # 과목 기록은 남는다


async def test_it_parses_the_course_name_into_the_portal_columns(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    assert await repo.save_courses(me, MINE, now=now) == len(MINE)
    rows = await (
        await conn.execute(
            "select canvas_course_id, name, term, portal_year, portal_term, portal_course_no"
            " from lms_courses where user_id = %s order by name",
            (me,),
        )
    ).fetchall()
    by_id = {row["canvas_course_id"]: row for row in rows}
    database = by_id[DATABASE["id"]]
    assert (database["portal_year"], database["portal_term"]) == (2026, 20)
    assert (database["portal_course_no"], database["term"]) == ("23525", "2026-2")
    assert database["name"] == DATABASE["name"]  # 원래 이름을 그대로 둔다
    seminar = by_id[SEMINAR["id"]]
    # 꼴이 다른 과목: 번호는 비우고 학기는 LearningX가 준 이름을 쓴다
    assert (seminar["portal_year"], seminar["portal_course_no"]) == (None, None)
    assert seminar["term"] == "2026년 2학기"


async def test_a_course_i_stopped_taking_drops_out_of_the_list(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, MINE, now=now)
    assert {one.canvas_course_id for one in await repo.courses(me, now=now)} == {
        one["id"] for one in MINE
    }

    # 다음 동기화에 데이터베이스만 남았다 → 나머지는 목록에서 빠지지만 행은 남는다
    await repo.save_courses(me, [DATABASE], now=now)
    assert [one.canvas_course_id for one in await repo.courses(me, now=now)] == [DATABASE["id"]]
    rows = await (
        await conn.execute(
            "select canvas_course_id, is_active from lms_courses where user_id = %s", (me,)
        )
    ).fetchall()
    assert {row["canvas_course_id"]: row["is_active"] for row in rows} == {
        DATABASE["id"]: True,
        MACHINE_LEARNING["id"]: False,
        SEMINAR["id"]: False,
    }

    # 다시 들으면 되살아난다
    await repo.save_courses(me, MINE, now=now)
    assert len(await repo.courses(me, now=now)) == len(MINE)


async def test_the_course_list_counts_what_is_stored_now(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = (await repo.courses(me, now=now))[0]
    # 과제·주차 항목 동기화는 F-51·F-52다. 그때까지 0이고 다음 할 일도 없다
    assert (course.open_assignments, course.new_materials, course.next_due) == (0, 0, None)
    assert course.has_syllabus is False
    assert course.short_name == "데이터베이스"
    assert "suup=23525" in (course.portal_syllabus_url or "")

    # 미제출 과제 둘(하나는 마감 지남)과 제출한 과제 하나를 넣으면 숫자가 맞는다
    row = await (
        await conn.execute(
            "select id from lms_courses where user_id = %s and canvas_course_id = %s",
            (me, DATABASE["id"]),
        )
    ).fetchone()
    course_id = row["id"]
    for canvas_id, title, due, state in (
        (1, "실습 2주차", now + timedelta(days=3), "unsubmitted"),
        (2, "실습 1주차", now - timedelta(days=3), "unsubmitted"),
        (3, "실습 3주차", now + timedelta(days=1), "submitted"),
    ):
        await conn.execute(
            "insert into lms_assignments (user_id, lms_course_id, canvas_assignment_id, title,"
            " due_at, submission_state) values (%s, %s, %s, %s, %s, %s)",
            (me, course_id, canvas_id, title, due, state),
        )
    counted = (await repo.courses(me, now=now))[0]
    assert counted.open_assignments == 2  # 마감이 지난 미제출도 센다
    assert counted.next_due is not None
    assert counted.next_due.kind == "assignment"
    assert counted.next_due.title == "실습 2주차"  # 아직 안 지난 것 중 가장 가까운 것
    assert counted.next_due.due_at == (now + timedelta(days=3)).astimezone(KST)


async def test_new_module_items_count_from_when_i_last_opened_the_course(
    world: dict[str, Any],
) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    await conn.execute(
        "update lms_courses set last_viewed_at = %s where user_id = %s",
        (now - timedelta(days=1), me),
    )
    for canvas_item_id, seen in ((11, now - timedelta(days=2)), (12, now), (13, now)):
        await conn.execute(
            "insert into lms_module_items (canvas_course_id, canvas_item_id, module_name, title,"
            " item_type, first_seen_at) values (%s, %s, '8주차', '08 - 자료', 'ExternalTool', %s)",
            (DATABASE["id"], canvas_item_id, seen),
        )
    assert (await repo.courses(me, now=now))[0].new_materials == 2  # 본 뒤에 생긴 둘만


async def test_an_empty_course_list_does_not_take_my_courses_away(world: dict[str, Any]) -> None:
    """학기 사이·필터·끊긴 목록 때문에 빈 목록이 올 수 있다. 그때 전부 내리면 복구할 길이 없다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, MINE, now=now)
    assert await repo.save_courses(me, [], now=now) == 0
    assert len(await repo.courses(me, now=now)) == len(MINE)


async def test_the_next_thing_due_can_be_a_syllabus_item(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = (await repo.courses(me, now=now))[0]
    row = await (
        await conn.execute(
            "insert into syllabi (user_id, lms_course_id, course_name, semester)"
            " values (%s, %s, '데이터베이스', '2026-2') returning id",
            (me, course.id),
        )
    ).fetchone()
    for item_type, title, starts, confirmed in (
        ("midterm", "중간고사", now + timedelta(days=2), True),
        ("final", "기말고사", now + timedelta(days=40), True),
        ("presentation", "발표(미확정)", now + timedelta(days=1), False),
    ):
        await conn.execute(
            "insert into syllabus_items (syllabus_id, item_type, title, starts_at, is_confirmed)"
            " values (%s, %s, %s, %s, %s)",
            (row["id"], item_type, title, starts, confirmed),
        )
    with_syllabus = (await repo.courses(me, now=now))[0]
    assert with_syllabus.has_syllabus is True
    assert with_syllabus.next_due is not None
    # 확인하지 않은 일정(발표)은 빼고, 확정된 것 중 가장 가까운 것이다
    assert (with_syllabus.next_due.kind, with_syllabus.next_due.title) == (
        "syllabus_item",
        "중간고사",
    )

    # 과제가 더 가까우면 과제가 이긴다
    await conn.execute(
        "insert into lms_assignments (user_id, lms_course_id, canvas_assignment_id, title,"
        " due_at, submission_state) values (%s, %s, 9, '실습 7주차', %s, 'unsubmitted')",
        (me, course.id, now + timedelta(hours=5)),
    )
    nearest = (await repo.courses(me, now=now))[0].next_due
    assert nearest is not None and (nearest.kind, nearest.title) == ("assignment", "실습 7주차")


async def test_the_list_is_sorted_by_the_name_on_screen(world: dict[str, Any]) -> None:
    """DB가 어떤 순서로 주든 화면 이름 순으로 정렬해 내려준다(정렬 규칙은 환경마다 다르다)."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, MINE, now=now)
    assert [one.short_name for one in await repo.courses(me, now=now)] == [
        "기계학습",
        "대학원 세미나(비정규)",
        "데이터베이스",
    ]


async def test_a_module_item_counts_for_everyone_taking_that_course(world: dict[str, Any]) -> None:
    """주차 항목은 과목 공통이다(ERD 3-2). 같은 과목을 듣는 사람이 넣어도 내 새 자료로 센다."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_courses(other, [DATABASE], now=now)
    await conn.execute("update lms_courses set last_viewed_at = %s", (now - timedelta(days=1),))
    await conn.execute(
        "insert into lms_module_items (canvas_course_id, canvas_item_id, module_name, title,"
        " item_type, first_seen_at) values (%s, 21, '9주차', '09 - 자료', 'ExternalTool', %s)",
        (DATABASE["id"], now),
    )
    assert (await repo.courses(me, now=now))[0].new_materials == 1
    assert (await repo.courses(other, now=now))[0].new_materials == 1


async def test_my_courses_and_connection_are_not_someone_elses(world: dict[str, Any]) -> None:
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.save_courses(me, MINE, now=now)

    assert await repo.connection(other) is None
    assert await repo.courses(other, now=now) == []
    assert await repo.delete_connection(other) is False
    # 남의 동기화가 내 과목을 내리지 않는다
    await repo.save_courses(other, [DATABASE], now=now)
    assert len(await repo.courses(me, now=now)) == len(MINE)


# ── 과제 저장 (F-51) ────────────────────────────────────────────────────────


def _one(
    canvas_id: int = 11,
    *,
    title: str = "실습 2주차 결과 제출",
    due: Any = None,
    state: str = "unsubmitted",
    submitted_at: Any = None,
) -> CanvasAssignment:
    return CanvasAssignment(
        canvas_assignment_id=canvas_id,
        title=title,
        due_at=due,
        html_url=f"https://lms.test/courses/214023/assignments/{canvas_id}",
        submission_state=state,
        submitted_at=submitted_at,
    )


async def _course_id(world: dict[str, Any], canvas_course_id: int = DATABASE["id"]) -> str:
    row = await (
        await world["conn"].execute(
            "select id from lms_courses where user_id = %s and canvas_course_id = %s",
            (world["me"], canvas_course_id),
        )
    ).fetchone()
    return str(row["id"])


async def test_it_saves_the_assignments_of_a_course(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)

    changes = await repo.save_assignments(me, course, assignments(DB_ASSIGNMENTS), now=now)
    assert [one.title for one in changes.created] == [
        "실습 2주차 결과 제출",
        "실습 3주차 결과 제출",
    ]
    assert (changes.due_changed, changes.submitted, changes.removed) == ([], [], 0)

    items = await repo.assignments(me, state="all")
    assert [(one.title, one.submission_state) for one in items] == [
        ("실습 3주차 결과 제출", "submitted"),  # 마감이 더 이르다(lock_at 10/18)
        ("실습 2주차 결과 제출", "unsubmitted"),
    ]
    assert items[0].course.short_name == "데이터베이스"
    # 마감은 샘플 그대로 저장되고 KST로 나간다(실습 3주차는 lock_at, 2주차는 due_at)
    assert [one.due_at.isoformat() for one in items] == [
        "2026-10-18T23:59:59+09:00",
        "2026-10-20T23:59:59+09:00",
    ]
    assert items[1].html_url == "https://lms.test/courses/214023/assignments/2811242"


async def test_saving_again_changes_nothing_new(world: dict[str, Any]) -> None:
    """같은 목록을 다시 받으면 새 과제도, 마감 변경도, 제출도 없다(알림이 두 번 가지 않는다)."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    items = [_one(due=now + timedelta(days=3))]
    await repo.save_assignments(me, course, items, now=now)

    again = await repo.save_assignments(me, course, items, now=now + timedelta(minutes=30))
    assert (again.created, again.due_changed, again.submitted, again.removed) == ([], [], [], 0)


async def test_a_changed_deadline_is_reported_once(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(due=now + timedelta(days=3))], now=now)

    moved = now + timedelta(days=5)
    changes = await repo.save_assignments(me, course, [_one(due=moved)], now=now)
    assert [one.id for one in changes.due_changed] and changes.created == []
    assert (await repo.assignments(me))[0].due_at == moved.astimezone(KST)

    nothing = await repo.save_assignments(me, course, [_one(due=moved)], now=now)
    assert nothing.due_changed == []


async def test_submitting_is_reported_once(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(due=now + timedelta(days=3))], now=now)

    handed_in = _one(due=now + timedelta(days=3), state="submitted", submitted_at=now)
    changes = await repo.save_assignments(me, course, [handed_in], now=now)
    assert len(changes.submitted) == 1

    graded = _one(due=now + timedelta(days=3), state="graded", submitted_at=now)
    again = await repo.save_assignments(me, course, [graded], now=now)
    assert again.submitted == []  # submitted → graded는 새 제출이 아니다
    assert (await repo.assignments(me, state="submitted"))[0].submission_state == "graded"


async def test_an_assignment_that_disappeared_is_marked_removed(world: dict[str, Any]) -> None:
    """LMS에서 지운 과제는 기록만 남기고 목록·숫자에서 뺀다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11), _one(12, title="실습 3주차")], now=now)

    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    assert changes.removed == 1
    assert [one.title for one in await repo.assignments(me, state="all")] == [
        "실습 2주차 결과 제출"
    ]
    assert (await repo.courses(me, now=now))[0].open_assignments == 1


async def test_an_empty_list_removes_the_assignments(world: dict[str, Any]) -> None:
    """과제는 0건인 과목이 흔하다(녹화 6과목 중 2과목). 과목 목록과 달리 빈 목록을 믿는다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11)], now=now)

    changes = await repo.save_assignments(me, course, [], now=now)
    assert changes.removed == 1
    assert await repo.assignments(me, state="all") == []


async def test_an_assignment_that_comes_back_counts_as_new(world: dict[str, Any]) -> None:
    """사라졌다 다시 나타나면 새 과제다. 그 사이 할 일·알림이 없었다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11)], now=now)
    await repo.save_assignments(me, course, [], now=now)

    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    assert len(changes.created) == 1
    assert len(await repo.assignments(me, state="all")) == 1  # 줄은 하나다(upsert)


async def test_assignments_of_another_user_are_not_mine(world: dict[str, Any]) -> None:
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    await repo.save_courses(other, [DATABASE], now=now)
    mine = await _course_id(world)
    row = await (
        await world["conn"].execute(
            "select id from lms_courses where user_id = %s and canvas_course_id = %s",
            (other, DATABASE["id"]),
        )
    ).fetchone()
    await repo.save_assignments(me, mine, [_one(11)], now=now)
    await repo.save_assignments(other, str(row["id"]), [_one(11), _one(12)], now=now)

    assert len(await repo.assignments(me, state="all")) == 1
    assert len(await repo.assignments(other, state="all")) == 2
    # 남의 동기화가 내 과제를 지우지 않는다
    await repo.save_assignments(other, str(row["id"]), [], now=now)
    assert len(await repo.assignments(me, state="all")) == 1


async def test_an_assignment_already_submitted_when_first_seen_is_quiet(
    world: dict[str, Any],
) -> None:
    """연결 첫 동기화에는 지난 과제가 한꺼번에 들어온다(녹화 17건 중 13건이 제출·채점 완료).
    낸 과제로 할 일을 만들거나 "새 과제" 알림을 보내면 안 된다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    old = _one(11, title="지난 과제", due=now - timedelta(days=9), state="graded", submitted_at=now)

    changes = await repo.save_assignments(me, course, [old], now=now)
    assert [one.title for one in changes.created] == ["지난 과제"]
    assert changes.created[0].submitted is True
    assert await repo.sync_planner(me, changes, now=now) == 0
    assert await _tasks(world) == []


async def test_a_dropped_courses_assignments_leave_the_list(world: dict[str, Any]) -> None:
    """수강을 빼면 그 과목의 과제는 더 받지 않는다(사라진 표시도 안 붙는다). 목록에서 뺀다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE, MACHINE_LEARNING], now=now)
    db = await _course_id(world)
    await repo.save_assignments(me, db, [_one(11, due=now + timedelta(days=3))], now=now)
    assert len(await repo.assignments(me)) == 1

    await repo.save_courses(me, [MACHINE_LEARNING], now=now)  # 데이터베이스를 뺐다
    assert await repo.assignments(me) == []
    assert await repo.assignments(me, state="all") == []


async def test_sweeping_twice_removes_nothing_the_second_time(world: dict[str, Any]) -> None:
    """사라진 표시는 한 번만 찍는다. 매번 다시 찍으면 동기화 결과가 거짓말을 한다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11)], now=now)
    assert (await repo.save_assignments(me, course, [], now=now)).removed == 1
    assert (await repo.save_assignments(me, course, [], now=now)).removed == 0


async def test_the_first_time_we_saw_an_assignment_is_kept(world: dict[str, Any]) -> None:
    """`first_seen_at`은 처음 본 때다. 다시 받을 때마다 밀리면 "새 자료" 기준이 무너진다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    await repo.save_assignments(me, course, [_one(11)], now=now)
    later = now + timedelta(days=1)
    await repo.save_assignments(me, course, [_one(11, title="이름이 바뀌었다")], now=later)

    row = await (
        await conn.execute(
            "select first_seen_at, title from lms_assignments where user_id = %s", (me,)
        )
    ).fetchone()
    assert row["first_seen_at"] == now  # 처음 본 때 그대로
    assert row["title"] == "이름이 바뀌었다"  # 제목은 갱신된다


async def test_the_list_does_not_borrow_another_users_task_or_event(
    world: dict[str, Any],
) -> None:
    """같은 과제 id를 가리키는 남의 할 일·캘린더 행이 내 목록에 붙지 않는다."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    assignment_id = changes.created[0].id
    # 남이 내 과제를 가리키는 행을 가졌다(실제로는 생기지 않지만, 조건이 빠지면 섞인다)
    await conn.execute(
        "insert into planner_tasks (user_id, source, lms_assignment_id, title, due_date)"
        " values (%s, 'lms_assignment', %s, '남의 할 일', %s)",
        (other, assignment_id, now.date()),
    )
    await conn.execute(
        "insert into calendar_events (user_id, provider, lms_assignment_id, title, starts_at,"
        " external_event_id) values (%s, 'google', %s, '남의 일정', %s, 'ev-9')",
        (other, assignment_id, now),
    )

    item = (await repo.assignments(me))[0]
    assert item.planner_task_id is None
    assert item.calendar_registered is False


# ── 과제 목록 (F-51) ────────────────────────────────────────────────────────


async def test_the_assignment_list_filters_and_sorts(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE, MACHINE_LEARNING], now=now)
    db, ml = await _course_id(world), await _course_id(world, MACHINE_LEARNING["id"])
    await repo.save_assignments(
        me,
        db,
        [
            _one(11, title="마감 없는 과제"),
            _one(12, title="늦은 과제", due=now + timedelta(days=9)),
            _one(13, title="낸 과제", due=now + timedelta(days=1), state="graded"),
        ],
        now=now,
    )
    await repo.save_assignments(
        me, ml, [_one(21, title="이른 과제", due=now + timedelta(days=2))], now=now
    )

    assert [one.title for one in await repo.assignments(me)] == [
        "이른 과제",
        "늦은 과제",
        "마감 없는 과제",  # 마감이 없는 과제는 뒤로 간다
    ]
    assert [one.title for one in await repo.assignments(me, state="submitted")] == ["낸 과제"]
    # pending_review(냈고 채점만 남음)도 제출 쪽이다. 어느 state에도 안 들어가면 안 된다
    await repo.save_assignments(
        me,
        ml,
        [
            _one(
                21, title="이른 과제", due=now + timedelta(days=2)
            ),  # 목록에서 빠지지 않게 함께 보낸다
            _one(22, title="검토 중 과제", due=now + timedelta(days=3), state="pending_review"),
        ],
        now=now,
    )
    assert "검토 중 과제" in [one.title for one in await repo.assignments(me, state="submitted")]
    assert "검토 중 과제" not in [one.title for one in await repo.assignments(me)]
    assert len(await repo.assignments(me, state="all")) == 5
    assert [one.title for one in await repo.assignments(me, course_id=ml)] == ["이른 과제"]


async def test_the_list_shows_the_task_and_calendar_links(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, changes, now=now)
    assignment_id = changes.created[0].id
    await conn.execute(
        "insert into calendar_events (user_id, provider, lms_assignment_id, title, starts_at,"
        " external_event_id) values (%s, 'google', %s, '마감', %s, 'ev-1')",
        (me, assignment_id, now + timedelta(days=3)),
    )

    item = (await repo.assignments(me))[0]
    assert item.planner_task_id is not None
    assert item.calendar_registered is True


async def test_a_calendar_row_without_an_event_is_not_registered(world: dict[str, Any]) -> None:
    """등록을 시작했다 못 끝낸 행이다(F-32의 reserve). 등록됐다고 보여 주면 안 된다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    await conn.execute(
        "insert into calendar_events (user_id, provider, lms_assignment_id, title, starts_at)"
        " values (%s, 'google', %s, '마감', %s)",
        (me, changes.created[0].id, now),
    )
    assert (await repo.assignments(me))[0].calendar_registered is False


# ── 플래너 (F-51·F-43) ──────────────────────────────────────────────────────


async def _tasks(world: dict[str, Any]) -> list[dict[str, Any]]:
    return await (
        await world["conn"].execute(
            "select title, due_date, coalesce(is_done, false) as is_done, done_at,"
            " source::text as source, lms_assignment_id from planner_tasks"
            " where user_id = %s order by due_date, title",
            (world["me"],),
        )
    ).fetchall()


async def test_a_new_assignment_becomes_a_planner_task(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    due = now + timedelta(days=3)
    changes = await repo.save_assignments(me, course, [_one(11, due=due)], now=now)

    assert await repo.sync_planner(me, changes, now=now) == 1
    rows = await _tasks(world)
    assert len(rows) == 1
    assert rows[0]["title"] == "실습 2주차 결과 제출"
    assert rows[0]["due_date"] == due.astimezone(KST).date()  # 마감은 KST 날짜다
    assert rows[0]["source"] == "lms_assignment"
    assert not rows[0]["is_done"]


async def test_an_assignment_without_a_deadline_gets_no_task(world: dict[str, Any]) -> None:
    """할 일에는 날짜가 있어야 한다(planner_tasks.due_date). 마감이 생기면 그때 만든다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    assert await repo.sync_planner(me, changes, now=now) == 0
    assert await _tasks(world) == []

    later = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=2))], now=now
    )
    assert await repo.sync_planner(me, later, now=now) == 1


async def test_a_moved_deadline_moves_the_task(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)

    moved = now + timedelta(days=6)
    changes = await repo.save_assignments(me, course, [_one(11, due=moved)], now=now)
    assert await repo.sync_planner(me, changes, now=now) == 0  # 새로 만들지 않는다
    rows = await _tasks(world)
    assert len(rows) == 1 and rows[0]["due_date"] == moved.astimezone(KST).date()


async def test_submitting_finishes_the_task(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)

    handed_in = _one(11, due=now + timedelta(days=3), state="submitted", submitted_at=now)
    changes = await repo.save_assignments(me, course, [handed_in], now=now)
    await repo.sync_planner(me, changes, now=now)
    rows = await _tasks(world)
    assert rows[0]["is_done"] and rows[0]["done_at"] == now


async def test_a_task_the_student_deleted_is_not_made_again(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)
    await conn.execute("delete from planner_tasks where user_id = %s", (me,))

    moved = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=5))], now=now
    )
    await repo.sync_planner(me, moved, now=now)
    assert await _tasks(world) == []  # 지운 할 일을 되살리지 않는다


async def test_a_finished_task_is_left_alone_when_the_deadline_moves(
    world: dict[str, Any],
) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)
    await conn.execute(
        "update planner_tasks set is_done = true, done_at = %s where user_id = %s", (now, me)
    )

    moved = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=9))], now=now
    )
    await repo.sync_planner(me, moved, now=now)
    rows = await _tasks(world)
    assert rows[0]["due_date"] == (now + timedelta(days=3)).astimezone(KST).date()


async def test_the_planner_does_not_touch_another_users_task(world: dict[str, Any]) -> None:
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_courses(other, [DATABASE], now=now)
    row = await (
        await world["conn"].execute("select id from lms_courses where user_id = %s", (other,))
    ).fetchone()
    changes = await repo.save_assignments(
        other, str(row["id"]), [_one(11, due=now + timedelta(days=3))], now=now
    )
    assert await repo.sync_planner(me, changes, now=now) == 0  # 내 할 일이 아니다
    assert await _tasks(world) == []


# ── 알림 (F-51·F-33) ────────────────────────────────────────────────────────


async def test_a_new_assignment_makes_one_notice(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    notes = NotificationRepository(conn)
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    notice = AssignmentNotice(changes.created[0].id, "데이터베이스 새 과제가 올라왔어요", "실습")

    assert await notes.add_assignment_notices(me, [notice], now=now) == 1
    assert await notes.add_assignment_notices(me, [notice], now=now) == 0  # 같은 과제는 한 번만
    row = await (
        await conn.execute(
            "select type, title, body, scheduled_at, dedupe_key, lms_assignment_id, status::text"
            " as status from notifications where user_id = %s",
            (me,),
        )
    ).fetchone()
    assert row["type"] == "new_assignment"
    assert row["dedupe_key"] == f"new_assignment:asg:{changes.created[0].id}"  # ERD 5장 표
    assert row["scheduled_at"] == now  # 찾은 때 바로 보낸다(09:00을 기다리지 않는다)
    assert row["status"] == "pending"


async def test_someone_elses_mute_does_not_silence_me(world: dict[str, Any]) -> None:
    """남이 끈 종류 때문에 내 알림이 사라지면 안 된다(끈 설정은 사용자별이다)."""
    repo, me, other, now, conn = (
        world["repo"],
        world["me"],
        world["other"],
        world["now"],
        world["conn"],
    )
    notes = NotificationRepository(conn)
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    await conn.execute(
        "insert into user_settings (user_id, muted_notification_types)"
        " values (%s, array['new_assignment'])",
        (other,),
    )
    notice = AssignmentNotice(changes.created[0].id, "제목", "본문")
    assert await notes.add_assignment_notices(me, [notice], now=now) == 1


async def test_a_muted_type_makes_no_notice(world: dict[str, Any]) -> None:
    """설정에서 끈 종류는 만들지 않는다(F-45, ERD)."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    notes = NotificationRepository(conn)
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11)], now=now)
    await conn.execute(
        "insert into user_settings (user_id, muted_notification_types)"
        " values (%s, array['new_assignment']) on conflict (user_id) do update"
        " set muted_notification_types = array['new_assignment']",
        (me,),
    )
    notice = AssignmentNotice(changes.created[0].id, "제목", "본문")
    assert await notes.add_assignment_notices(me, [notice], now=now) == 0


async def test_submitting_drops_the_notice_that_was_not_sent(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    notes = NotificationRepository(conn)
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    changes = await repo.save_assignments(me, course, [_one(11), _one(12)], now=now)
    waiting, sent = (one.id for one in changes.created)
    await notes.add_assignment_notices(
        me,
        [AssignmentNotice(waiting, "가", "나"), AssignmentNotice(sent, "다", "라")],
        now=now,
    )
    await conn.execute(
        "update notifications set status = 'succeeded', sent_at = %s where lms_assignment_id = %s",
        (now, sent),
    )

    assert await notes.drop_assignment_notices(me, [waiting, sent]) == 1
    rows = await (
        await conn.execute("select lms_assignment_id from notifications where user_id = %s", (me,))
    ).fetchall()
    assert [str(row["lms_assignment_id"]) for row in rows] == [sent]  # 보낸 알림은 남는다


async def test_dropping_nothing_is_fine(world: dict[str, Any]) -> None:
    notes = NotificationRepository(world["conn"])
    assert await notes.drop_assignment_notices(world["me"], []) == 0


# ── 동기화 시각·배치 대상 (F-51) ────────────────────────────────────────────


async def test_touching_the_sync_time_clears_the_error(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.mark_error(me, "토큰이 만료되었거나 삭제되었어요.")

    later = now + timedelta(hours=1)
    await repo.touch_synced(me, now=later)
    found = await repo.connection(me)
    assert found is not None
    assert (found.status, found.last_error) == ("active", None)
    assert found.last_synced_at == later


async def test_a_sync_can_be_claimed_only_once_in_the_window(world: dict[str, Any]) -> None:
    """같은 사용자를 두 번 동시에 동기화하지 않는다. 한 문장으로 자리를 잡는다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    window = timedelta(minutes=5)

    # 방금 연결해서 last_synced_at이 now다 → 5분 안에는 못 가져간다
    assert await repo.claim_sync(me, now=now, before=now - window) is False

    later = now + timedelta(minutes=6)
    assert await repo.claim_sync(me, now=later, before=later - window) is True
    found = await repo.connection(me)
    assert found is not None and found.last_synced_at == later
    # 바로 다음 요청은 막힌다(앞의 claim이 시각을 밀어 뒀다)
    assert await repo.claim_sync(me, now=later, before=later - window) is False


async def test_a_claim_is_refused_when_there_is_no_connection(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    assert await repo.claim_sync(me, now=now, before=now) is False

    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await world["conn"].execute(
        "update lms_connections set status = 'disconnected' where user_id = %s", (me,)
    )
    assert await repo.claim_sync(me, now=now, before=now + timedelta(days=1)) is False


async def test_a_claim_does_not_touch_the_error_message(world: dict[str, Any]) -> None:
    """가져가는 것만으로 "잘 됐다"고 적지 않는다. 성공은 touch_synced가 적는다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.mark_error(me, "토큰이 만료되었거나 삭제되었어요.")
    later = now + timedelta(hours=1)

    assert await repo.claim_sync(me, now=later, before=later - timedelta(minutes=5)) is True
    found = await repo.connection(me)
    assert found is not None
    assert (found.status, found.last_error) == ("error", "토큰이 만료되었거나 삭제되었어요.")


async def test_a_user_whose_sync_keeps_failing_does_not_block_the_queue(
    world: dict[str, Any],
) -> None:
    """실패해도 claim이 시각을 밀어 둔다. 안 그러면 그 사람이 영원히 배치 앞자리를 차지한다."""
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_connection(
        me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now - timedelta(hours=3)
    )
    await repo.save_connection(
        other, token="enc-2", last4="b8e1", canvas_user_id=2, now=now - timedelta(hours=2)
    )
    before = now - timedelta(minutes=5)
    assert await repo.connected_users(before=before, limit=10) == [me, other]

    # me를 가져가 동기화했지만 실패해서 touch_synced는 못 불렀다
    assert await repo.claim_sync(me, now=now, before=before) is True
    assert await repo.connected_users(before=before, limit=10) == [other]


async def test_a_slow_sync_does_not_turn_the_clock_back(world: dict[str, Any]) -> None:
    """느린 동기화가 뒤에 시작한 동기화의 자리를 지워 버리면, 같은 사용자를 또 동기화하게 된다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    started = now + timedelta(minutes=10)  # 느린 동기화가 시작한 시각
    later = started + timedelta(minutes=6)  # 그 사이 배치가 가져갔다
    assert await repo.claim_sync(me, now=later, before=later - timedelta(minutes=5)) is True

    await repo.touch_synced(me, now=started)  # 느린 쪽이 뒤늦게 끝났다
    found = await repo.connection(me)
    assert found is not None and found.last_synced_at == later


async def test_finishing_a_sync_does_not_revive_a_disconnected_one(world: dict[str, Any]) -> None:
    """해제한 뒤에 끝난 동기화가 연결을 되살리면 안 된다."""
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await conn.execute(
        "update lms_connections set status = 'disconnected' where user_id = %s", (me,)
    )
    await repo.touch_synced(me, now=now + timedelta(minutes=1))
    found = await repo.connection(me)
    assert found is not None and found.status == "disconnected"


async def test_an_already_finished_task_keeps_its_done_time(world: dict[str, Any]) -> None:
    """제출 상태가 그대로인데 동기화마다 완료 시각을 다시 찍으면, 플래너가 오늘 끝낸 일로 보인다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, [DATABASE], now=now)
    course = await _course_id(world)
    first = await repo.save_assignments(
        me, course, [_one(11, due=now + timedelta(days=3))], now=now
    )
    await repo.sync_planner(me, first, now=now)
    handed_in = _one(11, due=now + timedelta(days=3), state="submitted", submitted_at=now)
    changes = await repo.save_assignments(me, course, [handed_in], now=now)
    await repo.sync_planner(me, changes, now=now)

    # 같은 과제를 그대로 다시 받아도(제출 변화 없음) 완료 시각은 그대로다
    later = now + timedelta(hours=2)
    again = await repo.save_assignments(me, course, [handed_in], now=later)
    await repo.sync_planner(me, AssignmentChanges(submitted=[first.created[0].id]), now=later)
    assert again.submitted == []
    rows = await _tasks(world)
    assert rows[0]["done_at"] == now


async def test_the_batch_takes_the_ones_waiting_longest(world: dict[str, Any]) -> None:
    repo, me, other, now = world["repo"], world["me"], world["other"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.save_connection(
        other, token="enc-2", last4="b8e1", canvas_user_id=2, now=now - timedelta(hours=2)
    )

    waiting = await repo.connected_users(before=now - timedelta(minutes=5), limit=10)
    assert waiting == [other]  # 방금 받은 me는 건너뛴다

    assert await repo.connected_users(before=now + timedelta(minutes=1), limit=10) == [other, me]
    assert await repo.connected_users(before=now + timedelta(minutes=1), limit=1) == [other]


async def test_a_disconnected_user_is_not_synced(world: dict[str, Any]) -> None:
    repo, me, now, conn = world["repo"], world["me"], world["now"], world["conn"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await conn.execute(
        "update lms_connections set status = 'disconnected' where user_id = %s", (me,)
    )
    assert await repo.connected_users(before=now + timedelta(days=1), limit=10) == []


async def test_a_broken_token_is_still_tried_again(world: dict[str, Any]) -> None:
    """error 상태도 배치에 넣는다. 사용자가 LMS에서 토큰을 되살리면 거기서 풀린다."""
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_connection(me, token="enc-1", last4="a9f2", canvas_user_id=1, now=now)
    await repo.mark_error(me, "토큰이 만료되었거나 삭제되었어요.")
    assert await repo.connected_users(before=now + timedelta(minutes=1), limit=10) == [me]


async def test_the_changes_add_up(world: dict[str, Any]) -> None:
    """과목마다 센 것을 더해 한 동기화 결과로 만든다(app/lms/sync.py)."""
    first = AssignmentChanges(
        created=[SavedAssignment("a", "가", None)], submitted=["s1"], removed=1
    )
    second = AssignmentChanges(due_changed=[SavedAssignment("b", "나", None)], removed=2)
    total = first + second
    assert (len(total.created), len(total.due_changed), total.submitted, total.removed) == (
        1,
        1,
        ["s1"],
        3,
    )


# ── 실행 결과 (F-51, GET /runs/{id}) ───────────────────────────────────────


async def _run_with(world: dict[str, Any], tool: str, output: Any) -> str:
    """도구 하나를 남긴 동기화 실행. 결과는 저장하지 않고 이 출력에서 다시 읽는다."""
    conn, me = world["conn"], world["me"]
    row = await (
        await conn.execute(
            "insert into agent_runs (user_id, trigger_type, status) values (%s, 'lms_sync',"
            " 'succeeded') returning id",
            (me,),
        )
    ).fetchone()
    run_id = str(row["id"])
    await conn.execute(
        "insert into tool_calls (run_id, seq, tool_name, input, output, status)"
        " values (%s, 1, %s, '{}'::jsonb, %s, 'succeeded')",
        (run_id, tool, Jsonb(output) if output is not None else None),
    )
    return run_id


async def test_the_run_result_comes_from_the_save_step(world: dict[str, Any]) -> None:
    conn, me = world["conn"], world["me"]
    run_id = await _run_with(
        world,
        SAVE_TOOL,
        {"courses": 2, "new": 1, "due_changed": 0, "submitted": 2, "notices": 1},
    )
    found = await RunRepository(conn).lms_sync_result(me, run_id)
    assert found is not None
    assert found.kind == "lms_sync"
    assert found.courses == 2
    assert (found.assignments.new, found.assignments.due_changed) == (1, 0)
    assert found.assignments.submitted == 2
    assert (found.new_module_items, found.new_announcements) == (0, 0)  # F-52·F-53


async def test_a_connect_run_has_no_sync_result(world: dict[str, Any]) -> None:
    """F-50 연결 실행도 trigger가 lms_sync다. 저장 단계가 없으면 결과는 없다."""
    run_id = await _run_with(world, "fetch_lms_courses", {"courses": 8})
    assert await RunRepository(world["conn"]).lms_sync_result(world["me"], run_id) is None


async def test_a_broken_output_is_read_as_no_result(world: dict[str, Any]) -> None:
    run_id = await _run_with(world, SAVE_TOOL, {"courses": "둘"})
    assert await RunRepository(world["conn"]).lms_sync_result(world["me"], run_id) is None
    empty = await _run_with(world, SAVE_TOOL, None)
    assert await RunRepository(world["conn"]).lms_sync_result(world["me"], empty) is None


async def test_another_users_run_result_is_not_mine(world: dict[str, Any]) -> None:
    run_id = await _run_with(
        world, SAVE_TOOL, {"courses": 1, "new": 0, "due_changed": 0, "submitted": 0}
    )
    assert await RunRepository(world["conn"]).lms_sync_result(world["other"], run_id) is None


async def test_the_steps_have_korean_labels(world: dict[str, Any]) -> None:
    """처리 과정(F-42)에 도구 이름이 그대로 나오지 않게 한다."""
    run_id = await _run_with(world, "fetch_lms_assignments", {"courses": 2})
    steps = await RunRepository(world["conn"]).steps(run_id)
    assert [(one.tool, one.label) for one in steps] == [("fetch_lms_assignments", "과제·제출 받기")]
