"""파일 업로드 (F-13, API 명세 6장).

포스터(F-16)와 강의계획서(F-14)를 받는다. 강의자료(F-15)는 그 기능과 함께 연다.
받는 것은 종류마다 다르다 — 포스터는 사진과 2쪽 이하 PDF, 계획서는 **글자가 있는 PDF**다.

차례: 20MB까지 읽기 → 바이트로 형식·쪽수 보기 → 같은 파일인지 보기 → 하루 한도 보기 →
저장소에 올리기 → 기록 남기기.

올리기를 기록보다 먼저 한다. 거꾸로 하면 기록을 남긴 뒤 올리다 끊겼을 때, 다음에 같은 파일을 올려도
"이미 있어요"라며 저장소에 없는 파일을 가리킨다. 먼저 올리면 끊겨도 쓰이지 않는 파일만 남는다
(비공개 버킷이라 아무도 보지 못하고, 다시 올리면 제대로 기록된다).

DB 연결은 읽을 때와 쓸 때만 빌린다. 저장소에 올리는 동안 쥐고 있으면 저장소가 느릴 때 요청 풀이
묶여 다른 화면까지 멈춘다. 두 번으로 나눠도 중복은 부분 유니크가 막는다.
"""

import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.errors import ApiError
from app.repositories.files import FileReposDep, StoredFile
from app.schemas.files import FileUploadResult
from app.uploads import (
    DAILY_UPLOAD_LIMIT,
    clean_name,
    day_reset,
    day_start,
    inspect_poster,
    inspect_syllabus,
    read_upload,
    storage_path,
)
from app.uploads.storage import StorageDep, StorageError, SupabaseStorage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["업로드"])

POSTER = "poster"
SYLLABUS = "syllabus"
# 종류마다 받는 파일이 다르다. 여기 없는 종류(lecture_material)는 그 기능과 함께 연다
INSPECT = {POSTER: inspect_poster, SYLLABUS: inspect_syllabus}


@router.post(
    "",
    status_code=201,
    response_model=FileUploadResult,
    responses={200: {"model": FileUploadResult, "description": "이미 올린 파일(reused)"}},
)
async def upload_file(
    user: CurrentUserDep,
    repos: FileReposDep,
    storage: StorageDep,
    now: NowDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()],
) -> FileUploadResult:
    """파일을 저장소에 올리고 `file_id`를 준다. 같은 파일을 다시 올리면 200과 기존 id다."""
    inspect = INSPECT.get(kind)
    if inspect is None:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "입력값을 확인해 주세요.",
            {"fields": {"kind": "지금은 포스터와 강의계획서만 올릴 수 있어요."}},
        )
    data = await read_upload(file)
    found = inspect(data)

    async with repos() as repo:
        existing = await repo.existing(user.id, kind=kind, sha256=found.sha256)
        # 이미 올린 파일은 새로 저장하지 않으므로 하루 한도를 보지 않는다
        used = None if existing else await repo.uploads_since(user.id, day_start(now))
    if existing is not None:
        return _reused(existing, response)
    if used is not None and used >= DAILY_UPLOAD_LIMIT:
        raise ApiError(
            429,
            "DAILY_UPLOAD_LIMIT",
            f"오늘 올릴 수 있는 {DAILY_UPLOAD_LIMIT}개를 다 썼어요. 내일 다시 올려 주세요.",
            {"reset_at": day_reset(now).isoformat()},
        )

    file_id = str(uuid4())
    path = storage_path(user.id, kind, file_id, found.type.extension)
    try:
        await storage.upload(path, data, found.type.mime)
    except StorageError as exc:
        logger.warning("파일 저장소 업로드 실패: %s", exc)
        raise ApiError(
            502, "STORAGE_API_ERROR", "파일을 저장하지 못했어요. 잠시 후 다시 시도해 주세요."
        ) from exc

    async with repos() as repo:
        saved = await repo.add(
            user.id,
            file_id=file_id,
            kind=kind,
            path=path,
            mime_type=found.type.mime,
            size_bytes=len(data),
            page_count=found.page_count,
            sha256=found.sha256,
            original_name=clean_name(file.filename),
        )
        if saved is None:  # 올리는 사이에 같은 파일이 들어왔다. 방금 올린 것은 지운다
            winner = await repo.existing(user.id, kind=kind, sha256=found.sha256)
            assert winner is not None  # 충돌이 났다는 것은 그 행이 있다는 뜻이다
    if saved is None:
        await _discard(storage, path)
        return _reused(winner, response)
    return FileUploadResult(file_id=file_id, kind=kind, page_count=found.page_count)


def _reused(found: StoredFile, response: Response) -> FileUploadResult:
    response.status_code = 200
    return FileUploadResult(
        file_id=found.id,
        kind=found.kind,
        page_count=found.page_count,
        duplicate_of=found.id,
        reused=True,
    )


async def _discard(storage: SupabaseStorage, path: str) -> None:
    """되돌리기용 삭제. 여기서 실패해도 요청은 성공이라 기록만 남긴다."""
    try:
        await storage.remove(path)
    except StorageError as exc:
        logger.warning("쓰이지 않는 업로드 파일을 지우지 못했어요: %s", exc)
