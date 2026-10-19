"""문서함 SQL(F-44)을 실제 스키마에 대고 확인한다: 내 강의자료·계획서만, 과목 찾기, 최신순과 cursor.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.repositories.files import DOCUMENTS_SCOPE, DocumentFile, FileRepository
from app.repositories.opportunities import decode_cursor
from tests.db_world import DATABASE_URL, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

T0 = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)  # 2026-10-14 10:00 KST


@pytest.fixture
async def world() -> Any:
    conn = await connect()
    try:
        yield FileRepository(conn), await make_user(conn), await make_user(conn)
    finally:
        await conn.rollback()
        await conn.close()


async def course(repo: FileRepository, user: str, name: str = "202620HY23534_기계학습") -> str:
    row = await (
        await repo.conn.execute(
            "insert into lms_courses (user_id, canvas_course_id, name) values (%s, %s, %s)"
            " returning id::text as id",
            (user, int(uuid4().int % 1_000_000_000), name),
        )
    ).fetchone()
    assert row is not None
    return row["id"]


async def add_file(
    repo: FileRepository,
    user: str,
    *,
    kind: str = "lecture_material",
    origin: str = "upload",
    course_id: str | None = None,
    name: str | None = "자료.pdf",
    at: datetime | None = T0,
    size: int | None = 1000,
) -> str:
    file_id = str(uuid4())
    await repo.conn.execute(
        "insert into files (id, user_id, lms_course_id, kind, origin, external_ref, storage_path,"
        " size_bytes, sha256, original_name, created_at)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            file_id,
            user,
            course_id,
            kind,
            origin,
            str(uuid4()) if origin == "lms_attachment" else None,
            f"{user}/{kind}/{file_id}.pdf",
            size,
            uuid4().hex * 2,
            name,
            at,
        ),
    )
    return file_id


async def link_syllabus(
    repo: FileRepository, user: str, file_id: str, course_id: str | None
) -> None:
    await repo.conn.execute(
        "insert into syllabi (user_id, lms_course_id, file_id) values (%s, %s, %s)",
        (user, course_id, file_id),
    )


async def all_ids(repo: FileRepository, user: str) -> list[str]:
    page = await repo.documents(user, limit=50, after=None)
    return [item.file_id for item in page.items]


async def test_only_my_lecture_materials_and_syllabi_come_newest_first(world: Any) -> None:
    repo, me, other = world
    ml = await course(repo, me)
    attachment = await add_file(
        repo,
        me,
        origin="lms_attachment",
        course_id=ml,
        name="중간고사 대비 예제.pdf",
        at=T0 + timedelta(hours=3),
        size=86169,
    )
    syllabus = await add_file(
        repo, me, kind="syllabus", name="계획서.pdf", at=T0 + timedelta(hours=2)
    )
    material = await add_file(repo, me, name=None, at=T0 + timedelta(hours=1), size=None)
    await add_file(repo, me, kind="poster", name="포스터.pdf", at=T0 + timedelta(hours=4))
    await add_file(repo, other, at=T0 + timedelta(hours=5))  # 남의 자료

    page = await repo.documents(me, limit=20, after=None)
    assert [item.file_id for item in page.items] == [attachment, syllabus, material]
    assert page.next_cursor is None
    first = page.items[0].model_dump(mode="json")
    assert first == {
        "file_id": attachment,
        "file_name": "중간고사 대비 예제.pdf",
        "kind": "lecture_material",
        "origin": "lms_attachment",
        "course": {"id": ml, "short_name": "기계학습", "is_active": True},  # 과목명 `_` 뒤
        "size_bytes": 86169,
        "created_at": "2026-10-14T13:00:00+09:00",
    }
    assert page.items[1].kind == "syllabus" and page.items[1].origin == "upload"
    assert page.items[2].file_name == "파일.pdf"  # 원래 이름이 없으면 확장자로
    assert page.items[2].size_bytes is None and page.items[2].course is None


async def test_a_syllabus_finds_its_course_through_its_syllabus_row(world: Any) -> None:
    """계획서는 올릴 때가 아니라 일정을 뽑을 때 과목을 고른다. 과목은 계획서 행에 있다."""
    repo, me, _ = world
    linear = await course(repo, me, "202620HY23525_선형대수")
    linked = await add_file(repo, me, kind="syllabus", at=T0 + timedelta(hours=2))
    await link_syllabus(repo, me, linked, linear)
    loose = await add_file(repo, me, kind="syllabus", at=T0 + timedelta(hours=1))
    await link_syllabus(repo, me, loose, None)  # 과목을 고르지 않고 뽑았다

    page = await repo.documents(me, limit=20, after=None)
    courses = {item.file_id: item.course for item in page.items}
    assert courses[linked] is not None
    assert (courses[linked].id, courses[linked].short_name) == (linear, "선형대수")
    assert courses[loose] is None


async def test_a_later_extraction_without_a_course_keeps_the_course(world: Any) -> None:
    """같은 계획서를 과목 없이 한 번 더 뽑으면 과목 없는 계획서 행이 하나 더 생긴다. 과목은 그대로 보인다."""
    repo, me, _ = world
    linear = await course(repo, me, "202620HY23525_선형대수")
    syllabus = await add_file(repo, me, kind="syllabus")
    await link_syllabus(repo, me, syllabus, linear)
    await repo.conn.execute(
        "insert into syllabi (user_id, lms_course_id, file_id, created_at)"
        " values (%s, null, %s, now() + interval '1 hour')",
        (me, syllabus),
    )
    page = await repo.documents(me, limit=20, after=None)
    assert page.items[0].course is not None and page.items[0].course.id == linear


async def test_a_dropped_course_keeps_its_name_but_says_it_is_not_open(world: Any) -> None:
    """지난 학기·수강을 뺀 과목은 동기화가 `is_active`를 내린다. 묶음은 그대로 두고 과목 화면 링크만 숨긴다."""
    repo, me, _ = world
    dropped = await course(repo, me, "202610HY11111_자료구조")
    await repo.conn.execute("update lms_courses set is_active = false where id = %s", (dropped,))
    unknown = await course(repo, me, "202620HY22222_운영체제")
    await repo.conn.execute("update lms_courses set is_active = null where id = %s", (unknown,))
    old = await add_file(repo, me, origin="lms_attachment", course_id=dropped)
    now = await add_file(
        repo, me, origin="lms_attachment", course_id=unknown, at=T0 + timedelta(hours=1)
    )
    page = await repo.documents(me, limit=20, after=None)
    courses = {item.file_id: item.course for item in page.items}
    assert courses[old] is not None and (courses[old].short_name, courses[old].is_active) == (
        "자료구조",
        False,
    )
    assert (
        courses[now] is not None and courses[now].is_active is True
    )  # 값이 없으면 수강 중으로 본다


async def test_two_syllabus_rows_at_the_same_time_pick_the_same_course_every_time(
    world: Any,
) -> None:
    """같은 시각이면 계획서 행 번호가 큰 쪽이다. 정해 두지 않으면 부를 때마다 과목이 바뀔 수 있다."""
    repo, me, _ = world
    first = await course(repo, me, "202620HY23525_선형대수")
    second = await course(repo, me, "202620HY23534_기계학습")
    syllabus = await add_file(repo, me, kind="syllabus")
    for row_id, course_id in (
        ("00000000-0000-4000-8000-000000000001", first),
        ("ffffffff-ffff-4fff-bfff-ffffffffffff", second),
    ):
        await repo.conn.execute(
            "insert into syllabi (id, user_id, lms_course_id, file_id, created_at)"
            " values (%s, %s, %s, %s, %s)",
            (row_id, me, course_id, syllabus, T0),
        )
    page = await repo.documents(me, limit=20, after=None)
    assert page.items[0].course is not None and page.items[0].course.id == second


async def test_someone_elses_course_row_is_not_shown_as_mine(world: Any) -> None:
    repo, me, other = world
    theirs = await course(repo, other)
    attached = await add_file(repo, me, origin="lms_attachment", course_id=theirs)
    syllabus = await add_file(repo, me, kind="syllabus", at=T0 - timedelta(hours=1))
    await link_syllabus(repo, me, syllabus, theirs)
    page = await repo.documents(me, limit=20, after=None)
    assert [item.file_id for item in page.items] == [attached, syllabus]
    assert all(item.course is None for item in page.items)


async def test_pages_follow_the_cursor_without_gaps_or_repeats(world: Any) -> None:
    repo, me, _ = world
    for hours in (5, 4, 4, 3, 1):  # 4시는 둘이다 — id로 가른다
        await add_file(repo, me, at=T0 + timedelta(hours=hours))
    expected = await all_ids(repo, me)
    assert len(expected) == 5

    seen: list[str] = []
    after = None
    for size in (2, 2, 2):
        page = await repo.documents(me, limit=size, after=after)
        seen += [item.file_id for item in page.items]
        if page.next_cursor is None:
            break
        after = decode_cursor(page.next_cursor)
        assert after.scope == DOCUMENTS_SCOPE
    assert seen == expected
    assert page.next_cursor is None and len(page.items) == 1


async def test_exactly_a_full_page_has_no_next_cursor(world: Any) -> None:
    repo, me, _ = world
    for hours in (2, 1):
        await add_file(repo, me, at=T0 + timedelta(hours=hours))
    page = await repo.documents(me, limit=2, after=None)
    assert len(page.items) == 2 and page.next_cursor is None


async def test_a_file_without_a_time_comes_last_and_paging_still_ends(world: Any) -> None:
    """files.created_at에는 not null이 없다. 빈 행이 하나 있어도 목록이 깨지지 않는다."""
    repo, me, _ = world
    timeless = await add_file(repo, me, at=None)
    await repo.conn.execute("update files set created_at = null where id = %s", (timeless,))
    dated = await add_file(repo, me, at=T0)

    assert await all_ids(repo, me) == [dated, timeless]
    first = await repo.documents(me, limit=1, after=None)
    assert first.next_cursor is not None
    second = await repo.documents(me, limit=1, after=decode_cursor(first.next_cursor))
    assert [item.file_id for item in second.items] == [timeless]
    assert second.next_cursor is None
    assert second.items[0].created_at == datetime(1970, 1, 1, tzinfo=UTC)
    assert second.items[0].created_at.utcoffset() == timedelta(hours=9)


async def test_document_gives_only_my_material_or_syllabus(world: Any) -> None:
    repo, me, other = world
    material = await add_file(repo, me, name="강의 1주차.pdf")
    syllabus = await add_file(repo, me, kind="syllabus", name=None)
    attached = await add_file(repo, me, origin="lms_attachment", name="공지 첨부.pdf")
    poster = await add_file(repo, me, kind="poster")
    theirs = await add_file(repo, other)

    assert await repo.document(me, material) == DocumentFile(
        f"{me}/lecture_material/{material}.pdf", "강의 1주차.pdf", "upload"
    )
    assert await repo.document(me, syllabus) == DocumentFile(
        f"{me}/syllabus/{syllabus}.pdf", None, "upload"
    )
    assert await repo.document(me, attached) == DocumentFile(
        f"{me}/lecture_material/{attached}.pdf", "공지 첨부.pdf", "lms_attachment"
    )
    assert await repo.document(me, poster) is None  # 포스터는 문서함에 없다
    assert await repo.document(me, theirs) is None
    assert await repo.document(other, theirs) is not None
    assert await repo.document(me, str(uuid4())) is None
