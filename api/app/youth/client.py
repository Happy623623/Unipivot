"""온통청년 청년정책 API(getPlcy) 클라이언트 (PRD F-11, 도구 fetch_youth_policies).

- 요청: GET https://www.youthcenter.go.kr/go/ythip/getPlcy?apiKeyNm=…&rtnType=json&pageNum=…&pageSize=…
- 응답: result.youthPolicyList(정책), result.pagging.totCount(전체 건수). 등록일 최신순이다(10/13 확인).
- 키(YOUTH_API_KEY)는 요청 주소에만 넣는다. 오류 문구·실행 로그·tool_calls에는 넣지 않는다.
- 쪽(100건)이 5xx·연결 오류·JSON 아닌 응답이면 잠시 뒤 한 번 더 받는다(10/13 1차에서 16쪽이 500이었고
  2차에서는 됐다). 그래도 실패하면 10건씩, 그래도 실패한 묶음은 1건씩 나눠 받아 읽지 못한 정책만 건너뛴다.
  첫 쪽도 같다(전체 건수는 처음 받은 묶음에서 안다). 10건 묶음이 앞의 둘 다 실패하면 그 쪽은 통째로
  실패한 것으로 보고, 첫 쪽이 그러면 멈춘다.
- 두 쪽 연속으로 통째로 실패하거나, 받기가 연속 OUTAGE_FAILURES번 실패하면(온통청년이 멈춤) 멈춘다. 키가
  틀리면(403 e001) 바로 멈춘다. 호출은 max_calls번까지다.
- 전체 건수가 0이거나 받는 동안 바뀌면 빠짐없이 받은 것으로 보지 않는다(목록에서 사라진 정책을 숨기지 않는다).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.logging_redact import redact

BASE_URL = "https://www.youthcenter.go.kr"
POLICY_PATH = "/go/ythip/getPlcy"
PAGE_SIZE = 100
SMALL_PAGE = 10
USER_AGENT = "UNIPIVOT-bot/0.3 (student capstone project)"
SHAPE_ERROR = "온통청년 응답 모양이 달라요(result.youthPolicyList·result.pagging.totCount)"
FIRST_PAGE_ERROR = "온통청년에서 정책 목록을 받지 못했어요(첫 쪽이 두 번 실패)"
OUTAGE_FAILURES = 12  # 받기가 연속으로 이만큼 실패하면 멈춘다(응답 없음 30초씩이면 6분)


class YouthApiError(Exception):
    """온통청년 API를 쓸 수 없음. 메시지는 키 없이 사람에게 보여도 되는 한 줄이다."""


class _Retry(Exception):
    """잠깐 실패(5xx, 연결 오류, JSON 아닌 응답). 다시 받으면 될 수 있다."""


class _CallLimit(Exception):
    """호출 한도(max_calls)에 닿음."""


class _Outage(Exception):
    """받기가 연속 OUTAGE_FAILURES번 실패함."""


@dataclass(frozen=True)
class FetchResult:
    policies: tuple[dict[str, Any], ...]
    total: int  # 처음 받은 묶음의 totCount
    calls: int
    skipped: tuple[int, ...]  # 읽지 못하고 건너뛴 순번(0부터)
    stopped: str | None  # 끝까지 받지 못한 이유
    total_changed: bool  # 받는 동안 전체 건수가 바뀜(쪽이 밀려 빠진 정책이 있을 수 있다)
    seconds: float

    @property
    def complete(self) -> bool:
        """목록을 빠짐없이 받았다. 이때만 목록에서 사라진 정책을 숨긴다. 0건이면 아니다."""
        return (
            self.total > 0
            and self.stopped is None
            and not self.skipped
            and not self.total_changed
            and len(self.policies) >= self.total
        )

    def summary(self) -> dict[str, Any]:
        """실행 로그(tool_calls.output)에 남기는 값."""
        return {
            "total": self.total,
            "fetched": len(self.policies),
            "calls": self.calls,
            "skipped": list(self.skipped[:50]),
            "stopped": self.stopped,
            "total_changed": self.total_changed,
            "complete": self.complete,
            "seconds": round(self.seconds, 1),
        }


class YouthPolicyClient:
    def __init__(
        self,
        api_key: str,
        *,
        http: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
        retry_delay: float = 2.0,
        page_delay: float = 0.2,
        max_calls: int = 600,
    ) -> None:
        if not api_key.strip():
            raise YouthApiError("YOUTH_API_KEY가 비어 있어요(api/.env)")
        self._key = api_key.strip()
        self._http = http or httpx.AsyncClient(timeout=30)
        self._url = base_url.rstrip("/") + POLICY_PATH
        self._retry_delay = retry_delay
        self._page_delay = page_delay
        self._max_calls = max_calls
        self.calls = 0
        self._totals: set[int] = set()  # 응답마다 받은 totCount
        self._failures = 0  # 연속으로 실패한 받기

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch_all(self) -> FetchResult:
        started = time.monotonic()
        self._totals = set()
        self._failures = 0
        found: dict[str, dict[str, Any]] = {}
        skipped: list[int] = []
        stopped: str | None = None
        total: int | None = None
        whole_failures = 0
        num = 1
        try:
            while total is None or (num - 1) * PAGE_SIZE < total:
                page = await self._page(num, PAGE_SIZE)
                if page is not None:
                    _add(found, page[0])
                    total = page[1] if total is None else total
                    whole_failures = 0
                    num += 1
                    continue
                total, failed, whole = await self._split(num, total, found)
                if total is None:
                    raise YouthApiError(FIRST_PAGE_ERROR)
                if whole:  # 받은 묶음이 하나도 없음
                    whole_failures += 1
                    if whole_failures >= 2:
                        stopped = f"{num - 1}~{num}쪽을 받지 못함"
                        break
                    skipped.extend(range((num - 1) * PAGE_SIZE, min(num * PAGE_SIZE, total)))
                    num += 1
                    continue
                whole_failures = 0
                for small in failed:
                    for offset in range((small - 1) * SMALL_PAGE, min(small * SMALL_PAGE, total)):
                        single = await self._page(offset + 1, 1)
                        if single is None:
                            skipped.append(offset)
                        else:
                            _add(found, single[0])
                num += 1
        except _CallLimit:
            stopped = f"호출 {self._max_calls}회 한도에 닿음({num}쪽)"
        except _Outage:
            stopped = f"온통청년이 응답하지 않음(연속 {OUTAGE_FAILURES}번 실패, {num}쪽)"
        return FetchResult(
            policies=tuple(found.values()),
            total=total or 0,
            calls=self.calls,
            skipped=tuple(skipped),
            stopped=stopped,
            total_changed=len(self._totals) > 1,
            seconds=time.monotonic() - started,
        )

    async def _split(
        self, num: int, total: int | None, found: dict[str, dict[str, Any]]
    ) -> tuple[int | None, list[int], bool]:
        """실패한 100건 쪽을 10건씩 받는다. (전체 건수, 실패한 10건 쪽 번호, 통째로 실패).

        전체 건수를 모르면(첫 쪽) 처음 받은 묶음에서 안다. 앞의 두 묶음이 다 실패하면 그 쪽은 통째로 실패한
        것으로 보고 나머지 묶음은 받지 않는다(온통청년이 멈춘 경우 오래 걸리지 않게)."""
        failed: list[int] = []
        got = False
        first = (num - 1) * (PAGE_SIZE // SMALL_PAGE) + 1
        for small in range(first, first + PAGE_SIZE // SMALL_PAGE):
            if total is not None and (small - 1) * SMALL_PAGE >= total:
                break
            if not got and len(failed) >= 2:
                break
            page = await self._page(small, SMALL_PAGE)
            if page is None:
                failed.append(small)
            else:
                got = True
                _add(found, page[0])
                total = page[1] if total is None else total
        return total, failed, not got

    async def _page(self, num: int, size: int) -> tuple[list[dict[str, Any]], int] | None:
        """(정책, totCount). 잠깐 실패면 한 번 더 받고, 그래도 실패하면 None이다."""
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(self._retry_delay)
            try:
                page = await self._get(num, size)
            except _Retry:
                self._failures += 1
                continue
            self._failures = 0
            return page
        return None

    async def _get(self, num: int, size: int) -> tuple[list[dict[str, Any]], int]:
        if self.calls >= self._max_calls:
            raise _CallLimit
        if self._failures >= OUTAGE_FAILURES:
            raise _Outage
        if self.calls:
            await asyncio.sleep(self._page_delay)
        self.calls += 1
        params = {"apiKeyNm": self._key, "rtnType": "json", "pageNum": num, "pageSize": size}
        try:
            response = await self._http.get(
                self._url, params=params, headers={"User-Agent": USER_AGENT}
            )
        except httpx.HTTPError:
            raise _Retry from None  # 오류 문구에 요청 주소(키)가 들어갈 수 있어 이어 붙이지 않는다
        try:
            data = response.json()
        except ValueError:
            data = None
        bad_key = isinstance(data, dict) and data.get("errorCode") == "e001"
        if bad_key or response.status_code in (401, 403):
            raise YouthApiError(
                "온통청년 API 키가 맞지 않아요(HTTP 403·e001). api/.env의 YOUTH_API_KEY를 확인하세요"
            )
        if response.status_code >= 500:
            raise _Retry
        if response.status_code != 200:
            raise YouthApiError(f"온통청년이 요청을 받지 않았어요(HTTP {response.status_code})")
        if data is None:
            raise _Retry  # 200인데 JSON이 아님(점검 화면 등)
        if not isinstance(data, dict):
            raise YouthApiError(SHAPE_ERROR)
        if str(data.get("resultCode")) != "200":
            raise YouthApiError(f"온통청년 응답 오류: {data.get('resultCode')} {self._safe(data)}")
        result = data.get("result")
        items = result.get("youthPolicyList") if isinstance(result, dict) else None
        paging = result.get("pagging") if isinstance(result, dict) else None
        total = paging.get("totCount") if isinstance(paging, dict) else None
        if not isinstance(items, list) or not isinstance(total, int):
            raise YouthApiError(SHAPE_ERROR)
        self._totals.add(total)
        return [item for item in items if isinstance(item, dict) and item.get("plcyNo")], total

    def _safe(self, data: dict[str, Any]) -> str:
        """서버가 준 오류 문구. 요청 값을 되돌려 줄 수도 있어 키를 지우고 100자로 자른다."""
        message = " ".join(str(data.get("resultMessage") or "").split())
        return redact(message.replace(self._key, "[REDACTED]"))[:100].strip()


def _add(found: dict[str, dict[str, Any]], items: list[dict[str, Any]]) -> None:
    """정책 번호로 모은다. 같은 번호는 나중에 받은 값으로 바꾼다(쪽이 밀려 두 번 받은 경우)."""
    for item in items:
        found[str(item["plcyNo"])] = item
