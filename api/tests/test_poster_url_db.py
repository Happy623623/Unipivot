"""포스터 원본(W6) SQL을 실제 스키마에 대고 확인한다: 상세의 `poster_kind`와 원본 파일 찾기가 같은 조건이다.

내가 올린 포스터 공고에 붙은 내 파일만 이름이 붙는다. 트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

from typing import Any
from uuid import uuid4

import psycopg
import pytest

from app.repositories.files import FileRepository, PosterOriginalFile
from app.repositories.opportunities import OpportunityRepository
from tests.db_world import DATABASE_URL, World, build, connect

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def conn() -> Any:
    connection = await connect()
    try:
        yield connection
    finally:
        await connection.rollback()
        await connection.close()


async def poster_file(
    conn: psycopg.AsyncConnection, user: str, *, mime: str = "image/png", kind: str = "poster"
) -> tuple[str, str]:
    """올린 포스터 파일 하나. (id, 저장소 경로)다."""
    file_id = str(uuid4())
    path = f"{user}/{kind}/{file_id}.png"
    await conn.execute(
        "insert into files (id, user_id, kind, origin, storage_path, mime_type, sha256)"
        " values (%s, %s, %s, 'upload', %s, %s, %s)",
        (file_id, user, kind, path, mime, uuid4().hex * 2),
    )
    return file_id, path


async def attach(conn: psycopg.AsyncConnection, opportunity_id: str, file_id: str) -> None:
    await conn.execute(
        "update opportunities set poster_file_id = %s where id = %s", (file_id, opportunity_id)
    )


async def kind_and_file(
    world: World, user: str, title: str
) -> tuple[str | None, PosterOriginalFile | None]:
    """상세의 poster_kind와 원본 파일 찾기를 함께 본다. 둘은 언제나 같이 있거나 같이 없어야 한다."""
    opportunity_id = world.ids[title]
    detail = await OpportunityRepository(world.conn).detail(user, opportunity_id, now=world.now)
    found = await FileRepository(world.conn).poster(user, opportunity_id)
    return (detail.poster_kind if detail else None), found


async def test_my_poster_names_its_format_and_where_it_is(conn: psycopg.AsyncConnection) -> None:
    world, me, other = await build(conn)
    file_id, path = await poster_file(conn, me)
    await attach(conn, world.ids["내 포스터 I"], file_id)
    assert await kind_and_file(world, me, "내 포스터 I") == (
        "image",
        PosterOriginalFile(path, "image"),
    )

    # 다른 사람은 내 포스터 원본을 받지 못한다(남이 올린 포스터의 원본은 공유 P1에서 정한다)
    assert await FileRepository(conn).poster(other, world.ids["내 포스터 I"]) is None
    # 남이 올린 포스터는 그 사람 파일이 붙어 있어도 내게 없다(상세도 열리지 않는다)
    their_file, _ = await poster_file(conn, other)
    await attach(conn, world.ids["남의 포스터 H"], their_file)
    assert await kind_and_file(world, me, "남의 포스터 H") == (None, None)
    # 없는 공고도 없다
    assert await FileRepository(conn).poster(me, str(uuid4())) is None


@pytest.mark.parametrize(
    ("mime", "kind"),
    [
        ("application/pdf", "pdf"),
        ("image/jpeg", "image"),
        ("image/webp", "image"),
        ("image/heic", None),  # 올릴 때 받지 않는 형식이다. 이름을 모르면 원문 보기를 숨긴다
        (None, None),
    ],
    ids=["pdf", "jpeg", "webp", "heic", "no-mime"],
)
async def test_only_formats_the_upload_checks_get_a_name(
    conn: psycopg.AsyncConnection, mime: str | None, kind: str | None
) -> None:
    world, me, _ = await build(conn)
    file_id, path = await poster_file(conn, me, mime=mime)  # type: ignore[arg-type]
    await attach(conn, world.ids["내 포스터 I"], file_id)
    expected = PosterOriginalFile(path, kind) if kind else None
    assert await kind_and_file(world, me, "내 포스터 I") == (kind, expected)


async def test_a_file_that_is_not_my_poster_is_never_named(conn: psycopg.AsyncConnection) -> None:
    """포스터가 아닌 공고에 파일이 붙어 있거나, 내 포스터 공고에 남의 파일·포스터가 아닌 파일이 붙은 때."""
    world, me, other = await build(conn)
    mine, _ = await poster_file(conn, me)
    await attach(conn, world.ids["장학 A"], mine)  # 학교 공지에 붙은 포스터 파일
    # 올린 사람이 나로 적혀 있어도 포스터 공고가 아니면 원본이 없다
    await conn.execute(
        "update opportunities set uploaded_by = %s where id = %s", (me, world.ids["장학 A"])
    )
    assert await kind_and_file(world, me, "장학 A") == (None, None)

    their_file, _ = await poster_file(conn, other)
    await attach(conn, world.ids["내 포스터 I"], their_file)
    assert await kind_and_file(world, me, "내 포스터 I") == (None, None)

    # 남이 올린 포스터 공고에 내 파일이 붙어 있어도 내 원본이 아니다
    await attach(conn, world.ids["남의 포스터 H"], mine)
    assert await FileRepository(conn).poster(me, world.ids["남의 포스터 H"]) is None

    syllabus, _ = await poster_file(conn, me, mime="application/pdf", kind="syllabus")
    await attach(conn, world.ids["내 포스터 I"], syllabus)
    assert await kind_and_file(world, me, "내 포스터 I") == (None, None)

    # 원본을 붙이지 않은(예전에 만든) 포스터 공고도 없다
    await conn.execute(
        "update opportunities set poster_file_id = null where id = %s", (world.ids["내 포스터 I"],)
    )
    assert await kind_and_file(world, me, "내 포스터 I") == (None, None)


async def test_a_deleted_file_leaves_the_poster_without_an_original(
    conn: psycopg.AsyncConnection,
) -> None:
    """파일 행을 지우면(탈퇴 등) 공고의 poster_file_id가 비고 원본도 없다(ERD on delete set null)."""
    world, me, _ = await build(conn)
    file_id, _ = await poster_file(conn, me)
    await attach(conn, world.ids["내 포스터 I"], file_id)
    await conn.execute("delete from files where id = %s", (file_id,))
    assert await kind_and_file(world, me, "내 포스터 I") == (None, None)
