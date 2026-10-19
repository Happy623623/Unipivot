"""파일 업로드·문서함 응답 (API 명세 6장)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class FileUploadResult(BaseModel):
    """새로 저장하면 201, 같은 파일이 이미 있으면 200이다.

    200이면 `reused`가 true이고 `duplicate_of`는 돌려주는 `file_id`와 같다. 201이면 reused는
    false이고 duplicate_of는 null이다.
    """

    file_id: UUID
    kind: str
    page_count: int | None = None
    duplicate_of: UUID | None = None
    reused: bool = False


MyFileKind = Literal["lecture_material", "syllabus"]
MyFileOrigin = Literal["upload", "lms_attachment"]


class MyFileCourse(BaseModel):
    id: str
    short_name: str
    is_active: (
        bool  # 수강을 뺀(지난 학기) 과목은 false다. 과목 화면이 열리지 않아 화면은 링크를 숨긴다
    )


class MyFile(BaseModel):
    """문서함(F-44)의 파일 하나. 과목을 모르면 `course`가 null이다."""

    file_id: str
    file_name: str
    kind: MyFileKind
    origin: MyFileOrigin  # lms_attachment면 동기화가 공지 첨부를 받은 것(F-54)
    course: MyFileCourse | None
    size_bytes: int | None
    created_at: datetime


class MyFileList(BaseModel):
    items: list[MyFile]
    next_cursor: str | None


class FileDownloadUrl(BaseModel):
    """5분 동안 열리는 받기 주소. 열면 원래 이름으로 내려받는다(F-44)."""

    url: str
    expires_at: datetime
