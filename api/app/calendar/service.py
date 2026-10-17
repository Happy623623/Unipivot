"""캘린더 등록·취소 (F-32). 토큰을 꺼내 쓰고, 만료가 가까우면 갱신한 뒤 Google을 부른다.

연결이 없거나 갱신하지 못하면 409 CALENDAR_NOT_CONNECTED(details.reason)로 끝낸다. 화면은 그 코드를 보고
Google 연결(증분 승인)로 보낸다. Google이 거절하거나 닿지 못하면 502 GOOGLE_API_ERROR다.
토큰 값은 오류 문구·로그에 넣지 않는다.
"""

from datetime import datetime
from typing import Annotated

from fastapi import Depends

from app.calendar.google import GoogleCalendarClient, GoogleCalendarError
from app.config import Settings, get_settings
from app.crypto import decrypt, encrypt
from app.errors import ApiError
from app.repositories.calendar import CalendarRepoDep, CalendarRepository, GoogleTokens

NOT_CONNECTED = "Google 캘린더를 연결해 주세요."
EXPIRED = "캘린더 권한이 만료됐어요. 다시 연결해 주세요."


def _not_connected(reason: str) -> ApiError:
    return ApiError(
        409,
        "CALENDAR_NOT_CONNECTED",
        NOT_CONNECTED if reason == "not_connected" else EXPIRED,
        {"reason": reason},
    )


def _api_error(exc: GoogleCalendarError) -> ApiError:
    """권한 문제면 다시 연결하게 하고, 그 밖은 외부 서비스 오류다."""
    if exc.unauthorized:
        return _not_connected("expired")
    return ApiError(
        502, "GOOGLE_API_ERROR", "Google 캘린더가 응답하지 않아요. 잠시 후 다시 시도해 주세요."
    )


class CalendarService:
    def __init__(
        self, repo: CalendarRepository, client: GoogleCalendarClient, encryption_key: str
    ) -> None:
        self.repo = repo
        self.client = client
        self.key = encryption_key

    async def access_token(self, user_id: str, now: datetime) -> str:
        """쓸 수 있는 access token. 만료가 가까우면 갱신해 저장한다."""
        tokens = await self.repo.tokens(user_id)
        if tokens is None or not tokens.refresh_token:
            raise _not_connected("not_connected")
        if not tokens.expired(now):
            assert tokens.access_token is not None
            return self._decrypt(tokens.access_token)
        return await self._refresh(user_id, tokens)

    def _decrypt(self, value: str) -> str:
        """키를 바꿨거나 값이 깨졌으면 다시 연결하게 한다(500으로 끝내지 않는다)."""
        try:
            return decrypt(value, self.key)
        except Exception as exc:
            raise _not_connected("expired") from exc

    async def _refresh(self, user_id: str, tokens: GoogleTokens) -> str:
        assert tokens.refresh_token is not None
        # 앱 정보(.env의 client_id·secret)가 없으면 client.refresh가 401로 끝난다 → 다시 연결
        try:
            token, expires_in = await self.client.refresh(self._decrypt(tokens.refresh_token))
        except GoogleCalendarError as exc:
            raise _api_error(exc) from exc
        await self.repo.save_access_token(user_id, encrypt(token, self.key), expires_in)
        return token

    async def insert(self, token: str, *, event_id: str, title: str, ends_at: datetime) -> str:
        try:
            event = await self.client.insert(token, event_id=event_id, title=title, ends_at=ends_at)
        except GoogleCalendarError as exc:
            raise _api_error(exc) from exc
        return event.id

    async def move(self, token: str, *, event_id: str, title: str, ends_at: datetime) -> str | None:
        """이미 넣은 일정의 시각을 고친다. 일정이 사라졌으면(404·410) None이고, 부른 쪽이 다시 넣는다."""
        try:
            event = await self.client.move(token, event_id=event_id, title=title, ends_at=ends_at)
        except GoogleCalendarError as exc:
            if exc.status in (404, 410):
                return None
            raise _api_error(exc) from exc
        return event.id

    async def delete(self, token: str, external_event_id: str | None) -> None:
        if not external_event_id:  # 기록만 있고 Google에는 없다(ics 등)
            return
        try:
            await self.client.delete(token, external_event_id)
        except GoogleCalendarError as exc:
            raise _api_error(exc) from exc


def get_calendar_service(
    repo: CalendarRepoDep, settings: Annotated[Settings, Depends(get_settings)]
) -> CalendarService:
    client = GoogleCalendarClient(
        api_base=settings.google_calendar_api_base,
        token_url=settings.google_token_url,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
    )
    return CalendarService(repo, client, settings.token_encryption_key)


CalendarServiceDep = Annotated[CalendarService, Depends(get_calendar_service)]
