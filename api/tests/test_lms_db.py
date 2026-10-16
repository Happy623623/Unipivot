"""LearningX 연결·과목 SQL(F-50)을 실제 스키마에 대고 확인한다: 토큰 저장·교체·삭제,
과목 upsert와 수강 뺀 과목 내리기, 과목 목록의 숫자와 격리.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import timedelta
from typing import Any

import pytest

from app.eligibility import KST
from app.repositories.lms import LmsRepository
from tests.db_world import DATABASE_URL, connect, make_user
from tests.lms_samples import DATABASE, MACHINE_LEARNING, MINE, SEMINAR

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


async def test_the_list_is_sorted_by_course_name(world: dict[str, Any]) -> None:
    repo, me, now = world["repo"], world["me"], world["now"]
    await repo.save_courses(me, MINE, now=now)
    names = [one.name for one in await repo.courses(me, now=now)]
    assert names == sorted(names)


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
