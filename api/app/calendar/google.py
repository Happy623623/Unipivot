"""Google Calendar API 클라이언트 (F-32).

- 이벤트 넣기: POST {api_base}/calendars/primary/events
- 이벤트 빼기: DELETE {api_base}/calendars/primary/events/{id}
- access token 갱신: POST {token_url} (refresh_token 교환). 앱의 client_id·client_secret이 있어야 한다.
  비워 두면 갱신하지 못하고 만료로 본다(학생이 다시 연결한다).

마감 이벤트는 마감 시각으로 끝나는 1시간짜리다(10/15 선택). 종일 일정은 기본 알림이 전날이라 당일에
안 울리고, 몇 시 마감인지도 안 보인다. 토큰은 로그·오류 문구에 넣지 않는다.

일정 번호는 우리가 정해서 보낸다(calendar_events.id의 하이픈을 뺀 값). 같은 번호로 다시 넣으면 Google이
409로 거절하는데, 그것은 앞 요청이 이미 넣었다는 뜻이라 성공으로 본다. 응답을 받지 못하고 다시 눌러도
캘린더에 일정이 두 개가 되지 않는다.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
EVENT_MINUTES = 60  # 마감 시각으로 끝나는 1시간짜리
TIMEOUT_SECONDS = 15.0
_KST_NAME = "Asia/Seoul"
# Google이 받는 일정 번호: 소문자 a–v와 숫자, 5–1024자. uuid의 16진수는 그대로 들어간다
_EVENT_ID = re.compile(r"^[a-v0-9]{5,1024}$")


def event_id_for(row_id: str) -> str:
    """calendar_events.id → Google 일정 번호. 같은 행은 늘 같은 번호다(다시 넣어도 하나)."""
    value = row_id.replace("-", "").lower()
    if not _EVENT_ID.match(value):
        raise ValueError(f"Google이 받지 않는 일정 번호예요: {row_id}")
    return value


class GoogleCalendarError(Exception):
    """Google이 거절했거나 닿지 못했다. status가 401이면 다시 연결해야 한다."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def unauthorized(self) -> bool:
        """다시 연결해야 하는 오류. 403은 쿼터·한도에도 오므로 여기 넣지 않는다."""
        return self.status == 401


@dataclass(frozen=True)
class GoogleEvent:
    id: str
    starts_at: datetime
    ends_at: datetime


def event_title(opportunity_title: str) -> str:
    """캘린더에 보이는 제목. 앞에 [마감]을 붙여 다른 일정과 구분한다."""
    return f"[마감] {opportunity_title}"


def assignment_title(course: str, assignment: str) -> str:
    """LMS 과제 일정 제목. 과목을 앞에 둬서 캘린더에서 어느 수업인지 바로 보인다(F-51)."""
    return f"[과제] {course} · {assignment}"


class GoogleCalendarClient:
    def __init__(
        self,
        *,
        api_base: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        revoke_url: str = "https://oauth2.googleapis.com/revoke",
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.token_url = token_url
        self.revoke_url = revoke_url
        self.client_id = client_id
        self.client_secret = client_secret

    @property
    def can_refresh(self) -> bool:
        """앱 정보가 있어야 access token을 갱신할 수 있다."""
        return bool(self.client_id and self.client_secret)

    async def refresh(self, refresh_token: str) -> tuple[str, int]:
        """새 access token과 남은 초. 갱신하지 못하면 GoogleCalendarError(401)다."""
        if not self.can_refresh:
            raise GoogleCalendarError("캘린더 권한을 갱신할 수 없어요.", 401)
        body = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            payload = await self._send("POST", self.token_url, data=body)
        except GoogleCalendarError as exc:
            # 토큰 교환이 4xx면 refresh token이 없어졌거나 학생이 권한을 거뒀다(Google은 400
            # invalid_grant를 준다). 다시 연결해야 한다. 5xx·연결 오류는 잠깐 문제라 그대로 올린다
            if exc.status is not None and 400 <= exc.status < 500:
                raise GoogleCalendarError("캘린더 권한이 만료됐어요.", 401) from exc
            raise
        token = payload.get("access_token")
        if not token:
            raise GoogleCalendarError("캘린더 권한을 갱신하지 못했어요.", 401)
        return str(token), int(payload.get("expires_in") or 3600)

    async def revoke(self, token: str) -> None:
        """권한을 Google 쪽에서도 거둔다(연결 해제, F-06). refresh token을 주면 그 승인 전체가 풀린다.

        이미 풀린 토큰이면 Google이 400을 주는데, 거두려던 것이 거둬진 상태라 성공으로 본다.
        그 밖의 실패는 GoogleCalendarError로 올린다 — 부르는 쪽이 로그만 남기고 저장한 토큰을 지운다.
        """
        try:
            await self._send("POST", self.revoke_url, data={"token": token})
        except GoogleCalendarError as exc:
            if exc.status == 400:
                return
            raise

    async def insert(
        self, access_token: str, *, event_id: str, title: str, ends_at: datetime
    ) -> GoogleEvent:
        """우리가 정한 번호로 넣는다. 이미 그 번호가 있으면(409) 앞 요청이 넣은 것이라 성공으로 본다."""
        starts_at = ends_at - timedelta(minutes=EVENT_MINUTES)
        body = {
            "id": event_id,
            "summary": title,
            "start": {"dateTime": starts_at.isoformat(), "timeZone": _KST_NAME},
            "end": {"dateTime": ends_at.isoformat(), "timeZone": _KST_NAME},
        }
        try:
            await self._send(
                "POST",
                f"{self.api_base}/calendars/primary/events",
                json=body,
                token=access_token,
            )
        except GoogleCalendarError as exc:
            if exc.status != 409:  # 409는 같은 번호가 이미 있다는 뜻이다
                raise
            # 앞 요청이 이미 넣었다. **그때의 시각이 남아 있다** — 그 사이 마감이 바뀌었으면
            # 캘린더가 옛 시각을 가리키므로, 성공으로 보되 시각·제목을 한 번 맞춰 준다
            return await self.move(access_token, event_id=event_id, title=title, ends_at=ends_at)
        return GoogleEvent(event_id, starts_at, ends_at)

    async def move(
        self, access_token: str, *, event_id: str, title: str, ends_at: datetime
    ) -> GoogleEvent:
        """이미 넣은 일정의 시각·제목을 고친다(마감이 바뀐 과제). 일정이 없으면(404·410) 예외다.

        없어진 일정은 부른 쪽이 다시 넣는다 — 여기서 넣어 버리면 학생이 지운 일정이 되살아난다.
        """
        starts_at = ends_at - timedelta(minutes=EVENT_MINUTES)
        body = {
            "summary": title,
            "start": {"dateTime": starts_at.isoformat(), "timeZone": _KST_NAME},
            "end": {"dateTime": ends_at.isoformat(), "timeZone": _KST_NAME},
        }
        await self._send(
            "PATCH",
            f"{self.api_base}/calendars/primary/events/{quote(event_id, safe='')}",
            json=body,
            token=access_token,
        )
        return GoogleEvent(event_id, starts_at, ends_at)

    async def delete(self, access_token: str, event_id: str) -> None:
        """이미 지워진 일정(404·410)은 지운 것으로 본다."""
        await self._send(
            "DELETE",
            f"{self.api_base}/calendars/primary/events/{quote(event_id, safe='')}",
            token=access_token,
            gone_is_ok=True,
        )

    async def _send(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        data: dict | None = None,
        token: str | None = None,
        gone_is_ok: bool = False,
    ) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.request(method, url, json=json, data=data, headers=headers)
        except httpx.HTTPError as exc:
            raise GoogleCalendarError(
                f"Google 캘린더에 닿지 못했어요: {type(exc).__name__}"
            ) from exc
        if gone_is_ok and response.status_code in (404, 410):
            return {}
        if response.status_code >= 400:
            raise GoogleCalendarError(
                f"Google 캘린더가 요청을 거절했어요({response.status_code}).", response.status_code
            )
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleCalendarError("Google 캘린더 응답을 읽지 못했어요.") from exc
        return payload if isinstance(payload, dict) else {}
