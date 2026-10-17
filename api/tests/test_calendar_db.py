"""캘린더 기록 SQL(F-32·F-51)을 실제 스키마에 대고 확인한다: 토큰, 준비한 공고, LMS 과제 마감,
등록·중복·시각 고치기·취소·격리.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import timedelta
from typing import Any

import pytest

from app.eligibility import KST
from app.repositories.calendar import CalendarRepository
from app.repositories.opportunities import OpportunityRepository
from tests.db_world import DATABASE_URL, World, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def calendar() -> Any:
    """준비를 마친 공고 하나와 준비하지 않은 공고 하나, 사용자 둘."""
    conn = await connect()
    try:
        world = await World.start(conn)
        prepared = await world.add("준비한 장학", days=9)
        bare = await world.add("준비 안 한 장학", days=9)
        user = await make_user(conn, grade=3)
        other = await make_user(conn, grade=3)
        run = await (
            await conn.execute(
                "insert into agent_runs (user_id, trigger_type, status)"
                " values (%s, 'prepare', 'succeeded') returning id",
                (user,),
            )
        ).fetchone()
        await conn.execute(
            "insert into prep_plans (user_id, opportunity_id, agent_run_id) values (%s, %s, %s)",
            (user, prepared, run["id"]),
        )
        yield CalendarRepository(conn), user, other, prepared, bare, world.now
    finally:
        await conn.rollback()
        await conn.close()


async def test_only_a_prepared_opportunity_is_offered(calendar: Any) -> None:
    repo, user, other, prepared, bare, now = calendar
    found = await repo.prepared_opportunity(user, prepared)
    assert found is not None and found.title == "준비한 장학"
    assert found.deadline_at is not None
    assert await repo.prepared_opportunity(user, bare) is None  # 준비하지 않은 공고
    assert await repo.prepared_opportunity(other, prepared) is None  # 남의 계획


async def test_a_running_plan_is_not_prepared_yet(calendar: Any) -> None:
    """상세·플래너와 같은 기준(PREP_DONE)이다. 실행 중인 계획은 캘린더에도 넣지 못한다."""
    repo, user, _, prepared, _, _ = calendar
    await repo.conn.execute(
        "update agent_runs set status = 'running' where id ="
        " (select agent_run_id from prep_plans where user_id = %s and opportunity_id = %s)",
        (user, prepared),
    )
    assert await repo.prepared_opportunity(user, prepared) is None


async def test_reserve_is_one_per_opportunity(calendar: Any) -> None:
    """자리는 공고마다 하나다. 두 번째 요청은 같은 행을 돌려받아 같은 Google 번호를 쓴다."""
    repo, user, _, prepared, _, now = calendar
    ends_at = (now + timedelta(days=9)).astimezone(KST)
    event = await repo.reserve(
        user,
        provider="google",
        opportunity_id=prepared,
        title="[마감] 준비한 장학",
        starts_at=ends_at - timedelta(hours=1),
    )
    assert (event.provider, event.external_event_id, event.all_day) == ("google", None, False)
    again = await repo.reserve(
        user,
        provider="google",
        opportunity_id=prepared,
        title="[마감] 준비한 장학",
        starts_at=ends_at - timedelta(hours=1),
    )
    assert again.id == event.id
    await repo.attach(user, event.id, "gcal-1")
    done = await repo.one(user, event.id)
    assert done is not None and done.external_event_id == "gcal-1"
    rows = await (
        await repo.conn.execute(
            "select count(*) as n from calendar_events where user_id = %s", (user,)
        )
    ).fetchone()
    assert rows["n"] == 1


async def test_find_and_remove(calendar: Any) -> None:
    repo, user, other, prepared, _, now = calendar
    ends_at = (now + timedelta(days=9)).astimezone(KST)
    event = await repo.reserve(
        user,
        provider="google",
        opportunity_id=prepared,
        title="[마감] 준비한 장학",
        starts_at=ends_at - timedelta(hours=1),
    )
    await repo.attach(user, event.id, "gcal-1")
    assert (await repo.event_for(user, "google", opportunity_id=prepared)).id == event.id
    assert await repo.event_for(user, "ics", opportunity_id=prepared) is None
    assert await repo.one(other, event.id) is None  # 남의 일정은 안 보인다
    await repo.remove(other, event.id)  # 남의 일정은 못 지운다
    assert await repo.one(user, event.id) is not None
    await repo.remove(user, event.id)
    assert await repo.one(user, event.id) is None


async def test_tokens_are_read_and_the_access_token_is_replaced(calendar: Any) -> None:
    repo, user, _, _, _, _ = calendar
    assert await repo.tokens(user) is None  # 연결 전
    await repo.conn.execute(
        "insert into oauth_tokens (user_id, provider, access_token, refresh_token, expires_at)"
        " values (%s, 'google', 'enc-access', 'enc-refresh', now() + interval '55 minutes')",
        (user,),
    )
    tokens = await repo.tokens(user)
    assert tokens is not None
    assert (tokens.access_token, tokens.refresh_token) == ("enc-access", "enc-refresh")
    await repo.save_access_token(user, "enc-new", 3599)
    after = await repo.tokens(user)
    assert after is not None
    assert after.access_token == "enc-new"
    assert after.refresh_token == "enc-refresh"  # refresh token은 그대로 둔다
    assert after.expires_at is not None and not after.expired(after.expires_at - timedelta(hours=1))


async def test_a_reserved_event_is_not_shown_as_registered(calendar: Any) -> None:
    """Google에 넣기 전의 자리는 공고 상세에서 '등록됨'으로 보이지 않는다(F-32).

    보이면 학생이 "캘린더에서 빼기"만 누를 수 있고, 실제로는 캘린더에 아무것도 없다.
    """
    repo, user, _, prepared, _, now = calendar
    ends_at = (now + timedelta(days=9)).astimezone(KST)
    event = await repo.reserve(
        user,
        provider="google",
        opportunity_id=prepared,
        title="[마감] 준비한 장학",
        starts_at=ends_at - timedelta(hours=1),
    )
    detail = await OpportunityRepository(repo.conn).detail(
        user, prepared, now=now, display_name="테스트 학생"
    )
    assert detail is not None and detail.prep.calendar_events == []
    await repo.attach(user, event.id, "gcal-1")
    after = await OpportunityRepository(repo.conn).detail(
        user, prepared, now=now, display_name="테스트 학생"
    )
    assert after is not None
    assert [ref.id for ref in after.prep.calendar_events] == [event.id]


# ── LMS 과제 마감 (F-51) ────────────────────────────────────────────────────


async def _assignment(
    conn: Any, user: str, *, due: Any, title: str = "실습 2주차 결과 제출"
) -> str:
    """과목 하나와 과제 하나를 넣고 과제 id를 돌려준다."""
    course = await (
        await conn.execute(
            "insert into lms_courses (user_id, canvas_course_id, name)"
            " values (%s, 214023, '202620HY23525_데이터베이스') returning id",
            (user,),
        )
    ).fetchone()
    row = await (
        await conn.execute(
            "insert into lms_assignments (user_id, lms_course_id, canvas_assignment_id, title,"
            " due_at, submission_state) values (%s, %s, 11, %s, %s, 'unsubmitted') returning id",
            (user, course["id"], title, due),
        )
    ).fetchone()
    return str(row["id"])


async def test_an_assignment_deadline_comes_with_the_course_name(calendar: Any) -> None:
    repo, user, _, _, _, now = calendar
    due = now + timedelta(days=4)
    assignment_id = await _assignment(repo.conn, user, due=due)

    found = await repo.assignment_deadline(user, assignment_id)
    assert found is not None
    assert (found.title, found.course) == ("실습 2주차 결과 제출", "데이터베이스")
    assert found.due_at == due


async def test_another_students_assignment_is_not_mine(calendar: Any) -> None:
    repo, user, other, _, _, now = calendar
    assignment_id = await _assignment(repo.conn, user, due=now + timedelta(days=4))
    assert await repo.assignment_deadline(other, assignment_id) is None


async def test_a_removed_assignment_or_dropped_course_is_gone(calendar: Any) -> None:
    repo, user, _, _, _, now = calendar
    assignment_id = await _assignment(repo.conn, user, due=now + timedelta(days=4))
    await repo.conn.execute(
        "update lms_assignments set removed_at = %s where id = %s", (now, assignment_id)
    )
    assert await repo.assignment_deadline(user, assignment_id) is None

    await repo.conn.execute("update lms_assignments set removed_at = null")
    await repo.conn.execute("update lms_courses set is_active = false where user_id = %s", (user,))
    assert await repo.assignment_deadline(user, assignment_id) is None


async def test_an_assignment_event_is_one_per_assignment(calendar: Any) -> None:
    """같은 과제를 두 번 넣어도 일정은 하나다(부분 유니크 인덱스)."""
    repo, user, _, _, _, now = calendar
    due = (now + timedelta(days=4)).astimezone(KST)
    assignment_id = await _assignment(repo.conn, user, due=due)

    event = await repo.reserve(
        user,
        provider="google",
        title="[과제] 데이터베이스 · 실습 2주차 결과 제출",
        starts_at=due - timedelta(hours=1),
        lms_assignment_id=assignment_id,
    )
    again = await repo.reserve(
        user,
        provider="google",
        title="[과제] 데이터베이스 · 실습 2주차 결과 제출",
        starts_at=due - timedelta(hours=1),
        lms_assignment_id=assignment_id,
    )
    assert again.id == event.id
    rows = await (
        await repo.conn.execute(
            "select count(*) as n from calendar_events where lms_assignment_id = %s",
            (assignment_id,),
        )
    ).fetchone()
    assert rows["n"] == 1

    found = await repo.event_for(user, "google", lms_assignment_id=assignment_id)
    assert found is not None and found.id == event.id
    assert await repo.event_for(user, "ics", lms_assignment_id=assignment_id) is None


async def test_events_for_assignments_reads_only_mine(calendar: Any) -> None:
    repo, user, other, _, _, now = calendar
    due = (now + timedelta(days=4)).astimezone(KST)
    mine = await _assignment(repo.conn, user, due=due)
    event = await repo.reserve(
        user,
        provider="google",
        title="[과제] 데이터베이스 · 실습",
        starts_at=due - timedelta(hours=1),
        lms_assignment_id=mine,
    )
    await repo.attach(user, event.id, "gcal-1")

    found = await repo.events_for_assignments(user, [mine])
    assert set(found) == {mine}
    assert found[mine].external_event_id == "gcal-1"
    assert await repo.events_for_assignments(other, [mine]) == {}
    assert await repo.events_for_assignments(user, []) == {}


async def test_moving_an_event_changes_only_the_time(calendar: Any) -> None:
    repo, user, other, _, _, now = calendar
    due = (now + timedelta(days=4)).astimezone(KST)
    assignment_id = await _assignment(repo.conn, user, due=due)
    event = await repo.reserve(
        user,
        provider="google",
        title="[과제] 데이터베이스 · 실습",
        starts_at=due - timedelta(hours=1),
        lms_assignment_id=assignment_id,
    )
    await repo.attach(user, event.id, "gcal-1")

    moved = (now + timedelta(days=9)).astimezone(KST)
    await repo.move(user, event.id, starts_at=moved - timedelta(hours=1))
    found = await repo.one(user, event.id)
    assert found is not None
    assert found.starts_at == moved - timedelta(hours=1)
    assert found.external_event_id == "gcal-1"  # Google 번호는 그대로다

    await repo.move(other, event.id, starts_at=now)  # 남의 일정은 못 고친다
    again = await repo.one(user, event.id)
    assert again is not None and again.starts_at == moved - timedelta(hours=1)


async def test_the_auto_setting_defaults_to_on(calendar: Any) -> None:
    """설정 행이 없으면 기본 켬이다(ERD 기본값). 끄면 false를 본다."""
    repo, user, _, _, _, _ = calendar
    assert await repo.auto_lms(user) is True

    await repo.conn.execute(
        "insert into user_settings (user_id, calendar_auto_lms) values (%s, false)", (user,)
    )
    assert await repo.auto_lms(user) is False


async def test_one_target_only(calendar: Any) -> None:
    """공고와 과제를 함께 주거나 둘 다 비우면 코드 잘못이다(SQL까지 가지 않는다)."""
    repo, user, _, prepared, _, now = calendar
    with pytest.raises(ValueError):
        await repo.event_for(user, "google")
    with pytest.raises(ValueError):
        await repo.event_for(user, "google", opportunity_id=prepared, lms_assignment_id=prepared)


async def test_unfinished_events_are_picked_up_again(calendar: Any) -> None:
    """Google에 넣지 못해 자리만 남은 과제는 다음 동기화가 다시 가져간다(F-51)."""
    repo, user, other, _, _, now = calendar
    due = now + timedelta(days=4)
    assignment_id = await _assignment(repo.conn, user, due=due)
    await repo.reserve(
        user, provider="google", title="[과제] 데이터베이스 · 실습", starts_at=now,
        lms_assignment_id=assignment_id,
    )  # fmt: skip

    pending = await repo.unfinished_assignment_events(user)
    assert [(one.id, one.course, one.due_at) for one in pending] == [
        (assignment_id, "데이터베이스", due)
    ]
    assert await repo.unfinished_assignment_events(other) == []  # 남의 것은 안 준다


async def test_an_event_already_in_google_is_not_picked_up(calendar: Any) -> None:
    repo, user, _, _, _, now = calendar
    assignment_id = await _assignment(repo.conn, user, due=now + timedelta(days=4))
    event = await repo.reserve(
        user, provider="google", title="[과제] 데이터베이스 · 실습", starts_at=now,
        lms_assignment_id=assignment_id,
    )  # fmt: skip
    await repo.attach(user, event.id, "gcal-1")

    assert await repo.unfinished_assignment_events(user) == []


async def test_a_gone_assignment_is_not_picked_up(calendar: Any) -> None:
    """사라진 과제·수강 뺀 과목·마감이 없어진 과제는 다시 넣지 않는다."""
    repo, user, _, _, _, now = calendar
    assignment_id = await _assignment(repo.conn, user, due=now + timedelta(days=4))
    await repo.reserve(
        user, provider="google", title="[과제] 데이터베이스 · 실습", starts_at=now,
        lms_assignment_id=assignment_id,
    )  # fmt: skip

    await repo.conn.execute(
        "update lms_assignments set removed_at = now() where id = %s", (assignment_id,)
    )
    assert await repo.unfinished_assignment_events(user) == []
    await repo.conn.execute(
        "update lms_assignments set removed_at = null, due_at = null where id = %s",
        (assignment_id,),
    )
    assert await repo.unfinished_assignment_events(user) == []
    await repo.conn.execute(
        "update lms_assignments set due_at = %s where id = %s",
        (now + timedelta(days=4), assignment_id),
    )
    await repo.conn.execute("update lms_courses set is_active = false where user_id = %s", (user,))
    assert await repo.unfinished_assignment_events(user) == []


async def test_a_place_not_yet_in_google_takes_the_new_time(calendar: Any) -> None:
    """넣다 만 자리를 다시 쓸 때는 제목·시각을 새로 맞춘다(그새 마감이 바뀌었을 수 있다)."""
    repo, user, _, prepared, _, now = calendar
    first = await repo.reserve(
        user, provider="google", title="[마감] 준비한 장학", starts_at=now, opportunity_id=prepared
    )  # fmt: skip
    later = now + timedelta(days=1)

    again = await repo.reserve(
        user, provider="google", title="[마감] 준비한 장학 (연장)", starts_at=later,
        opportunity_id=prepared,
    )  # fmt: skip
    assert (again.id, again.title, again.starts_at) == (
        first.id,
        "[마감] 준비한 장학 (연장)",
        later,
    )


async def test_a_place_already_in_google_keeps_its_time(calendar: Any) -> None:
    """이미 Google에 들어간 일정은 기록만 바꾸면 캘린더와 어긋난다. 그대로 둔다."""
    repo, user, _, prepared, _, now = calendar
    first = await repo.reserve(
        user, provider="google", title="[마감] 준비한 장학", starts_at=now, opportunity_id=prepared
    )  # fmt: skip
    await repo.attach(user, first.id, "gcal-1")

    again = await repo.reserve(
        user, provider="google", title="[마감] 바뀐 제목", starts_at=now + timedelta(days=1),
        opportunity_id=prepared,
    )  # fmt: skip
    assert (again.title, again.starts_at, again.external_event_id) == (
        "[마감] 준비한 장학",
        now,
        "gcal-1",
    )


async def test_the_time_comes_back_in_kst(calendar: Any) -> None:
    """화면은 KST로 보여 준다(명세 1장). 저장은 UTC다."""
    repo, user, _, prepared, _, now = calendar
    event = await repo.reserve(
        user, provider="google", title="[마감] 준비한 장학", starts_at=now, opportunity_id=prepared
    )  # fmt: skip
    assert event.starts_at.utcoffset() == KST.utcoffset(None)
    assert event.starts_at == now


# ── 계획서 일정 (F-14) ──────────────────────────────────────────────────────


async def _syllabus_item(
    conn: Any,
    user: str,
    *,
    starts_at: Any,
    confirmed: bool = True,
    with_course: bool = True,
    kind: str = "midterm",
) -> str:
    """계획서 하나와 일정 하나. 과목을 붙이면 제목에 과목 이름이 따라온다."""
    course = None
    if with_course:
        course = await (
            await conn.execute(
                "insert into lms_courses (user_id, canvas_course_id, name) values (%s, %s, %s)"
                " returning id",
                (user, 9_910_001, "202620HY23525_데이터베이스"),
            )
        ).fetchone()
    syllabus = await (
        await conn.execute(
            "insert into syllabi (user_id, lms_course_id, semester) values (%s, %s, '2026-2')"
            " returning id",
            (user, course["id"] if course else None),
        )
    ).fetchone()
    row = await (
        await conn.execute(
            "insert into syllabus_items (syllabus_id, item_type, title, starts_at, is_confirmed)"
            " values (%s, %s, '중간고사', %s, %s) returning id",
            (syllabus["id"], kind, starts_at, confirmed),
        )
    ).fetchone()
    return str(row["id"])


async def test_a_confirmed_syllabus_item_comes_with_the_course_name(calendar: Any) -> None:
    repo, user, _, _, _, now = calendar
    starts = now + timedelta(days=6)
    item_id = await _syllabus_item(repo.conn, user, starts_at=starts)

    found = await repo.syllabus_deadline(user, item_id)
    assert found is not None
    assert (found.title, found.course, found.item_type) == ("중간고사", "데이터베이스", "midterm")
    assert found.starts_at == starts


async def test_an_unconfirmed_item_cannot_go_in_the_calendar(calendar: Any) -> None:
    """확인 전 추출 결과는 날짜가 틀릴 수 있다. 확인한 뒤에만 넣는다."""
    repo, user, _, _, _, now = calendar
    item_id = await _syllabus_item(
        repo.conn, user, starts_at=now + timedelta(days=6), confirmed=False
    )
    assert await repo.syllabus_deadline(user, item_id) is None


async def test_another_students_syllabus_item_is_not_mine(calendar: Any) -> None:
    repo, user, other, _, _, now = calendar
    item_id = await _syllabus_item(repo.conn, user, starts_at=now + timedelta(days=6))
    assert await repo.syllabus_deadline(other, item_id) is None


async def test_a_syllabus_without_a_course_has_no_course_name(calendar: Any) -> None:
    repo, user, _, _, _, now = calendar
    item_id = await _syllabus_item(
        repo.conn, user, starts_at=now + timedelta(days=6), with_course=False
    )
    found = await repo.syllabus_deadline(user, item_id)
    assert found is not None and found.course is None


async def test_a_syllabus_event_is_one_per_item(calendar: Any) -> None:
    """같은 일정을 두 번 넣어도 캘린더 기록은 하나다(부분 유니크 인덱스)."""
    repo, user, _, _, _, now = calendar
    starts = (now + timedelta(days=6)).astimezone(KST)
    item_id = await _syllabus_item(repo.conn, user, starts_at=starts)

    event = await repo.reserve(
        user,
        provider="google",
        title="[시험] 데이터베이스 · 중간고사",
        starts_at=starts,
        syllabus_item_id=item_id,
    )
    await repo.attach(user, event.id, "gcal-syllabus-1")
    again = await repo.reserve(
        user,
        provider="google",
        title="[시험] 데이터베이스 · 중간고사",
        starts_at=starts,
        syllabus_item_id=item_id,
    )
    assert again.id == event.id
    assert again.external_event_id == "gcal-syllabus-1"  # 이미 넣은 일정은 그대로 둔다
    found = await repo.event_for(user, "google", syllabus_item_id=item_id)
    assert found is not None and found.id == event.id


async def test_a_syllabus_item_is_a_target_on_its_own(calendar: Any) -> None:
    """공고·과제와 함께 주면 코드 잘못이다(SQL까지 가지 않는다)."""
    repo, user, _, prepared, _, _ = calendar
    with pytest.raises(ValueError):
        await repo.event_for(user, "google", opportunity_id=prepared, syllabus_item_id=prepared)
