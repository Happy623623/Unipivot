"""포스터로 공고 등록 (F-16, API 명세 6장).

이번에는 추출까지다. 확인 화면에서 고친 값으로 공고를 만드는 POST /posters/confirm은 다음이다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.config import Settings, get_settings
from app.eligibility import KST
from app.errors import ApiError
from app.posters.service import PosterServiceDep
from app.schemas.posters import PosterExtractRequest, PosterExtractStarted

router = APIRouter(prefix="/posters", tags=["포스터"])


@router.post("/extract", status_code=202, response_model=PosterExtractStarted)
async def extract_poster(
    body: PosterExtractRequest,
    user: CurrentUserDep,
    service: PosterServiceDep,
    now: NowDep,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PosterExtractStarted:
    """올린 포스터에서 공고 초안을 뽑는다. 진행과 결과는 `GET /runs/{run_id}`로 본다."""
    file = await service.file(user.id, str(body.file_id))
    if file is None:
        raise ApiError(404, "NOT_FOUND", "올린 포스터를 찾을 수 없어요. 다시 올려 주세요.")
    run_id = await service.begin(user.id, file, now=now, today=now.astimezone(KST).date())
    response.headers["Location"] = f"{settings.api_prefix}/runs/{run_id}"
    return PosterExtractStarted(run_id=run_id, status="running")
