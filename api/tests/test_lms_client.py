"""LearningX 클라이언트(F-50): GET만·허용 경로만, 쪽 이어 받기, 남의 주소·평문 http는 따라가지 않음,
3xx·401·403 구분, 끝까지 못 받으면 예외, 토큰이 오류·로그에 남지 않음. HTTP는 respx로 가로챈다."""

import logging

import httpx
import pytest
import respx

from app.lms.client import MAX_PAGES, PER_PAGE, LearningXClient, LearningXError, allowed, next_link
from tests.lms_samples import COURSES, USERS_SELF

pytestmark = pytest.mark.anyio

BASE = "https://lms.test"
TOKEN = "18742~pAtB1g3TestTokenValue0000000000"
# 로그 가림(logging_redact)이 잡지 못하는 모양. "로그에 토큰이 없다"를 의미 있게 재는 데 쓴다
PLAIN_TOKEN = "plain-sample-value-not-token-shaped"


def client() -> LearningXClient:
    return LearningXClient(api_base=BASE + "/", timeout=2.0)


def test_only_the_recorded_paths_are_allowed() -> None:
    for path in (
        "/api/v1/users/self",
        "/api/v1/courses",
        "/api/v1/courses/214023/assignments",
        "/api/v1/courses/214023/modules",
        "/api/v1/courses/214023/modules/2749846/items",
        "/api/v1/courses/214023/discussion_topics",
    ):
        assert allowed(path), path
    for path in (
        "/api/v1/users/self/logins",  # 로그인 정보
        "/api/v1/courses/214023",  # 과목 상세(쓰지 않는다)
        "/api/v1/courses/214023/users",  # 같이 듣는 학생
        "/api/v1/courses/214023/students/submissions",  # 남의 제출
        "/api/v1/accounts",
        "/login/oauth2/token",
        "/api/v1/courses/abc/assignments",  # 번호가 아닌 과목
    ):
        assert not allowed(path), path


@respx.mock
async def test_it_sends_the_token_in_the_header_and_asks_for_a_hundred_at_a_time() -> None:
    route = respx.get(f"{BASE}/api/v1/courses").mock(httpx.Response(200, json=COURSES))
    got = await client().courses(TOKEN)
    assert len(got) == len(COURSES)
    request = route.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.url.params["per_page"] == str(PER_PAGE)
    assert request.url.params["enrollment_state"] == "active"
    assert request.url.params["include[]"] == "term"


@respx.mock
async def test_it_follows_the_next_page_until_the_header_stops() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=COURSES[2:])
        return httpx.Response(
            200,
            json=COURSES[:2],
            headers={"Link": f'<{BASE}/api/v1/courses?page=2&per_page=100>; rel="next"'},
        )

    route = respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(side_effect=handle)
    got = await client().courses(TOKEN)
    assert len(got) == len(COURSES)
    assert route.call_count == 2


@respx.mock
@pytest.mark.parametrize(
    "link",
    [
        '<https://evil.test/api/v1/courses?page=2>; rel="next"',  # 남의 주소
        '<https://lms.test/api/v1/accounts?page=2>; rel="next"',  # 허용하지 않은 경로
        '<http://lms.test/api/v1/courses?page=2>; rel="next"',  # 평문 http (토큰이 그대로 나간다)
        '<javascript:alert(1)>; rel="next"',
    ],
)
async def test_it_does_not_follow_a_next_page_somewhere_else(link: str) -> None:
    respx.get(f"{BASE}/api/v1/courses").mock(
        httpx.Response(200, json=COURSES[:1], headers={"Link": link})
    )
    elsewhere = respx.get(host="evil.test").mock(httpx.Response(200, json=[]))
    got = await client().courses(TOKEN)
    assert len(got) == 1
    assert not elsewhere.called


@respx.mock
async def test_it_refuses_to_hand_back_a_list_it_could_not_finish() -> None:
    """쪽 상한에 걸리면 받은 것을 돌려주지 않는다. 부분 목록을 전체로 쓰면 과목을 지운다."""
    route = respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(
        httpx.Response(
            200,
            json=COURSES[:1],
            headers={"Link": f'<{BASE}/api/v1/courses?page=9&per_page=100>; rel="next"'},
        )
    )
    with pytest.raises(LearningXError) as caught:
        await client().courses(TOKEN)
    assert "끝까지" in str(caught.value)
    assert route.call_count == MAX_PAGES


async def test_it_refuses_a_path_outside_the_allowed_list_before_asking() -> None:
    with respx.mock:  # 아무 경로도 등록하지 않는다. 요청을 보내면 respx가 터진다
        with pytest.raises(LearningXError) as caught:
            await client()._get(TOKEN, "/api/v1/courses/214023/users")
    assert "허용하지 않은" in str(caught.value)


@respx.mock
async def test_a_wrong_token_is_unauthorized_and_a_closed_path_is_forbidden() -> None:
    respx.get(f"{BASE}/api/v1/users/self").mock(
        httpx.Response(401, json={"errors": [{"message": "Invalid access token."}]})
    )
    with pytest.raises(LearningXError) as unauthorized:
        await client().me(TOKEN)
    assert unauthorized.value.unauthorized and not unauthorized.value.forbidden

    respx.get(url__startswith=f"{BASE}/api/v1/courses/1/assignments").mock(httpx.Response(403))
    with pytest.raises(LearningXError) as forbidden:
        await client().assignments(TOKEN, 1)
    assert forbidden.value.forbidden and not forbidden.value.unauthorized


@respx.mock
async def test_it_reports_a_connection_problem_without_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """토큰은 오류 문구·로그에 남지 않는다. 로그 가림이 잡지 못하는 모양으로 재야 뜻이 있다."""
    respx.get(f"{BASE}/api/v1/users/self").mock(side_effect=httpx.ConnectError("no route"))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(LearningXError) as caught:
            await client().me(PLAIN_TOKEN)
    assert "연결하지 못했어요" in str(caught.value)
    assert PLAIN_TOKEN not in str(caught.value)
    assert PLAIN_TOKEN not in caplog.text
    assert all(PLAIN_TOKEN not in str(record.args or ()) for record in caplog.records)


@respx.mock
async def test_it_does_not_follow_a_redirect(caplog: pytest.LogCaptureFixture) -> None:
    """리다이렉트를 따라가면 그 주소로 토큰을 보낸다. 3xx는 오류로 끝낸다."""
    respx.get(f"{BASE}/api/v1/users/self").mock(
        httpx.Response(302, headers={"Location": "https://evil.test/steal"})
    )
    elsewhere = respx.get(host="evil.test").mock(httpx.Response(200, json={}))
    with pytest.raises(LearningXError) as caught:
        await client().me(TOKEN)
    assert caught.value.status == 302
    assert not elsewhere.called


@respx.mock
async def test_too_many_requests_is_an_external_error_not_a_token_problem() -> None:
    respx.get(f"{BASE}/api/v1/users/self").mock(httpx.Response(429, headers={"Retry-After": "30"}))
    with pytest.raises(LearningXError) as caught:
        await client().me(TOKEN)
    assert caught.value.status == 429
    assert not caught.value.unauthorized and not caught.value.forbidden


@respx.mock
async def test_it_reads_the_user_and_rejects_a_body_in_another_shape() -> None:
    respx.get(f"{BASE}/api/v1/users/self").mock(httpx.Response(200, json=USERS_SELF))
    assert (await client().me(TOKEN))["id"] == USERS_SELF["id"]

    respx.get(f"{BASE}/api/v1/users/self").mock(httpx.Response(200, json=[1, 2]))
    with pytest.raises(LearningXError):
        await client().me(TOKEN)


def test_it_reads_the_next_link_out_of_the_header() -> None:
    header = (
        '<https://lms.test/api/v1/courses?page=1>; rel="current",'
        '<https://lms.test/api/v1/courses?page=2>; rel="next",'
        '<https://lms.test/api/v1/courses?page=1>; rel="first"'
    )
    assert next_link(header) == "https://lms.test/api/v1/courses?page=2"
    assert next_link('<https://lms.test/api/v1/courses?page=1>; rel="current"') is None
    assert next_link("") is None
    # rel이 두 번째 조각이 아닐 수도 있다
    other = '<https://lms.test/api/v1/courses?page=2>; type="application/json"; rel="next"'
    assert next_link(other) == "https://lms.test/api/v1/courses?page=2"
