"""파일 업로드 응답 (API 명세 6장)."""

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
