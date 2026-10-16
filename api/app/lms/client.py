"""LearningX(Canvas) API 클라이언트 (F-50, API 명세 9장).

지키는 것(명세 9장·PRD 7장):
- **GET만 보낸다.** 다른 방법은 요청을 만들기 전에 예외다
- **허용 경로만 부른다.** 2026-09-28 점검과 10-16 녹화에서 쓴 경로뿐이고, 그 밖은 예외다
- 쪽이 나뉘면 `Link: rel="next"`를 따라가되 **우리 주소와 허용 경로인 쪽만** 따라간다
  (서버가 준 주소를 그대로 믿으면 엉뚱한 곳에 토큰을 보낼 수 있다)
- 토큰은 예외 문구·로그에 넣지 않는다. 호출하는 쪽도 토큰을 입력으로 기록하지 않는다

- 다음 쪽 주소는 **우리와 같은 스킴·호스트·허용 경로**일 때만 따라간다. `https`를 `http`로 바꿔 주면
  평문으로 토큰을 보내게 되므로 스킴도 고정한다
- 리다이렉트는 따라가지 않는다(`follow_redirects=False`). 3xx도 오류로 본다
- 목록을 끝까지 읽지 못하면(쪽 상한·시간 예산) 받은 것을 돌려주지 않고 예외다. 부분 목록을 "전체"로
  잘못 쓰면 수강 과목을 지우는 일이 생긴다(F-50 연결의 과목 내리기)

녹화에서 확인한 것(2026-10-16): 수강 과목 응답은 8과목이 한 쪽에 들어왔고(per_page=100), 과제·모듈·공지는
6과목에서 받았다. `include[]=items`로 모듈 항목이 함께 왔다(항목이 없는 주차는 `items: []`).
함께 오지 않는 과목이 있을 수 있어 항목만 따로 받는 경로도 둔다.
"""

import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20.0  # httpx는 연결·읽기·쓰기에 각각 걸린다
BUDGET_SECONDS = 60.0  # 한 목록을 끝까지 받는 데 쓸 수 있는 전체 시간
PER_PAGE = 100
MAX_PAGES = 10  # 한 쪽에 100건이라 1,000건까지. 넘으면 끝까지 못 읽은 것으로 본다

# 허용 경로. 쿼리는 뺀 경로만 본다(명세 9장 "허용 경로 밖이면 요청을 보내기 전에 예외")
ALLOWED_PATHS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/v1/users/self$"),
    re.compile(r"^/api/v1/courses$"),
    re.compile(r"^/api/v1/courses/\d+/assignments$"),
    re.compile(r"^/api/v1/courses/\d+/modules$"),
    re.compile(r"^/api/v1/courses/\d+/modules/\d+/items$"),
    re.compile(r"^/api/v1/courses/\d+/discussion_topics$"),
)


class LearningXError(Exception):
    """LearningX가 거절했거나 닿지 못했다. status가 401이면 토큰을 다시 받아야 한다."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def unauthorized(self) -> bool:
        return self.status == 401

    @property
    def forbidden(self) -> bool:
        """학교가 그 경로를 닫았다. 토큰 문제와 구분해 기능 범위를 줄인다."""
        return self.status == 403


def allowed(path: str) -> bool:
    return any(pattern.match(path) for pattern in ALLOWED_PATHS)


def next_link(header: str) -> str | None:
    """`Link` 헤더의 rel="next" 주소. 없으면 None이다."""
    for part in header.split(","):
        pieces = part.split(";")
        # rel은 두 번째가 아닐 수 있다(`<url>; type="application/json"; rel="next"`)
        if any('rel="next"' in piece.replace(" ", "") for piece in pieces[1:]):
            return pieces[0].strip().strip("<>")
    return None


class LearningXClient:
    def __init__(self, *, api_base: str, timeout: float = TIMEOUT_SECONDS) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        base = urlsplit(self.api_base)
        self._scheme = base.scheme or "https"
        self._host = base.netloc.lower()

    async def me(self, token: str) -> dict[str, Any]:
        """토큰 확인 (명세 9장: 저장 전에 이 경로로 확인한다)."""
        body = await self._get(token, "/api/v1/users/self")
        if not isinstance(body, dict):
            raise LearningXError("LearningX 응답을 읽지 못했어요.")
        return body

    async def courses(self, token: str) -> list[dict[str, Any]]:
        """수강 중인 과목. 학기 정보를 함께 받는다."""
        return await self._list(
            token, "/api/v1/courses", {"enrollment_state": "active", "include[]": "term"}
        )

    async def assignments(self, token: str, course_id: int) -> list[dict[str, Any]]:
        """과목 과제와 내 제출 상태(F-51)."""
        return await self._list(
            token, f"/api/v1/courses/{course_id}/assignments", {"include[]": "submission"}
        )

    async def modules(self, token: str, course_id: int) -> list[dict[str, Any]]:
        """주차 모듈과 그 안의 항목(F-52)."""
        return await self._list(
            token, f"/api/v1/courses/{course_id}/modules", {"include[]": "items"}
        )

    async def module_items(
        self, token: str, course_id: int, module_id: int
    ) -> list[dict[str, Any]]:
        """항목이 모듈과 함께 오지 않은 과목에서만 쓴다."""
        return await self._list(token, f"/api/v1/courses/{course_id}/modules/{module_id}/items")

    async def announcements(self, token: str, course_id: int) -> list[dict[str, Any]]:
        """과목 공지(F-53)."""
        return await self._list(
            token,
            f"/api/v1/courses/{course_id}/discussion_topics",
            {"only_announcements": "true"},
        )

    # ── 안쪽 ────────────────────────────────────────────────────────────────

    async def _list(
        self, token: str, path: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """목록 경로. 쪽이 나뉘면 끝까지 모은다."""
        url = self._url(path, {**(params or {}), "per_page": str(PER_PAGE)})
        items: list[dict[str, Any]] = []
        until = time.monotonic() + BUDGET_SECONDS
        for _ in range(MAX_PAGES):
            body, link = await self._fetch(token, url)
            if not isinstance(body, list):
                raise LearningXError("LearningX 응답을 읽지 못했어요.")
            items.extend(row for row in body if isinstance(row, dict))
            following = next_link(link)
            if not following or not self._ours(following):
                return items
            if time.monotonic() > until:
                raise LearningXError(f"LearningX 목록을 끝까지 받지 못했어요: {path}")
            url = following
        raise LearningXError(f"LearningX 목록이 너무 길어 끝까지 받지 못했어요: {path}")

    async def _get(self, token: str, path: str) -> Any:
        body, _ = await self._fetch(token, self._url(path, {}))
        return body

    def _url(self, path: str, params: dict[str, str]) -> str:
        if not allowed(path):
            raise LearningXError(f"허용하지 않은 LearningX 경로예요: {path}")
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"{self.api_base}{path}{'?' + query if query else ''}"

    def _ours(self, url: str) -> bool:
        """다음 쪽 주소가 우리 LearningX의 허용 경로인지. 아니면 따라가지 않는다."""
        parts = urlsplit(url)
        # 스킴까지 같아야 한다. https를 http로 바꿔 주면 토큰이 평문으로 나간다
        return (
            parts.scheme == self._scheme
            and parts.netloc.lower() == self._host
            and allowed(parts.path)
        )

    async def _fetch(self, token: str, url: str) -> tuple[Any, str]:
        """GET 한 번. 토큰은 헤더로만 보내고 예외 문구에는 넣지 않는다."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
                )
        except httpx.HTTPError as exc:
            raise LearningXError("LearningX에 연결하지 못했어요.") from exc
        # 3xx도 오류다. 리다이렉트를 따라가면 그 주소로 토큰을 보내게 된다
        if not 200 <= response.status_code < 300:
            raise LearningXError(
                f"LearningX가 요청을 거절했어요({response.status_code}).", response.status_code
            )
        try:
            return response.json(), response.headers.get("Link", "")
        except ValueError as exc:
            raise LearningXError("LearningX 응답을 읽지 못했어요.") from exc
