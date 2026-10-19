"""업로드 파일 SQL (F-13, ERD files).

사용자 것만 읽고 쓴다. 같은 사용자가 같은 파일(sha256)을 같은 kind로 올리면 한 행이다
(ERD v0.9의 부분 유니크 files_user_upload_sha_uq, origin = 'upload'에만 걸린다). LMS 첨부 자동
수집은 (user_id, external_ref) 유니크가 맡으므로 같은 파일 찾기는 origin = 'upload'만 본다. 문서함(F-44)
목록과 받기는 두 출처(직접 올림·공지 첨부)를 다 본다.

라우터에는 저장소가 아니라 **공급자**를 준다. 파일을 Supabase Storage에 올리는 동안 요청 풀의
연결을 쥐고 있으면, 저장소가 느리거나 멈췄을 때 열 개뿐인 연결이 모두 묶여 다른 화면까지 멈춘다.
필요할 때 빌렸다 블록이 끝나면 돌려준다(app/agent_log.py의 로그 연결과 같은 방식).
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.db import get_conn
from app.eligibility.dates import KST
from app.errors import ApiError
from app.lms.parse import course_name
from app.repositories.opportunities import Cursor, encode_cursor
from app.schemas.files import MyFile, MyFileCourse, MyFileList
from app.uploads import document_name

DOCUMENT_KINDS = ("lecture_material", "syllabus")  # 문서함 종류(F-44). 포스터는 공고 쪽에 있다
DOCUMENTS_SCOPE = "documents"  # 문서함 목록 cursor의 범위 이름


@dataclass(frozen=True)
class StoredFile:
    id: str
    kind: str
    page_count: int | None


@dataclass(frozen=True)
class DocumentFile:
    """받기 주소를 만들 내 파일(F-44). 출처는 저장소에서 없어졌을 때 안내 문구를 고르는 데 쓴다."""

    storage_path: str
    original_name: str | None
    origin: str  # upload · lms_attachment


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

    # ── 공지 첨부 자동 저장 (F-54) ─────────────────────────────────────────────

    async def lms_attachment_refs(self, user_id: str, refs: list[str]) -> set[str]:
        """이 중 이미 저장한 공지 첨부(Canvas 첨부 번호)."""
        if not refs:
            return set()
        rows = await (
            await self.conn.execute(
                "select external_ref from files where user_id = %s"
                " and origin = 'lms_attachment' and external_ref = any(%s)",
                (user_id, refs),
            )
        ).fetchall()
        return {row["external_ref"] for row in rows}

    async def add_lms_attachment(
        self,
        user_id: str,
        *,
        file_id: str,
        course_id: str,
        ref: str,
        path: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        original_name: str,
    ) -> str | None:
        """받은 공지 첨부를 남긴다. 넣지 않았으면 None이다 — 부른 쪽이 올린 것을 지운다.

        넣지 않는 때: 같은 첨부 번호가 이미 있다(유니크), 또는 `course_id`가 **내** 과목 행이 아니다
        (과목 공통 번호가 아니라 `lms_courses.id`다).
        """
        row = await (
            await self.conn.execute(
                "insert into files (id, user_id, lms_course_id, kind, origin, external_ref,"
                " storage_path, mime_type, size_bytes, sha256, original_name)"
                " select %(id)s, %(uid)s, c.id, 'lecture_material', 'lms_attachment', %(ref)s,"
                " %(path)s, %(mime)s, %(size)s, %(sha)s, %(name)s"
                " from lms_courses c where c.id = %(course)s and c.user_id = %(uid)s"
                " on conflict (user_id, external_ref) do nothing"
                " returning id::text as id",
                {
                    "id": file_id,
                    "uid": user_id,
                    "course": course_id,
                    "ref": ref,
                    "path": path,
                    "mime": mime_type,
                    "size": size_bytes,
                    "sha": sha256,
                    "name": original_name,
                },
            )
        ).fetchone()
        return None if row is None else row["id"]

    # ── 문서함 (F-44) ─────────────────────────────────────────────────────────

    async def documents(self, user_id: str, *, limit: int, after: Cursor | None) -> MyFileList:
        """내 강의자료·계획서를 최신순으로. `after`는 앞 쪽의 마지막 파일(cursor)이다."""
        params: dict[str, Any] = {"uid": user_id, "kinds": list(DOCUMENT_KINDS), "limit": limit + 1}
        clause = ""
        if after is not None:
            clause = f" and ({_AT}, f.id) < (%(at)s, %(id)s::uuid)"
            params |= {"at": after.value, "id": after.id}
        rows = await (await self.conn.execute(_DOCUMENTS.format(after=clause), params)).fetchall()
        last = rows[limit - 1] if len(rows) > limit else None
        return MyFileList(
            items=[_document(row) for row in rows[:limit]],
            next_cursor=encode_cursor(
                Cursor(scope=DOCUMENTS_SCOPE, value=last["created_at"], id=last["id"])
            )
            if last
            else None,
        )

    async def document(self, user_id: str, file_id: str) -> DocumentFile | None:
        """받기 주소를 만들 내 파일. 남의 파일·문서함에 없는 종류(포스터)는 None이다."""
        row = await (
            await self.conn.execute(
                "select storage_path, original_name, origin::text as origin from files"
                " where id = %(id)s and user_id = %(uid)s and kind::text = any(%(kinds)s)",
                {"id": file_id, "uid": user_id, "kinds": list(DOCUMENT_KINDS)},
            )
        ).fetchone()
        if row is None:
            return None
        return DocumentFile(row["storage_path"], row["original_name"], row["origin"])


# files.created_at에는 not null이 없다(기본값만 있다). 빈 행이 하나 있어도 목록이 깨지지 않게 맨 뒤로 둔다
_AT = "coalesce(f.created_at, 'epoch'::timestamptz)"
_DOCUMENTS = (
    "select f.id::text as id, f.kind::text as kind, f.origin::text as origin, f.original_name,"
    f" f.size_bytes, {_AT} as created_at, f.storage_path, c.id::text as course_id,"
    " c.name as course_name, coalesce(c.is_active, true) as course_active from files f"
    # 계획서는 과목을 계획서 행이 들고 있다(올릴 때가 아니라 일정을 뽑을 때 과목을 고른다)
    " left join lateral (select s.lms_course_id from syllabi s where s.file_id = f.id"
    "  and s.user_id = f.user_id and s.lms_course_id is not null"
    "  order by s.created_at desc, s.id desc limit 1) s on true"
    " left join lms_courses c on c.id = coalesce(f.lms_course_id, s.lms_course_id)"
    "  and c.user_id = f.user_id"
    " where f.user_id = %(uid)s and f.kind::text = any(%(kinds)s){after}"
    f" order by {_AT} desc, f.id desc limit %(limit)s"
)


def _document(row: dict[str, Any]) -> MyFile:
    course = None
    if row["course_id"] is not None:
        course = MyFileCourse(
            id=row["course_id"],
            short_name=course_name(row["course_name"]).short_name,
            is_active=row["course_active"],
        )
    return MyFile(
        file_id=row["id"],
        file_name=document_name(row["original_name"], row["storage_path"]),
        kind=row["kind"],
        origin=row["origin"],
        course=course,
        size_bytes=row["size_bytes"],
        created_at=row["created_at"].astimezone(KST),
    )


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
