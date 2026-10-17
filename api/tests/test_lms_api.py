"""LearningX 연결 API(F-50): 토큰 확인·저장·교체·해제와 과목 목록.
LearningX 호출은 respx로 가로채고 SQL은 test_lms_db.py가 본다."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.agent_log import using
from app.clock import current_time
from app.config import Settings, get_settings
from app.crypto import decrypt
from app.db import get_log_connect
from app.lms.parse import course_name
from app.main import create_app
from app.repositories.lms import Connection, get_lms_repo, ordered
from app.schemas.lms import CourseItem
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeLogConnection
from tests.lms_samples import COURSES, DATABASE, MINE, USERS_SELF

CONNECTION = "/api/v1/lms/connection"
COURSES_PATH = "/api/v1/lms/courses"
BASE = "https://lms.test"
TOKEN = "18742~pAtB1g3TestTokenValue0000000000"
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 2026-10-16 12:00 KST


class FakeLmsRepository:
    def __init__(self) -> None:
        self.row: Connection | None = None
        self.saved_courses: list[dict[str, Any]] = []
        self.deactivated = 0

    async def connection(self, user_id: str) -> Connection | None:
        assert user_id == USER_ID
        return self.row

    async def save_connection(
        self,
        user_id: str,
        *,
        token: str,
        last4: str,
        canvas_user_id: int | None,
        now: datetime,
    ) -> None:
        assert user_id == USER_ID
        self.row = Connection(
            status="active",
            token_last4=last4,
            access_token=token,
            canvas_user_id=canvas_user_id,
            last_synced_at=now,
            last_error=None,
        )

    async def mark_error(self, user_id: str, message: str) -> None:
        if self.row:
            self.row = Connection(**{**self.row.__dict__, "status": "error", "last_error": message})

    async def delete_connection(self, user_id: str) -> bool:
        if self.row is None:
            return False
        self.row = None
        return True

    async def save_courses(
        self, user_id: str, courses: list[dict[str, Any]], *, now: datetime
    ) -> int:
        assert user_id == USER_ID
        if courses:  # 실제 저장소도 빈 목록으로는 과목을 내리지 않는다
            self.saved_courses = courses
        return len(courses)

    async def courses(self, user_id: str, *, now: datetime) -> list[CourseItem]:
        assert user_id == USER_ID
        items = []
        for one in self.saved_courses:
            parsed = course_name(one["name"])
            items.append(
                CourseItem(
                    id=f"course-{one['id']}",
                    canvas_course_id=one["id"],
                    name=one["name"],
                    short_name=parsed.short_name,
                    has_syllabus=False,
                    portal_syllabus_url=parsed.syllabus_url,
                    open_assignments=0,
                    new_materials=0,
                    next_due=None,
                )
            )
        return items


@pytest.fixture
def repo() -> FakeLmsRepository:
    return FakeLmsRepository()


@pytest.fixture
def log() -> FakeLogConnection:
    return FakeLogConnection()


@pytest.fixture
def client(
    settings: Settings, repo: FakeLmsRepository, log: FakeLogConnection
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: Settings(
        **{**settings.model_dump(), "lms_api_base": BASE}
    )
    app.dependency_overrides[get_lms_repo] = lambda: repo
    app.dependency_overrides[get_log_connect] = lambda: using(log)  # type: ignore[arg-type]
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as started:
        yield started


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def learningx(*, me: int = 200, courses: int = 200) -> None:
    respx.get(f"{BASE}/api/v1/users/self").mock(
        httpx.Response(me, json=USERS_SELF if me == 200 else {"errors": [{"message": "no"}]})
    )
    respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(
        httpx.Response(courses, json=COURSES if courses == 200 else {"errors": []})
    )


@respx.mock
def test_it_connects_and_keeps_only_my_student_courses(
    client: TestClient, repo: FakeLmsRepository, log: FakeLogConnection, settings: Settings
) -> None:
    learningx()
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["token_last4"] == TOKEN[-4:]
    assert body["courses"] == len(MINE)  # 조교 과목과 준비중 과목은 뺀다
    assert body["first_sync_run_id"] == log.run_id
    assert [one["id"] for one in repo.saved_courses] == [one["id"] for one in MINE]
    # 토큰은 암호화해서만 저장하고 응답에는 끝 4자리만 간다
    assert repo.row is not None
    assert repo.row.access_token != TOKEN
    assert decrypt(repo.row.access_token, settings.token_encryption_key) == TOKEN
    assert TOKEN not in response.text
    # 실행과 도구 호출이 기록됐고, 도구 입력에 토큰이 없다
    assert log.wrote("insert into agent_runs")
    assert log.tools() == ["check_lms_token", "fetch_lms_courses"]
    assert all(TOKEN not in str(params) for _, params in log.statements)


@respx.mock
def test_a_wrong_token_is_refused_and_nothing_is_saved(
    client: TestClient, repo: FakeLmsRepository, log: FakeLogConnection
) -> None:
    learningx(me=401)
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LMS_TOKEN_INVALID"
    assert repo.row is None and repo.saved_courses == []
    # 실패한 토큰 확인도 실행으로 남는다(지표에 쓴다). 과목은 받지 않는다
    assert log.tools() == ["check_lms_token"]
    assert any(
        "status = %s" in query and "failed" in str(params) for query, params in log.statements
    )


@respx.mock
def test_when_the_course_list_fails_the_connection_is_not_saved(
    client: TestClient, repo: FakeLmsRepository
) -> None:
    learningx(courses=500)
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LMS_API_ERROR"
    assert repo.row is None


@respx.mock
def test_a_token_that_lost_access_while_listing_courses_asks_to_reconnect(
    client: TestClient,
) -> None:
    learningx(courses=401)
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LMS_TOKEN_INVALID"


@respx.mock
def test_connecting_again_replaces_the_token(
    client: TestClient, repo: FakeLmsRepository, settings: Settings
) -> None:
    learningx()
    client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    second = "18742~sEcOnDtOkEnValue00000000000000"
    response = client.post(CONNECTION, json={"access_token": f"  {second}  "}, headers=headers())
    assert response.status_code == 201
    assert response.json()["token_last4"] == second[-4:]  # 앞뒤 공백은 떼고 받는다
    assert repo.row is not None
    assert decrypt(repo.row.access_token, settings.token_encryption_key) == second


@respx.mock
def test_it_shows_the_connection_and_forgets_it_on_disconnect(
    client: TestClient, repo: FakeLmsRepository
) -> None:
    assert client.get(CONNECTION, headers=headers()).status_code == 404
    assert client.delete(CONNECTION, headers=headers()).status_code == 404

    learningx()
    client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    view = client.get(CONNECTION, headers=headers())
    assert view.status_code == 200
    assert view.json() == {
        "status": "active",
        "token_last4": TOKEN[-4:],
        "last_synced_at": "2026-10-16T12:00:00+09:00",
        "last_error": None,
    }
    assert client.delete(CONNECTION, headers=headers()).status_code == 204
    assert client.get(CONNECTION, headers=headers()).status_code == 404
    assert repo.row is None


@respx.mock
def test_the_course_list_has_the_short_name_and_the_portal_link(client: TestClient) -> None:
    learningx()
    client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    items = client.get(COURSES_PATH, headers=headers()).json()["items"]
    assert [one["short_name"] for one in items] == [
        "데이터베이스",
        "기계학습",
        "대학원 세미나(비정규)",
    ]
    assert "suup=23525" in items[0]["portal_syllabus_url"]
    assert items[2]["portal_syllabus_url"] is None  # 과목명 꼴이 달라 링크를 만들 수 없다
    assert items[0]["name"] == "202620HY23525_데이터베이스"  # 원래 이름은 그대로 둔다


@respx.mock
def test_an_empty_course_list_does_not_wipe_the_courses_i_had(
    client: TestClient, repo: FakeLmsRepository
) -> None:
    learningx()
    client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert len(repo.saved_courses) == len(MINE)

    respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(httpx.Response(200, json=[]))
    again = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert again.status_code == 201
    assert again.json()["courses"] == 0
    assert len(repo.saved_courses) == len(MINE)  # 앞서 받은 과목이 그대로 남는다


@respx.mock
def test_courses_i_only_assist_or_that_are_not_open_yet_are_left_out(
    client: TestClient, repo: FakeLmsRepository
) -> None:
    learningx()
    no_state = {**DATABASE, "id": 219004}
    no_state.pop("workflow_state")  # 열렸는지 알 수 없는 과목도 세지 않는다
    huge = {**DATABASE, "id": 2**70}  # bigint를 넘는 번호는 저장하지 않는다(DB가 터진다)
    respx.get(url__startswith=f"{BASE}/api/v1/courses").mock(
        httpx.Response(200, json=[*COURSES, no_state, huge])
    )
    response = client.post(CONNECTION, json={"access_token": TOKEN}, headers=headers())
    assert response.json()["courses"] == len(MINE)
    assert [one["id"] for one in repo.saved_courses] == [one["id"] for one in MINE]


def test_the_course_list_order_does_not_depend_on_the_database() -> None:
    """정렬은 ordered()가 한다. DB의 정렬 규칙(collation)은 환경마다 한글·숫자 앞뒤가 바뀐다.

    DB 없이 도는 테스트라 CI에서만 걸리는 일이 없다(2026-10-16에 그렇게 한 번 걸렸다).
    """
    names = [
        "202620HY23534_기계학습",
        "대학원 세미나(비정규)",
        "2026 겨울 특강",
        "202620HY25123_AI+X공학융합프로젝트",
        "202620HY23525_데이터베이스",
    ]
    items = [
        CourseItem(
            id=f"course-{index}",
            canvas_course_id=index,
            name=name,
            short_name=course_name(name).short_name,
            has_syllabus=False,
            portal_syllabus_url=None,
            open_assignments=0,
            new_materials=0,
            next_due=None,
        )
        for index, name in enumerate(names, start=1)
    ]
    assert [one.short_name for one in ordered(items)] == [
        "2026 겨울 특강",  # 과목명 꼴이 아니라 이름 전체가 화면 이름이다
        "AI+X공학융합프로젝트",
        "기계학습",
        "대학원 세미나(비정규)",
        "데이터베이스",
    ]
    # 어느 순서로 들어와도 결과가 같다
    assert [one.name for one in ordered(items[::-1])] == [one.name for one in ordered(items)]


def test_it_refuses_a_body_with_another_field(client: TestClient) -> None:
    response = client.post(
        CONNECTION, json={"access_token": TOKEN, "lms": "other"}, headers=headers()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", CONNECTION),
        ("get", CONNECTION),
        ("delete", CONNECTION),
        ("get", COURSES_PATH),
        ("get", f"{COURSES_PATH}/11111111-1111-4111-8111-111111111111"),
        ("post", "/api/v1/lms/sync"),
        ("get", "/api/v1/lms/assignments"),
        ("get", "/api/v1/lms/updates"),
    ],
)
def test_every_lms_path_needs_a_login(client: TestClient, method: str, path: str) -> None:
    body = {"json": {"access_token": TOKEN}} if path == CONNECTION and method == "post" else {}
    assert getattr(client, method)(path, **body).status_code == 401
