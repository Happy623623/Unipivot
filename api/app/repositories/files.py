"""업로드 파일 SQL (F-13, ERD files).

사용자 것만 읽고 쓴다. 같은 사용자가 같은 파일(sha256)을 같은 kind로 올리면 한 행이다
(ERD v0.9의 부분 유니크 files_user_upload_sha_uq, origin = 'upload'에만 걸린다). LMS 첨부 자동
수집은 (user_id, external_ref) 유니크가 맡으므로 이 저장소는 origin = 'upload'만 본다.

라우터에는 저장소가 아니라 **공급자**를 준다. 파일을 Supabase Storage에 올리는 동안 요청 풀의
연결을 쥐고 있으면, 저장소가 느리거나 멈췄을 때 열 개뿐인 연결이 모두 묶여 다른 화면까지 멈춘다.
필요할 때 빌렸다 블록이 끝나면 돌려준다(app/agent_log.py의 로그 연결과 같은 방식).
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.db import get_conn
from app.errors import ApiError


@dataclass(frozen=True)
class StoredFile:
    id: str
    kind: str
    page_count: int | None


_SELECT = "select id::text as id, kind::text as kind, page_count from files"


class FileRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def existing(self, user_id: str, *, kind: str, sha256: str) -> StoredFile | None:
        """같은 파일을 이미 올렸으면 그 행. 아니면 None이다."""
        row = await (
            await self.conn.execute(
                _SELECT + " where user_id = %s and kind::text = %s and sha256 = %s"
                " and origin = 'upload'",
                (user_id, kind, sha256),
            )
        ).fetchone()
        return None if row is None else StoredFile(row["id"], row["kind"], row["page_count"])

    async def storage_paths(self, user_id: str) -> list[str]:
        """이 사용자가 올린 파일이 저장소에 있는 경로 전부(탈퇴 때 지운다)."""
        rows = await (
            await self.conn.execute(
                "select storage_path from files where user_id = %s order by created_at, storage_path",
                (user_id,),
            )
        ).fetchall()
        return [row["storage_path"] for row in rows]

    async def uploads_since(self, user_id: str, since: datetime) -> int:
        """하루 한도를 세는 값. 올려서 저장한 것만 센다(이미 있던 파일을 다시 올린 것은 안 센다)."""
        row = await (
            await self.conn.execute(
                "select count(*) as used from files"
                " where user_id = %s and origin = 'upload' and created_at >= %s",
                (user_id, since),
            )
        ).fetchone()
        assert row is not None
        return int(row["used"])

    async def add(
        self,
        user_id: str,
        *,
        file_id: str,
        kind: str,
        path: str,
        mime_type: str,
        size_bytes: int,
        page_count: int | None,
        sha256: str,
        original_name: str | None,
    ) -> str | None:
        """기록을 남긴다. 그새 같은 파일이 들어왔으면 None이다(부른 쪽이 기존 행을 돌려준다).

        id를 우리가 정해서 넣는다. 저장소 경로에 그 id가 들어가므로, 먼저 정해야 올릴 수 있다.
        """
        row = await (
            await self.conn.execute(
                "insert into files (id, user_id, kind, origin, storage_path, mime_type,"
                " size_bytes, page_count, sha256, original_name)"
                " values (%(id)s, %(uid)s, %(kind)s, 'upload', %(path)s, %(mime)s, %(size)s,"
                " %(pages)s, %(sha)s, %(name)s)"
                " on conflict (user_id, kind, sha256) where origin = 'upload' do nothing"
                " returning id::text as id",
                {
                    "id": file_id,
                    "uid": user_id,
                    "kind": kind,
                    "path": path,
                    "mime": mime_type,
                    "size": size_bytes,
                    "pages": page_count,
                    "sha": sha256,
                    "name": original_name,
                },
            )
        ).fetchone()
        return None if row is None else row["id"]


# 한 번 부를 때마다 연결을 빌려 저장소를 만들고, 블록이 끝나면 커밋하고 돌려준다
FileRepos = Callable[[], AbstractAsyncContextManager[FileRepository]]


def get_file_repos(request: Request) -> FileRepos:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")

    @asynccontextmanager
    async def connect() -> AsyncIterator[FileRepository]:
        async with pool.connection() as conn:  # 블록이 끝나면 커밋, 예외면 롤백
            yield FileRepository(conn)

    return connect


FileReposDep = Annotated[FileRepos, Depends(get_file_repos)]


def get_file_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> FileRepository:
    """요청 트랜잭션 안에서 쓰는 저장소(탈퇴처럼 다른 삭제와 한 트랜잭션이어야 할 때)."""
    return FileRepository(conn)


FileRepoDep = Annotated[FileRepository, Depends(get_file_repo)]
