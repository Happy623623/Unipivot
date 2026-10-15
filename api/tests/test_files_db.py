"""업로드 파일 SQL(F-13)을 실제 스키마에 대고 확인한다: 중복 막기, 사용자 격리, 하루 세기.

트랜잭션을 되돌려 지운다. DATABASE_URL이 있을 때만 돈다.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.eligibility import KST
from app.errors import ApiError
from app.repositories.files import FileRepository, get_file_repos
from app.uploads import day_start
from tests.db_world import DATABASE_URL, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)  # 2026-10-15 12:00 KST


@pytest.fixture
async def files() -> Any:
    conn = await connect()
    try:
        yield FileRepository(conn), await make_user(conn), await make_user(conn)
    finally:
        await conn.rollback()
        await conn.close()


async def add(repo: FileRepository, user: str, sha: str, **over: Any) -> str | None:
    file_id = str(uuid4())
    fields: dict[str, Any] = {
        "file_id": file_id,
        "kind": "poster",
        "path": f"{user}/poster/{file_id}.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": 1234,
        "page_count": None,
        "sha256": sha,
        "original_name": "포스터.jpg",
    }
    return await repo.add(user, **(fields | over))


async def test_a_stored_file_is_found_again_by_its_hash(files: Any) -> None:
    repo, user, _ = files
    saved = await add(repo, user, "a" * 64, page_count=2)
    assert saved is not None
    found = await repo.existing(user, kind="poster", sha256="a" * 64)
    assert found is not None
    assert (found.id, found.kind, found.page_count) == (saved, "poster", 2)
    assert await repo.existing(user, kind="poster", sha256="b" * 64) is None


async def test_the_same_file_twice_leaves_one_row(files: Any) -> None:
    repo, user, _ = files
    first = await add(repo, user, "c" * 64)
    assert await add(repo, user, "c" * 64) is None  # 부분 유니크가 막는다
    found = await repo.existing(user, kind="poster", sha256="c" * 64)
    assert found is not None and found.id == first


async def test_two_students_can_upload_the_same_file(files: Any) -> None:
    repo, user, other = files
    mine = await add(repo, user, "d" * 64)
    theirs = await add(repo, other, "d" * 64)
    assert mine is not None and theirs is not None and mine != theirs
    found = await repo.existing(other, kind="poster", sha256="d" * 64)
    assert found is not None and found.id == theirs


async def test_another_students_file_is_not_mine(files: Any) -> None:
    repo, user, other = files
    await add(repo, other, "e" * 64)
    assert await repo.existing(user, kind="poster", sha256="e" * 64) is None


async def test_an_lms_attachment_is_not_an_upload(files: Any) -> None:
    """LMS 첨부는 (user_id, external_ref) 유니크가 맡는다. 같은 파일이 여러 과목 첨부로 올 수 있다."""
    repo, user, _ = files
    for ref in ("canvas-1", "canvas-2"):
        await repo.conn.execute(
            "insert into files (user_id, kind, origin, external_ref, storage_path, sha256)"
            " values (%s, 'poster', 'lms_attachment', %s, %s, %s)",
            (user, ref, f"{user}/lms/{ref}.jpg", "f" * 64),
        )
    assert await repo.existing(user, kind="poster", sha256="f" * 64) is None
    assert await repo.uploads_since(user, day_start(NOW)) == 0


async def test_the_daily_count_only_covers_this_kst_day(files: Any) -> None:
    repo, user, other = files
    await add(repo, user, "1" * 64)
    await add(repo, user, "2" * 64)
    await add(repo, other, "3" * 64)  # 남의 업로드는 세지 않는다
    yesterday = await add(repo, user, "4" * 64)
    await repo.conn.execute(
        "update files set created_at = %s where id = %s",
        (day_start(NOW) - timedelta(minutes=1), yesterday),
    )
    assert await repo.uploads_since(user, day_start(NOW)) == 2
    # 하루 경계는 KST 0시다. 그 직후에 올린 것은 오늘 것이다
    edge = await add(repo, user, "5" * 64)
    await repo.conn.execute(
        "update files set created_at = %s where id = %s", (day_start(NOW), edge)
    )
    assert await repo.uploads_since(user, day_start(NOW)) == 3
    assert day_start(NOW).astimezone(KST).hour == 0


async def test_each_borrow_gives_the_connection_back() -> None:
    """공급자는 블록이 끝나면 연결을 풀에 돌려준다. 돌려주지 않으면 두 번째가 영영 기다린다."""
    pool = AsyncConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=1,
        open=False,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
    )
    await pool.open()
    try:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
        repos = get_file_repos(request)  # type: ignore[arg-type]
        for _ in range(3):
            async with asyncio.timeout(5):
                async with repos() as repo:
                    assert await repo.uploads_since(str(uuid4()), day_start(NOW)) == 0
    finally:
        await pool.close()


async def test_without_a_pool_the_answer_is_db_unavailable() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    with pytest.raises(ApiError) as caught:
        get_file_repos(request)  # type: ignore[arg-type]
    assert (caught.value.status, caught.value.code) == (503, "DB_UNAVAILABLE")
