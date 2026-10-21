"""강의자료 요약 (F-15 축소판, API 명세 8장).

학생이 강의자료 PDF를 `POST /files`(kind=lecture_material)로 올린 뒤 `POST /materials`를 부른다. 글자가 상한
(기본 3만 토큰) 안이면 202와 `run_id`로 답하고 뒤에서 문서 전체를 한 번 요약한다. 넘으면 413
`MATERIAL_TOO_LONG`이다(쪽 범위 선택은 없다 — 나눠 올리라고 안내한다). 이미 요약이 있으면 200과 요약이다.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.auth import CurrentUserDep
from app.errors import ApiError
from app.materials.service import MaterialServiceDep
from app.repositories.materials import MATERIALS_SCOPE, MaterialReposDep
from app.repositories.opportunities import decode_cursor
from app.schemas.materials import (
    MaterialDetail,
    MaterialList,
    MaterialStarted,
    MaterialSummarizeRequest,
)

router = APIRouter(prefix="/materials", tags=["강의자료"])
NOT_FOUND = "강의자료를 찾을 수 없어요. 다시 올려 주세요."
LIST_LIMIT = 50  # 한 쪽 상한(명세 1장 목록 규칙: 1–50, 기본 20)


@router.post(
    "",
    status_code=202,
    response_model=MaterialStarted | MaterialDetail,
    responses={200: {"model": MaterialDetail, "description": "이미 요약이 있음(캐시)"}},
)
async def summarize_material(
    body: MaterialSummarizeRequest,
    user: CurrentUserDep,
    repos: MaterialReposDep,
    service: MaterialServiceDep,
    response: Response,
) -> MaterialStarted | MaterialDetail:
    """내 강의자료를 요약한다. 요약 중이면 그 실행의 run_id로 202, 요약이 있으면 200이다."""
    async with repos() as repo:
        material = await repo.material(user.id, str(body.file_id))
    if material is None:
        raise ApiError(404, "NOT_FOUND", NOT_FOUND)
    if material.detail.status == "succeeded":
        response.status_code = 200
        return material.detail
    if material.summarizing and material.detail.run_id is not None:
        return MaterialStarted(run_id=material.detail.run_id)
    job = await service.prepare(user.id, material)
    return MaterialStarted(run_id=await service.begin(job, stopped_run=material.stopped_run))


@router.get("/{file_id}", response_model=MaterialDetail)
async def read_material(
    file_id: UUID, user: CurrentUserDep, repos: MaterialReposDep
) -> MaterialDetail:
    """요약 상태와 요약(Markdown). 아직 요약을 요청하지 않았으면 pending이다."""
    async with repos() as repo:
        material = await repo.material(user.id, str(file_id))
    if material is None:
        raise ApiError(404, "NOT_FOUND", NOT_FOUND)
    return material.detail


@router.get("", response_model=MaterialList)
async def list_materials(
    user: CurrentUserDep,
    repos: MaterialReposDep,
    lms_course_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=LIST_LIMIT)] = 20,
    cursor: Annotated[str | None, Query(description="앞 응답의 next_cursor")] = None,
) -> MaterialList:
    """요약을 요청한 내 강의자료(최신순). 과목을 주면 그 과목만."""
    after = None
    if cursor:
        try:
            after = decode_cursor(cursor)
        except ValueError:
            after = None
        if after is None or after.scope != MATERIALS_SCOPE or after.value is None:
            raise ApiError(
                422,
                "VALIDATION_FAILED",
                "입력값을 확인해 주세요.",
                {"fields": {"cursor": "목록을 처음부터 다시 불러와 주세요."}},
            )
    async with repos() as repo:
        items, next_cursor = await repo.list(
            user.id,
            course_id=str(lms_course_id) if lms_course_id else None,
            limit=limit,
            after=after,
        )
    return MaterialList(items=items, next_cursor=next_cursor)
