"""주차학습 열기(11/24): 브라우저가 주차학습 탭을 열 때와 같은 길을 가되, 정해진 곳으로만 가고 강의는 열지 않는다.

- 학생 토큰은 Canvas API(탭 목록·실행 주소)에만 보낸다. 실행 페이지·LTI 폼·주차학습 목록에는 보내지 않는다
- 실행 주소와 폼 주소는 우리 LearningX(같은 스킴·호스트)의 정해진 경로만 따른다
- POST는 받은 LTI 폼을 그대로 돌려보내는 한 번뿐이다
- 주차학습이 준 표(쿠키)는 메모리에만 두고, 실행 주소의 한 번 쓰는 값과 함께 오류·로그에 남지 않는다

HTTP는 respx로 가로챈다.
"""

import logging
from urllib.parse import parse_qsl

import httpx
import pytest
import respx

from app.lms.client import LearningXClient, LearningXError, lti_form, weekly_tool
from tests.lms_samples import (
    DB_LECTURE_MODULES,
    LAUNCH,
    LAUNCH_FIELDS,
    LAUNCH_VERIFIER,
    LEARNINGX_TOKEN,
    TABS,
    TABS_WITHOUT_WEEKLY,
    launch_page,
)

pytestmark = pytest.mark.anyio

BASE = "https://lms.test"
TOKEN = "18742~pAtB1g3TestTokenValue0000000000"
COURSE = 214023
TABS_URL = f"{BASE}/api/v1/courses/{COURSE}/tabs"
LAUNCH_API = f"{BASE}/api/v1/courses/{COURSE}/external_tools/sessionless_launch"
LAUNCH_URL = f"{BASE}/courses/{COURSE}/external_tools/sessionless_launch"
FORM_URL = f"{BASE}/learningx/lti/modulebuilder"
MODULES_URL = f"{BASE}/learningx/api/v1/courses/{COURSE}/modules"
COOKIE = f"xn_api_token={LEARNINGX_TOKEN}; Path=/; Secure; HttpOnly"


def client() -> LearningXClient:
    return LearningXClient(api_base=BASE + "/", timeout=2.0)


def mock_launch(
    *,
    tabs: object = TABS,
    launch: object = LAUNCH,
    page: str | None = None,
    posted: httpx.Response | None = None,
) -> dict[str, respx.Route]:
    """주차학습을 여는 길을 모두 가로챈다. 바꿀 응답만 넘긴다."""
    return {
        "tabs": respx.get(TABS_URL).mock(httpx.Response(200, json=tabs)),
        "launch": respx.get(LAUNCH_API).mock(httpx.Response(200, json=launch)),
        "page": respx.get(LAUNCH_URL).mock(
            httpx.Response(200, text=page if page is not None else launch_page())
        ),
        "post": respx.post(FORM_URL).mock(
            posted or httpx.Response(200, text="<html></html>", headers={"Set-Cookie": COOKIE})
        ),
    }


@respx.mock
async def test_it_opens_the_weekly_tab_the_way_the_browser_does() -> None:
    routes = mock_launch()
    session = await client().learningx_session(TOKEN, COURSE)
    assert session is not None and session.token == LEARNINGX_TOKEN
    assert LEARNINGX_TOKEN not in repr(session)  # 실수로 찍어도 표가 보이지 않는다

    tabs = routes["tabs"].calls[0].request
    assert tabs.headers["Authorization"] == f"Bearer {TOKEN}"
    assert tabs.url.params["include[]"] == "external"
    launch = routes["launch"].calls[0].request
    assert launch.headers["Authorization"] == f"Bearer {TOKEN}"
    assert launch.url.params["id"] == "140"  # 옛 도구('(구) 강의콘텐츠', 138)가 아니라 지금 도구다

    # 실행 페이지와 LTI 폼에는 학생 토큰을 보내지 않는다(브라우저도 보내지 않는다)
    page = routes["page"].calls[0].request
    assert "Authorization" not in page.headers
    assert page.url.params["verifier"] == LAUNCH_VERIFIER
    posted = routes["post"].calls[0].request
    assert "Authorization" not in posted.headers
    assert posted.headers["Content-Type"] == "application/x-www-form-urlencoded"
    # 폼 값을 HTML 글자를 풀어 그대로, 같은 순서로 돌려보낸다
    assert parse_qsl(posted.content.decode()) == LAUNCH_FIELDS


@respx.mock
async def test_it_reads_the_weekly_list_with_the_learningx_pass_only() -> None:
    route = respx.get(MODULES_URL).mock(httpx.Response(200, json=DB_LECTURE_MODULES))
    mock_launch()
    session = await client().learningx_session(TOKEN, COURSE)
    assert session is not None
    modules = await client().lecture_modules(session, COURSE)
    assert [one["title"] for one in modules] == [
        "3주차",
        "4주차 (개천절 대체휴일)",
        "6주차",
        "7주차",
    ]
    request = route.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {LEARNINGX_TOKEN}"
    assert TOKEN not in str(request.headers)  # 학생의 LearningX 토큰은 가지 않는다
    assert request.url.params["include_detail"] == "true"
    assert request.method == "GET"


@respx.mock
async def test_a_weekly_list_in_another_shape_is_an_error() -> None:
    respx.get(MODULES_URL).mock(httpx.Response(200, json={"errors": []}))
    mock_launch()
    session = await client().learningx_session(TOKEN, COURSE)
    assert session is not None
    with pytest.raises(LearningXError):
        await client().lecture_modules(session, COURSE)


@respx.mock
async def test_a_course_without_the_weekly_tab_has_no_session() -> None:
    routes = mock_launch(tabs=TABS_WITHOUT_WEEKLY)
    assert await client().learningx_session(TOKEN, COURSE) is None
    assert not routes["launch"].called and not routes["post"].called


@respx.mock
@pytest.mark.parametrize(
    "url",
    [
        f"https://evil.test/courses/{COURSE}/external_tools/sessionless_launch?verifier=x",
        f"http://lms.test/courses/{COURSE}/external_tools/sessionless_launch?verifier=x",  # 평문
        f"{BASE}/login/canvas?verifier=x",  # 우리 LearningX지만 실행 페이지가 아니다
        None,
    ],
)
async def test_it_does_not_open_a_launch_address_somewhere_else(url: str | None) -> None:
    routes = mock_launch(launch={**LAUNCH, "url": url})
    elsewhere = respx.route(host="evil.test").mock(httpx.Response(200, text=launch_page()))
    plain = respx.route(scheme="http").mock(httpx.Response(200, text=launch_page()))
    with pytest.raises(LearningXError):
        await client().learningx_session(TOKEN, COURSE)
    assert not elsewhere.called and not plain.called
    assert not routes["page"].called and not routes["post"].called


@respx.mock
@pytest.mark.parametrize(
    "action",
    [
        "https://evil.test/learningx/lti/modulebuilder",  # 남의 주소
        "http://lms.test/learningx/lti/modulebuilder",  # 평문
        "/api/v1/users/self",  # 우리 LearningX지만 LTI 폼 주소가 아니다
        "/learningx/lti/../../api/v1/courses",
    ],
)
async def test_it_does_not_post_the_form_somewhere_else(action: str) -> None:
    routes = mock_launch(page=launch_page(action))
    elsewhere = respx.post(url__regex=r".*").mock(httpx.Response(200))
    with pytest.raises(LearningXError):
        await client().learningx_session(TOKEN, COURSE)
    assert not routes["post"].called and not elsewhere.called


@respx.mock
async def test_a_relative_form_address_is_resolved_against_the_launch_page() -> None:
    routes = mock_launch(page=launch_page("/learningx/lti/modulebuilder"))
    assert await client().learningx_session(TOKEN, COURSE) is not None
    assert routes["post"].called


@respx.mock
@pytest.mark.parametrize(
    ("posted", "status"),
    [
        (httpx.Response(200, text="<html></html>"), None),  # 표(쿠키)가 오지 않았다
        # 다른 쿠키만 왔다(세션 쿠키 등) — 그것을 표로 쓰지 않는다
        (httpx.Response(200, text="", headers={"Set-Cookie": "_session=abc; Path=/"}), None),
        (httpx.Response(401, text="unauthorized"), 401),
        (httpx.Response(500, text="error"), 500),
    ],
)
async def test_it_needs_the_learningx_pass(posted: httpx.Response, status: int | None) -> None:
    mock_launch(posted=posted)
    with pytest.raises(LearningXError) as caught:
        await client().learningx_session(TOKEN, COURSE)
    assert caught.value.status == status


@respx.mock
async def test_a_redirect_after_the_form_still_gives_the_pass_and_is_not_followed() -> None:
    """LTI 폼 응답이 화면으로 옮기라고 해도 따라가지 않는다. 표는 그 응답의 쿠키로 온다."""
    moved = httpx.Response(
        302,
        headers=[("Location", f"{BASE}/learningx/home"), ("Set-Cookie", COOKIE)],
    )
    mock_launch(posted=moved)
    followed = respx.get(f"{BASE}/learningx/home").mock(httpx.Response(200))
    session = await client().learningx_session(TOKEN, COURSE)
    assert session is not None and session.token == LEARNINGX_TOKEN
    assert not followed.called


@respx.mock
@pytest.mark.parametrize(
    "page",
    [
        "<html><body>로그인이 필요해요</body></html>",
        '<form method="get" action="/learningx/lti/modulebuilder"><input name="a" value="1"></form>',
        '<form method="post" action="/learningx/lti/modulebuilder"></form>',  # 값이 없다
    ],
)
async def test_a_launch_page_without_a_post_form_is_an_error(page: str) -> None:
    routes = mock_launch(page=page)
    with pytest.raises(LearningXError):
        await client().learningx_session(TOKEN, COURSE)
    assert not routes["post"].called


@respx.mock
async def test_a_launch_page_that_moves_is_not_followed() -> None:
    routes = mock_launch()
    routes["page"].mock(httpx.Response(302, headers={"Location": "https://evil.test/"}))
    elsewhere = respx.route(host="evil.test").mock(httpx.Response(200))
    with pytest.raises(LearningXError) as caught:
        await client().learningx_session(TOKEN, COURSE)
    assert caught.value.status == 302
    assert not elsewhere.called


@respx.mock
async def test_the_one_time_address_and_the_pass_stay_out_of_errors_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    routes = mock_launch()
    routes["page"].mock(side_effect=httpx.ConnectError(f"cannot reach {LAUNCH['url']}"))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(LearningXError) as caught:
            await client().learningx_session(TOKEN, COURSE)
    assert LAUNCH_VERIFIER not in str(caught.value)
    assert LAUNCH_VERIFIER not in caplog.text

    respx.get(MODULES_URL).mock(side_effect=httpx.ConnectError("no route"))
    routes["page"].mock(httpx.Response(200, text=launch_page()))
    session = await client().learningx_session(TOKEN, COURSE)
    assert session is not None
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(LearningXError) as failed:
            await client().lecture_modules(session, COURSE)
    assert LEARNINGX_TOKEN not in str(failed.value)
    assert LEARNINGX_TOKEN not in caplog.text


def test_it_picks_the_current_weekly_tool_over_the_old_one() -> None:
    assert weekly_tool(TABS) == 140
    assert weekly_tool(list(reversed(TABS))) == 140
    assert weekly_tool([TABS[1]]) == 138  # 옛 도구만 있으면 그것이라도 연다
    assert weekly_tool(TABS_WITHOUT_WEEKLY) is None
    assert weekly_tool({"not": "a list"}) is None
    # 탭 번호 꼴이 다르면(도구가 아닌 탭) 고르지 않는다
    assert weekly_tool([{"id": "modules", "label": "주차학습"}]) is None
    assert weekly_tool([{"id": "context_external_tool_7", "label": "Lecture Contents"}]) == 7


def test_it_reads_only_the_first_form_of_the_launch_page() -> None:
    form = lti_form(launch_page())
    assert form is not None
    assert form.action == "https://lms.test/learningx/lti/modulebuilder"
    assert form.fields == LAUNCH_FIELDS  # 둘째 폼(로그아웃)의 값은 섞이지 않는다
    assert lti_form("<p>폼이 없다</p>") is None
