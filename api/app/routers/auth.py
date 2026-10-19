from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.auth import CurrentUserDep
from app.calendar.service import CalendarServiceDep
from app.config import Settings, get_settings
from app.crypto import encrypt
from app.errors import ApiError
from app.repositories.profiles import ProfileRepoDep
from app.schemas.me import GoogleTokensRequest, GoogleTokensResponse

router = APIRouter(prefix="/auth", tags=["인증"])


@router.post("/google/tokens", response_model=GoogleTokensResponse)
async def save_google_tokens(
    body: GoogleTokensRequest,
    user: CurrentUserDep,
    repo: ProfileRepoDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> GoogleTokensResponse:
    """캘린더를 처음 연결할 때(증분 승인) 콜백이 한 번 보낸다 (API 4장, F-01). 로그인 때는 부르지 않는다."""
    if not body.provider_refresh_token:
        raise ApiError(
            422,
            "GOOGLE_REFRESH_TOKEN_MISSING",
            "캘린더 권한을 다시 받아야 해요. Google 화면에서 캘린더 접근을 허용해 주세요.",
        )
    await repo.ensure(user.id, user.name)
    await repo.save_google_tokens(
        user.id,
        encrypt(body.provider_token, settings.token_encryption_key),
        encrypt(body.provider_refresh_token, settings.token_encryption_key),
    )
    return GoogleTokensResponse(calendar_connected=True, scope="calendar.events")


@router.delete("/google/tokens", status_code=204, response_class=Response)
async def delete_google_tokens(user: CurrentUserDep, service: CalendarServiceDep) -> Response:
    """캘린더 연결을 해제한다 (API 4장, F-06). Google 쪽 권한을 거두고 저장한 토큰을 지운다.

    연결이 없어도 204다(두 번 눌러도 같다). 이미 넣은 일정은 학생의 캘린더에 그대로 둔다.
    """
    await service.disconnect(user.id)
    return Response(status_code=204)
