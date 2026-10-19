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

공지 첨부 받기(F-54, 10/19 녹화)는 API가 아니라 웹 경로 `/files/{id}/download`다. 공지 응답의 첨부
`url`에 든 `verifier`가 열쇠라 **토큰을 보내지 않는다**(토큰만으로는 로그인 화면으로 302). 그 주소는
파일 저장소(네이버 클라우드)의 서명 주소로 302를 주고, 거기서 파일이 온다. 그래서 첨부만은 리다이렉트를
따라가되 `https`로만, 세 번까지만 가고, 우리 LearningX의 다른 경로(로그인 화면)로 보내면 실패로 본다.
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

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


# 공지 첨부 받기(F-54). API 경로가 아니어서 ALLOWED_PATHS와 따로 둔다
ALLOWED_DOWNLOADS: tuple[re.Pattern[str], ...] = (re.compile(r"^/files/\d+/download$"),)
MAX_REDIRECTS = 3  # 녹화에서는 한 번(LearningX → 파일 저장소)이었다
DOWNLOAD_BUDGET_SECONDS = 120.0  # 20MB 하나를 받는 데 쓸 수 있는 전체 시간


class AttachmentUnavailable(Exception):
    """공지 첨부를 받지 못했다. **토큰 문제가 아니다** — 연결 상태를 바꾸지 않고 다음 동기화에 다시 본다.

    문구에 주소를 넣지 않는다(verifier·서명이 들어 있다).
    """


class AttachmentTooLarge(AttachmentUnavailable):
    """받아 보니 상한보다 컸다(첨부 목록의 크기와 달랐거나 크기가 없었다)."""


@dataclass(frozen=True)
class DownloadedFile:
    data: bytes
    content_type: str | None


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

    async def attachment(
        self, url: str, *, max_bytes: int, html_ok: bool = False
    ) -> DownloadedFile:
        """공지 첨부 하나를 받는다(F-54). 토큰은 보내지 않는다(받는 쪽이 누구든 토큰을 볼 일이 없다).

        `url`은 공지 응답의 첨부 주소 그대로다. 우리 LearningX의 `/files/{id}/download`가 아니면 보내기
        전에 거절한다. `max_bytes`를 넘으면 받다가 멈춘다(AttachmentTooLarge). 첨부가 HTML이 아닌데
        HTML이 오면 로그인·오류 화면이 온 것으로 본다(`html_ok`는 첨부 자체가 HTML일 때만 켠다).
        """
        if not self._downloadable(url):
            raise AttachmentUnavailable("허용하지 않은 첨부 주소예요.")
        until = time.monotonic() + DOWNLOAD_BUDGET_SECONDS
        current = url
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                for _ in range(MAX_REDIRECTS + 1):
                    async with client.stream("GET", current, headers={"Accept": "*/*"}) as response:
                        if 300 <= response.status_code < 400:
                            current = self._next_hop(current, response.headers.get("Location"))
                            continue
                        return await self._read_file(response, max_bytes, html_ok, until)
        except httpx.HTTPError as exc:
            raise AttachmentUnavailable(
                f"첨부를 받지 못했어요(연결 오류 {type(exc).__name__})."
            ) from None
        raise AttachmentUnavailable("첨부 주소가 너무 여러 번 옮겨졌어요.")

    def _downloadable(self, url: str) -> bool:
        """우리 LearningX의 첨부 받기 경로인지(스킴·호스트까지 같아야 한다)."""
        parts = urlsplit(url)
        return (
            parts.scheme == self._scheme
            and parts.netloc.lower() == self._host
            and any(pattern.match(parts.path) for pattern in ALLOWED_DOWNLOADS)
        )

    def _next_hop(self, current: str, location: str | None) -> str:
        """리다이렉트할 곳. `https`가 아니거나 우리 LearningX의 다른 경로(로그인 화면)면 멈춘다."""
        if not location:
            raise AttachmentUnavailable("첨부 주소가 옮겨졌는데 갈 곳이 없어요.")
        target = urljoin(current, location)
        parts = urlsplit(target)
        # 시험·로컬 LearningX가 http일 때만 http를 허용한다. https를 http로 내리는 일은 없다
        if parts.scheme not in ("https", self._scheme):
            raise AttachmentUnavailable("첨부 주소가 안전하지 않은 곳으로 옮겨졌어요.")
        if parts.netloc.lower() == self._host and not any(
            pattern.match(parts.path) for pattern in ALLOWED_DOWNLOADS
        ):
            raise AttachmentUnavailable("LearningX가 첨부 대신 로그인 화면으로 보냈어요.")
        return target

    async def _read_file(
        self, response: httpx.Response, max_bytes: int, html_ok: bool, until: float
    ) -> DownloadedFile:
        if response.status_code != 200:
            raise AttachmentUnavailable(f"첨부를 받지 못했어요({response.status_code}).")
        content_type = response.headers.get("Content-Type")
        if not html_ok and content_type and content_type.split(";")[0].strip() == "text/html":
            raise AttachmentUnavailable("첨부 대신 웹 페이지가 왔어요.")
        declared = response.headers.get("Content-Length", "")
        if declared.isdigit() and int(declared) > max_bytes:
            raise AttachmentTooLarge("첨부가 상한보다 커요.")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise AttachmentTooLarge("첨부가 상한보다 커요.")
            if time.monotonic() > until:
                raise AttachmentUnavailable("첨부를 받는 데 너무 오래 걸려요.")
            chunks.append(chunk)
        return DownloadedFile(b"".join(chunks), content_type)

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
