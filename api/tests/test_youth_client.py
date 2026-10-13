"""온통청년 API 클라이언트: 쪽 받기, 실패한 쪽 나눠 받기, 막힘(403), 중간에 멈추면 받은 데까지, 키가 오류·로그에
남지 않음. HTTP는 respx로 가로챈다(가짜 온통청년은 10/13에 본 응답 모양을 따른다)."""

import logging
from collections.abc import Callable

import httpx
import pytest
import respx

from app.youth.client import (
    BASE_URL,
    BLOCKED_ERROR,
    POLICY_PATH,
    FetchResult,
    YouthApiError,
    YouthPolicyClient,
)

pytestmark = pytest.mark.anyio
KEY = "youthcenter-test-key-0123456789"
URL = BASE_URL + POLICY_PATH
BLOCKED = {"errorCode": "e001", "errorMsg": "invalid api key."}  # 10/13에 받은 403 본문


def policies(count: int) -> list[dict[str, str]]:
    return [{"plcyNo": f"2026{n:010d}", "plcyNm": f"정책 {n}"} for n in range(count)]


def server(
    items: list[dict[str, str]],
    *,
    broken: Callable[[int, int], bool] = lambda start, size: False,
    total: Callable[[int, int], int] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """getPlcy 흉내. broken(시작 순번, 쪽 크기)이 참이면 500이다. total(시작 순번, 쪽 크기)은 totCount다."""

    def handle(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params["apiKeyNm"] == KEY and params["rtnType"] == "json"
        num, size = int(params["pageNum"]), int(params["pageSize"])
        start = (num - 1) * size
        if broken(start, size):
            return httpx.Response(500, json={"status": 500, "error": "Internal Server Error"})
        body = {
            "resultCode": 200,
            "resultMessage": "성공적으로 데이터를 가지고 왔습니다.",
            "result": {
                "pagging": {
                    "totCount": total(start, size) if total else len(items),
                    "pageNum": num,
                    "pageSize": size,
                },
                "youthPolicyList": items[start : start + size],
            },
        }
        return httpx.Response(200, json=body)

    return handle


def client(**options: float) -> YouthPolicyClient:
    return YouthPolicyClient(KEY, retry_delay=0, page_delay=0, **options)


async def test_fetch_all_pages() -> None:
    items = policies(250)
    with respx.mock() as router:
        route = router.get(URL).mock(side_effect=server(items))
        fetched = await client().fetch_all()
    assert [p["plcyNo"] for p in fetched.policies] == [p["plcyNo"] for p in items]
    assert (fetched.total, fetched.calls, route.call_count) == (250, 3, 3)
    assert fetched.complete and fetched.summary()["complete"] is True


async def test_retry_then_split_and_skip_broken_record() -> None:
    """2쪽(100~199)이 계속 500이면 10건씩, 그래도 실패한 묶음(120~129)은 1건씩 받아 123번만 건너뛴다."""
    items = policies(250)

    def broken(start: int, size: int) -> bool:
        return start <= 123 < start + size

    with respx.mock() as router:
        router.get(URL).mock(side_effect=server(items, broken=broken))
        fetched = await client().fetch_all()
    assert len(fetched.policies) == 249 and fetched.skipped == (123,)
    assert items[123]["plcyNo"] not in {p["plcyNo"] for p in fetched.policies}
    # 1쪽 1 + 2쪽 2(다시 한 번) + 10건 쪽 9 + 13번째 묶음 2 + 1건씩 9 + 123번 2 + 3쪽 1
    assert fetched.calls == 26 and not fetched.complete and fetched.stopped is None


async def test_one_retry_is_enough() -> None:
    """10/13 1차에서 16쪽이 500이었고 다시 받으니 됐다. 한 번 실패한 쪽은 다시 받아 끝까지 받는다."""
    items = policies(150)
    seen: set[int] = set()

    def broken(start: int, size: int) -> bool:
        first_time = start == 100 and start not in seen
        seen.add(start)
        return first_time

    with respx.mock() as router:
        router.get(URL).mock(side_effect=server(items, broken=broken))
        fetched = await client().fetch_all()
    assert fetched.complete and fetched.calls == 3


async def test_page_that_is_not_json_is_fetched_again() -> None:
    """점검 화면처럼 200인데 JSON이 아닌 응답은 잠깐 실패로 보고 다시 받는다."""
    items = policies(150)
    answer = server(items)
    calls: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(int(request.url.params["pageNum"]))
        if len(calls) == 2:
            return httpx.Response(200, text="<html>시스템 점검 중</html>")
        return answer(request)

    with respx.mock() as router:
        router.get(URL).mock(side_effect=handle)
        fetched = await client().fetch_all()
    assert fetched.complete and calls == [1, 2, 2]


async def test_call_limit() -> None:
    with respx.mock() as router:
        router.get(URL).mock(side_effect=server(policies(500)))
        fetched = await client(max_calls=3).fetch_all()
    assert fetched.stopped == "호출 3회 한도에 닿음(4쪽)" and len(fetched.policies) == 300
    assert not fetched.complete


async def test_first_page_with_a_broken_record_is_split() -> None:
    """첫 쪽(최신 정책)에 읽지 못하는 정책이 있어도 나눠 받아 그 정책만 건너뛴다."""
    items = policies(150)
    with respx.mock() as router:
        router.get(URL).mock(
            side_effect=server(items, broken=lambda start, size: start <= 5 < start + size)
        )
        fetched = await client().fetch_all()
    assert fetched.skipped == (5,) and len(fetched.policies) == 149 and fetched.total == 150
    assert not fetched.complete


async def test_first_page_gives_up_quickly_when_the_service_is_down() -> None:
    """첫 쪽(2번)과 10건 묶음 둘(2번씩)이 실패하면 멈춘다."""
    with respx.mock() as router:
        route = router.get(URL).mock(return_value=httpx.Response(503, text="점검 중"))
        with pytest.raises(YouthApiError, match="첫 쪽이 두 번 실패"):
            await client().fetch_all()
    assert route.call_count == 6


async def test_empty_list_is_not_complete() -> None:
    """전체 0건(장애 때의 빈 목록)은 빠짐없이 받은 것이 아니다. 믿으면 넣은 정책을 모두 숨긴다."""
    with respx.mock() as router:
        router.get(URL).mock(side_effect=server([]))
        fetched = await client().fetch_all()
    assert (fetched.total, fetched.policies, fetched.complete) == (0, (), False)


async def test_call_limit_counts_split_calls() -> None:
    """나눠 받는 호출도 한도에 센다."""
    items = policies(500)
    with respx.mock() as router:
        route = router.get(URL).mock(
            side_effect=server(items, broken=lambda start, size: start <= 150 < start + size)
        )
        fetched = await client(max_calls=10).fetch_all()
    assert route.call_count == 10 and fetched.stopped == "호출 10회 한도에 닿음(2쪽)"


async def test_outage_in_the_middle_stops_after_twelve_failures() -> None:
    """2쪽의 첫 10건만 받고 온통청년이 멈췄다: 나머지 묶음을 받다가 연속 12번 실패하면 멈춘다."""
    items = policies(500)

    def broken(start: int, size: int) -> bool:
        return start >= 100 and (start, size) != (100, 10)

    with respx.mock() as router:
        route = router.get(URL).mock(side_effect=server(items, broken=broken))
        fetched = await client().fetch_all()
    assert fetched.stopped == "온통청년이 응답하지 않음(연속 12번 실패, 2쪽)"
    assert route.call_count == 1 + 2 + 1 + 12 and not fetched.complete


async def test_last_short_page_can_fail_as_a_whole() -> None:
    """마지막 쪽(50건)의 앞 두 묶음이 다 실패하면 통째로 실패한 쪽이다. 1건씩 받지 않는다."""
    with respx.mock() as router:
        route = router.get(URL).mock(
            side_effect=server(policies(250), broken=lambda start, size: start >= 200)
        )
        fetched = await client().fetch_all()
    assert fetched.skipped == tuple(range(200, 250)) and fetched.stopped is None
    assert route.call_count == 1 + 1 + 2 + 2 + 2 and not fetched.complete


async def test_two_whole_pages_fail_stop() -> None:
    items = policies(500)
    with respx.mock() as router:
        router.get(URL).mock(side_effect=server(items, broken=lambda start, size: start >= 100))
        fetched = await client().fetch_all()
    assert len(fetched.policies) == 100 and fetched.stopped == "2~3쪽을 받지 못함"
    assert fetched.skipped == tuple(range(100, 200)) and not fetched.complete


async def test_whole_failures_must_be_in_a_row_to_stop() -> None:
    """2쪽과 4쪽이 통째로 실패해도 사이의 3쪽을 받았으면 멈추지 않고 끝까지 받는다."""
    items = policies(500)
    with respx.mock() as router:
        router.get(URL).mock(
            side_effect=server(items, broken=lambda start, size: start // 100 in (1, 3))
        )
        fetched = await client().fetch_all()
    assert fetched.stopped is None and len(fetched.policies) == 300
    assert fetched.skipped == tuple(range(100, 200)) + tuple(range(300, 400))


async def test_page_with_one_broken_record_resets_whole_failures() -> None:
    """2쪽 통째 실패 → 3쪽은 한 건만 못 읽음(나머지는 받음) → 4쪽 통째 실패. 연속이 아니라 멈추지 않는다."""
    items = policies(500)

    def broken(start: int, size: int) -> bool:
        pages = 100 <= start < 200 or 300 <= start < 400
        return pages or start <= 250 < start + size

    with respx.mock() as router:
        router.get(URL).mock(side_effect=server(items, broken=broken))
        fetched = await client().fetch_all()
    assert fetched.stopped is None
    assert fetched.skipped == (*range(100, 200), 250, *range(300, 400))


def test_skipped_policies_are_not_complete() -> None:
    """건너뛴 정책이 있으면 받은 수가 전체 수와 같아도(받는 사이 새 정책이 올라옴) 빠짐없이 받은 것이 아니다."""
    fetched = FetchResult(
        policies=tuple(policies(3)),
        total=3,
        calls=4,
        skipped=(1,),
        stopped=None,
        total_changed=False,
        seconds=0.1,
    )
    assert not fetched.complete


async def test_total_changed_while_fetching_is_not_complete() -> None:
    """받는 동안 새 정책이 올라오면 쪽이 밀린다. 사라진 정책을 숨기지 않게 빠짐없이 받은 것으로 보지 않는다."""
    items = policies(150)
    with respx.mock() as router:
        router.get(URL).mock(
            side_effect=server(items, total=lambda start, size: 150 + start // 100)
        )
        fetched = await client().fetch_all()
    assert fetched.total_changed and not fetched.complete
    assert fetched.total == 150  # 처음 받은 쪽의 전체 건수


async def test_total_changed_on_small_pages() -> None:
    """나눠 받은 10건 묶음에서 바뀐 전체 건수도 센다."""
    items = policies(250)
    with respx.mock() as router:
        router.get(URL).mock(
            side_effect=server(
                items,
                broken=lambda start, size: size == 100 and start == 100,
                total=lambda start, size: 250 if size == 100 else 251,
            )
        )
        fetched = await client().fetch_all()
    assert fetched.total_changed and not fetched.complete


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx.Response(403, json=BLOCKED),
            "온통청년이 요청을 막았어요(HTTP 403·e001 invalid api key.)",
        ),
        (httpx.Response(401, text="Unauthorized"), "온통청년이 요청을 막았어요(HTTP 401)."),
        (
            httpx.Response(200, json=BLOCKED),
            "온통청년이 요청을 막았어요(HTTP 200·e001 invalid api key.)",
        ),
        (httpx.Response(404, text="없는 주소"), "온통청년이 요청을 받지 않았어요(HTTP 404)"),
        (
            httpx.Response(400, json={"errorCode": "e003", "errorMsg": "bad request"}),
            "온통청년이 요청을 받지 않았어요(HTTP 400·e003 bad request)",
        ),
        (
            httpx.Response(200, json={"resultCode": 400, "resultMessage": "잘못된 요청"}),
            "온통청년 응답 오류: 400 잘못된 요청",
        ),
        (
            httpx.Response(200, json={"errorCode": "e002", "errorMsg": "일일 호출 한도 초과"}),
            "온통청년 응답 오류: e002 일일 호출 한도 초과",
        ),
        (httpx.Response(200, json={}), "온통청년 응답 오류: 모르는 응답"),
        (httpx.Response(200, json={"resultCode": 200, "result": {}}), "응답 모양이 달라요"),
        (httpx.Response(200, json=["목록"]), "응답 모양이 달라요"),
    ],
)
async def test_stops_on_errors_that_retry_cannot_fix(
    response: httpx.Response, message: str
) -> None:
    with respx.mock() as router:
        route = router.get(URL).mock(return_value=response)
        with pytest.raises(YouthApiError) as caught:
            await client().fetch_all()
    assert message in str(caught.value) and route.call_count == 1


async def test_blocked_first_page_says_wrong_key_or_short_block() -> None:
    """10/13: 미리 보기 바로 뒤 넣기에서 맞는 키로 403 e001이 왔고 4분 뒤 됐다. 키 탓으로만 말하지 않는다."""
    with respx.mock() as router:
        router.get(URL).mock(return_value=httpx.Response(403, json=BLOCKED))
        with pytest.raises(YouthApiError) as caught:
            await client().fetch_all()
    assert str(caught.value) == BLOCKED_ERROR.format(detail="HTTP 403·e001 invalid api key.")
    assert str(caught.value) == (
        "온통청년이 요청을 막았어요(HTTP 403·e001 invalid api key.). 키가 틀렸거나, 방금 여러 번 불러"
        " 잠깐 막혔을 수 있어요. 몇 분 뒤 다시 돌려 보고, 그래도 같으면 api/.env의 YOUTH_API_KEY를"
        " 확인하세요"
    )
    assert caught.value.__context__ is None


async def test_blocked_midway_keeps_what_was_fetched() -> None:
    """2쪽에서 막히면 다시 받지 않고 멈춘다. 1쪽 정책은 돌려준다(넣을 수 있게). 빠짐없이 받은 것은 아니다."""
    items = policies(250)
    answer = server(items)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params["pageNum"] == "2":
            return httpx.Response(403, json=BLOCKED)
        return answer(request)

    with respx.mock() as router:
        route = router.get(URL).mock(side_effect=handle)
        fetched = await client().fetch_all()
    assert [p["plcyNo"] for p in fetched.policies] == [p["plcyNo"] for p in items[:100]]
    assert fetched.stopped == "2쪽에서 온통청년이 요청을 막음(HTTP 403·e001 invalid api key.)"
    assert (fetched.total, fetched.calls, route.call_count) == (250, 2, 2)
    assert not fetched.complete and fetched.summary()["stopped"] == fetched.stopped


async def test_blocked_while_splitting_the_first_page_keeps_the_total() -> None:
    """첫 쪽이 500이라 10건씩 받다가 둘째 묶음에서 막혔다. 받은 10건과 전체 건수(첫 묶음의 totCount)를 남긴다."""
    items = policies(150)
    answer = server(items, broken=lambda start, size: size == 100)

    def handle(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if (params["pageNum"], params["pageSize"]) == ("2", "10"):
            return httpx.Response(403, json=BLOCKED)
        return answer(request)

    with respx.mock() as router:
        router.get(URL).mock(side_effect=handle)
        fetched = await client().fetch_all()
    assert len(fetched.policies) == 10 and fetched.total == 150 and fetched.calls == 4
    assert fetched.stopped == "1쪽에서 온통청년이 요청을 막음(HTTP 403·e001 invalid api key.)"


async def test_second_fetch_starts_over() -> None:
    """같은 클라이언트로 다시 받을 때 앞의 결과를 쓰지 않는다. 다시 받은 첫 쪽이 막히면 오류다."""
    fetcher = client()
    with respx.mock() as router:
        router.get(URL).mock(side_effect=server(policies(150)))
        assert (await fetcher.fetch_all()).total == 150
    with respx.mock() as router:
        router.get(URL).mock(return_value=httpx.Response(403, json=BLOCKED))
        with pytest.raises(YouthApiError, match="요청을 막았어요"):
            await fetcher.fetch_all()


async def test_long_server_message_is_cut() -> None:
    """서버 문구는 100자까지만 붙인다."""
    with respx.mock() as router:
        body = {"errorCode": "e001", "errorMsg": "가" * 300}
        router.get(URL).mock(return_value=httpx.Response(403, json=body))
        with pytest.raises(YouthApiError) as caught:
            await client().fetch_all()
    assert f"(HTTP 403·e001 {'가' * 100})." in str(caught.value)


async def test_other_error_midway_keeps_what_was_fetched() -> None:
    """받는 도중의 다른 오류(응답 모양)도 거기까지 받은 정책으로 끝낸다. 첫 쪽이면 오류다(위 테스트)."""
    items = policies(250)
    answer = server(items)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params["pageNum"] == "3":
            return httpx.Response(200, json={"resultCode": 200, "result": {}})
        return answer(request)

    with respx.mock() as router:
        router.get(URL).mock(side_effect=handle)
        fetched = await client().fetch_all()
    assert len(fetched.policies) == 200 and not fetched.complete
    assert fetched.stopped == (
        "3쪽에서 온통청년 응답 모양이 달라요(result.youthPolicyList·result.pagging.totCount)"
    )


async def test_server_message_never_carries_the_key() -> None:
    """서버가 요청 값을 오류 문구·코드에 되돌려 줘도 키는 지운다. 받는 도중 멈춘 이유(stopped)도 같다."""
    bodies = [
        (200, {"resultCode": 500, "resultMessage": f"잘못된 요청 apiKeyNm={KEY}"}),
        (200, {"resultCode": 500, "resultMessage": f"키 {KEY} 를 확인"}),
        (403, {"errorCode": "e001", "errorMsg": f"invalid api key: {KEY}"}),
        (400, {"errorCode": KEY, "errorMsg": "bad"}),
    ]
    for status, body in bodies:
        with respx.mock() as router:
            router.get(URL).mock(return_value=httpx.Response(status, json=body))
            with pytest.raises(YouthApiError) as caught:
                await client().fetch_all()
        assert KEY not in str(caught.value) and "[REDACTED]" in str(caught.value)
        assert KEY not in caught.value.midway
    answer = server(policies(150))

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params["pageNum"] == "2":
            return httpx.Response(403, json={"errorCode": "e001", "errorMsg": f"키 {KEY}"})
        return answer(request)

    with respx.mock() as router:
        router.get(URL).mock(side_effect=handle)
        fetched = await client().fetch_all()
    assert fetched.stopped == "2쪽에서 온통청년이 요청을 막음(HTTP 403·e001 키 [REDACTED])"


async def test_key_never_appears_in_errors_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    """연결 오류 문구에는 요청 주소(키)가 들어갈 수 있어 이어 붙이지 않는다. httpx 요청 로그의 키는 가린다."""
    from app.logging_redact import install_log_redaction

    install_log_redaction()

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"연결 실패 {request.url}", request=request)

    with caplog.at_level(logging.INFO), respx.mock() as router:
        router.get(URL).mock(side_effect=refuse)
        with pytest.raises(YouthApiError) as caught:
            await client().fetch_all()
    assert "첫 쪽이 두 번 실패" in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert KEY not in repr(caught.value) and KEY not in caplog.text
    with caplog.at_level(logging.INFO), respx.mock() as router:
        router.get(URL).mock(side_effect=server(policies(3)))
        await client().fetch_all()
    assert "apiKeyNm=[REDACTED]" in caplog.text and KEY not in caplog.text


async def test_empty_key() -> None:
    with pytest.raises(YouthApiError, match="YOUTH_API_KEY가 비어 있어요"):
        YouthPolicyClient(" ")
