"""플래너 SQL(F-43)을 실제 스키마에 대고 확인한다: 기간·완료 거르기, 마커, 수정·삭제 권한.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.eligibility import KST
from app.repositories.planner import PlannerRepository
from tests.db_world import DATABASE_URL, World, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def planner() -> Any:
    """사용자 둘, 준비한 공고 하나(서류 할 일 2개)와 직접 추가한 할 일 하나."""
    conn = await connect()
    try:
        world = await World.start(conn)
        opportunity = await world.add("준비 장학", days=10)
        user = await make_user(conn, grade=3)
        other = await make_user(conn, grade=3)
        today = world.now.astimezone(KST).date()  # 머신 시간대가 아니라 KST로 센다
        plan = await (
            await conn.execute(
                "insert into prep_plans (user_id, opportunity_id) values (%s, %s) returning id",
                (user, opportunity),
            )
        ).fetchone()
        ids: dict[str, str] = {}
        for name, due, done in (("재학증명서 준비", 2, False), ("신청 제출", 9, True)):
            row = await (
                await conn.execute(
                    "insert into planner_tasks (user_id, prep_plan_id, title, due_date, source,"
                    " is_done) values (%s, %s, %s, %s, 'prep_plan', %s) returning id",
                    (user, plan["id"], name, today + timedelta(days=due), done),
                )
            ).fetchone()
            ids[name] = str(row["id"])
        row = await (
            await conn.execute(
                "insert into planner_tasks (user_id, title, due_date, source)"
                " values (%s, '스터디 자료 정리', %s, 'manual') returning id",
                (user, today + timedelta(days=3)),
            )
        ).fetchone()
        ids["스터디 자료 정리"] = str(row["id"])
        yield PlannerRepository(conn), user, other, today, ids, opportunity
    finally:
        await conn.rollback()
        await conn.close()


async def test_tasks_in_a_range_with_their_opportunity(planner: Any) -> None:
    """기간 안의 할 일을 날짜 순으로 주고, 공고에서 온 할 일에는 공고 제목·카테고리가 붙는다."""
    repo, user, _, today, ids, opportunity = planner
    found = await repo.tasks(user, start=today, end=today + timedelta(days=30), include_done=True)
    assert [task.title for task in found.items] == [
        "재학증명서 준비",
        "스터디 자료 정리",
        "신청 제출",
    ]
    prep = found.items[0]
    assert prep.source == "prep_plan"
    assert (prep.link.type, prep.link.id, prep.link.category) == (
        "opportunity",
        opportunity,
        "scholarship",
    )
    assert prep.link.title == "준비 장학"
    manual = found.items[1]
    assert manual.source == "manual"
    assert (manual.link.type, manual.link.id, manual.link.title) == (None, None, None)


async def test_a_narrow_range_and_include_done(planner: Any) -> None:
    repo, user, _, today, _, _ = planner
    narrow = await repo.tasks(user, start=today, end=today + timedelta(days=2), include_done=True)
    assert [task.title for task in narrow.items] == ["재학증명서 준비"]
    undone = await repo.tasks(user, start=today, end=today + timedelta(days=30), include_done=False)
    assert [task.title for task in undone.items] == ["재학증명서 준비", "스터디 자료 정리"]


async def test_markers_are_the_deadlines_of_prepared_opportunities(planner: Any) -> None:
    """마커는 준비 중인 공고의 마감일이다. 준비하지 않은 공고는 들어가지 않는다."""
    repo, user, other, today, _, opportunity = planner
    found = await repo.tasks(user, start=today, end=today + timedelta(days=30), include_done=True)
    assert len(found.markers) == 1
    marker = found.markers[0]
    assert (marker.kind, marker.title, marker.opportunity_id) == (
        "deadline",
        "준비 장학 마감",
        opportunity,
    )
    assert marker.date == today + timedelta(days=10) and marker.category == "scholarship"
    # 준비하지 않은 다른 학생에게는 마커도 할 일도 없다
    none = await repo.tasks(other, start=today, end=today + timedelta(days=30), include_done=True)
    assert (none.items, none.markers) == ([], [])


async def test_a_marker_outside_the_range_is_left_out(planner: Any) -> None:
    repo, user, _, today, _, _ = planner
    found = await repo.tasks(user, start=today, end=today + timedelta(days=5), include_done=True)
    assert found.markers == []


async def test_add_update_and_remove(planner: Any) -> None:
    repo, user, _, today, _, _ = planner
    added = await repo.add(user, "면접 준비", today + timedelta(days=4))
    assert (added.title, added.source, added.is_done) == ("면접 준비", "manual", False)
    assert added.due_date == today + timedelta(days=4)
    done = await repo.update(user, added.id, {"is_done": True})
    assert done.is_done is True
    moved = await repo.update(user, added.id, {"due_date": today + timedelta(days=6)})
    assert moved.due_date == today + timedelta(days=6) and moved.is_done is True
    await repo.remove(user, added.id)
    assert await repo.one(user, added.id) is None


async def test_done_at_follows_the_check(planner: Any) -> None:
    """완료로 바꾸면 done_at을 찍고, 풀면 지운다(지표에 쓴다)."""
    repo, user, _, today, ids, _ = planner
    task_id = ids["재학증명서 준비"]
    await repo.update(user, task_id, {"is_done": True})
    assert await _done_at(repo, task_id) is not None
    await repo.update(user, task_id, {"is_done": False})
    assert await _done_at(repo, task_id) is None


async def test_another_students_task_is_invisible(planner: Any) -> None:
    """남의 할 일은 읽지도 고치지도 지우지도 못한다(SQL에 user_id 조건이 있다)."""
    repo, user, other, _, ids, _ = planner
    task_id = ids["스터디 자료 정리"]
    assert await repo.task(other, task_id) is None
    assert await repo.one(other, task_id) is None
    await repo.remove(other, task_id)  # 아무것도 지우지 않는다
    assert await repo.one(user, task_id) is not None


async def _done_at(repo: PlannerRepository, task_id: str) -> Any:
    row = await (
        await repo.conn.execute("select done_at from planner_tasks where id = %s", (task_id,))
    ).fetchone()
    return row["done_at"]


async def test_a_deadline_late_at_night_counts_as_the_kst_day(planner: Any) -> None:
    """마커 날짜는 KST로 센다. UTC로는 전날인 마감도 KST 날짜에 찍힌다(CI가 UTC여도 같다)."""
    repo, user, _, _, _, opportunity = planner
    # 2026-10-24 15:30 UTC = 2026-10-25 00:30 KST
    await repo.conn.execute(
        "update opportunities set deadline_at = %s where id = %s",
        (datetime(2026, 10, 24, 15, 30, tzinfo=UTC), opportunity),
    )
    kst_day = date(2026, 10, 25)
    found = await repo.tasks(user, start=kst_day, end=kst_day, include_done=True)
    assert [marker.date for marker in found.markers] == [kst_day]
    utc_day = date(2026, 10, 24)
    missing = await repo.tasks(user, start=utc_day, end=utc_day, include_done=True)
    assert missing.markers == []


async def test_a_plan_that_is_still_running_has_no_marker(planner: Any) -> None:
    """실행 중·멈춘 계획은 상세가 '준비하지 않음'으로 보여 준다. 플래너 마커도 같은 기준이다."""
    repo, user, _, today, _, _ = planner
    run = await (
        await repo.conn.execute(
            "insert into agent_runs (user_id, trigger_type, status)"
            " values (%s, 'prepare', 'running') returning id",
            (user,),
        )
    ).fetchone()
    await repo.conn.execute(
        "update prep_plans set agent_run_id = %s where user_id = %s", (run["id"], user)
    )
    found = await repo.tasks(user, start=today, end=today + timedelta(days=30), include_done=True)
    assert found.markers == []
    await repo.conn.execute(
        "update agent_runs set status = 'succeeded' where id = %s", (run["id"],)
    )
    done = await repo.tasks(user, start=today, end=today + timedelta(days=30), include_done=True)
    assert len(done.markers) == 1  # 실행이 성공하면 다시 보인다
