"""학교 공지 링크 API(B안): POST /notices/link의 응답 규칙. 서비스는 가짜다.
실제 실행·학교 사이트·SQL은 test_notice_link_db.py가 본다."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clock import current_time
from app.config import NOTICE_LINK_PERMIT_ENDS, POLICY_V02_EFFECTIVE, Settings, get_settings
from app.crawl.link import NoticeLink
from app.crawl.service import DAILY_LINK_LIMIT, SEOUL, Existing, get_notice_link_service
from app.deploy import plan as deploy_plan
from tests.conftest import USER_ID
from tests.school_fakes import permalink, view_link

LINK = "/api/v1/notices/link"
NOW = datetime(2026, 11, 4, 15, 30, tzinfo=UTC)  # 11/5 00:30 KST
ENTRY = 119702


class FakeLinkService:
    def __init__(self) -> None:
        self.found: dict[str, Existing] = {}
        self.used = 0
        self.since: list[datetime] = []
        self.ongoing: dict[tuple[str, str], str] = {}
        self.begun: list[tuple[str, NoticeLink]] = []
        self.model = True

    def has_model(self) -> bool:
        return self.model

    def admission(self) -> Any:
        return nullcontext()  # 차례는 test_notice_link_db.py가 동시에 보내서 본다

    async def existing(self, entry_id: str) -> Existing | None:
        return self.found.get(entry_id)

    async def used_since(self, user_id: str, since: datetime) -> int:
        self.since.append(since)
        return self.used

    def running(self, user_id: str, entry_id: str) -> str | None:
        return self.ongoing.get((user_id, entry_id))

    async def begin(self, user_id: str, link: NoticeLink) -> str:
        self.begun.append((user_id, link))
        return "00000000-0000-4000-8000-0000000000b1"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """링크 가져오기를 연 서버. 여는 시각은 test_links_open_when_the_policy_takes_effect가, 닫는 시각은
    test_links_close_when_the_school_permit_ends가 본다."""
    return settings.model_copy(update={"notice_link_opens_at": None, "notice_link_closes_at": None})


@pytest.fixture
def service(client: TestClient) -> FakeLinkService:
    fake = FakeLinkService()
    client.app.dependency_overrides[get_notice_link_service] = lambda: fake  # type: ignore[attr-defined]
    client.app.dependency_overrides[current_time] = lambda: NOW  # type: ignore[attr-defined]
    return fake


def post(client: TestClient, auth: dict[str, str], url: Any) -> Any:
    return client.post(LINK, json={"url": url}, headers=auth)


def test_a_new_notice_starts_a_run(
    client: TestClient, auth: dict[str, str], service: FakeLinkService
) -> None:
    answer = post(client, auth, view_link(ENTRY))
    assert answer.status_code == 202
    assert answer.json() == {
        "status": "running",
        "run_id": "00000000-0000-4000-8000-0000000000b1",
        "opportunity_id": None,
    }
    assert answer.headers["location"] == "/api/v1/runs/00000000-0000-4000-8000-0000000000b1"
    ((user, link),) = service.begun
    assert (user, link.entry_id) == (USER_ID, "119702")
    assert [since.isoformat() for since in service.since] == ["2026-11-05T00:00:00+09:00"]


def test_an_imported_notice_is_given_without_asking_the_school(
    client: TestClient, auth: dict[str, str], service: FakeLinkService
) -> None:
    service.found["119702"] = Existing("00000000-0000-4000-8000-0000000000c1", False, "제목")
    service.used = DAILY_LINK_LIMIT  # 한도를 다 써도 이미 가져온 공지는 준다
    answer = post(client, auth, permalink(ENTRY))
    assert answer.status_code == 200
    assert answer.json() == {
        "status": "existing",
        "run_id": None,
        "opportunity_id": "00000000-0000-4000-8000-0000000000c1",
    }
    assert service.begun == []

    service.found["119702"] = Existing("00000000-0000-4000-8000-0000000000c1", True, "서울 공지")
    hidden = post(client, auth, permalink(ENTRY))
    assert hidden.status_code == 422
    assert hidden.json()["error"]["code"] == "SEOUL_NOTICE"
    assert hidden.json()["error"]["message"] == SEOUL


def test_the_same_notice_being_read_returns_that_run(
    client: TestClient, auth: dict[str, str], service: FakeLinkService
) -> None:
    service.ongoing[(USER_ID, "119702")] = "00000000-0000-4000-8000-0000000000d1"
    answer = post(client, auth, permalink(ENTRY))
    assert answer.status_code == 200
    assert answer.json()["run_id"] == "00000000-0000-4000-8000-0000000000d1"
    assert service.begun == []


def test_the_daily_limit(
    client: TestClient, auth: dict[str, str], service: FakeLinkService
) -> None:
    service.used = DAILY_LINK_LIMIT
    answer = post(client, auth, permalink(ENTRY))
    assert answer.status_code == 429
    error = answer.json()["error"]
    assert error["code"] == "DAILY_LINK_LIMIT"
    assert error["details"] == {"reset_at": "2026-11-06T00:00:00+09:00"}
    service.used = DAILY_LINK_LIMIT - 1
    assert post(client, auth, permalink(ENTRY)).status_code == 202


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("", "공지 주소를 붙여 주세요."),
        (
            "https://www.hanyang.ac.kr/notice_all",
            "공지 글 하나의 주소를 붙여 주세요. 목록이 아니라 글을 연 화면의 주소예요.",
        ),
        (
            "https://portal.hanyang.ac.kr/notice/url/4a4/1d396",
            "한양대 공지사항(www.hanyang.ac.kr)의 글 주소만 가져올 수 있어요.",
        ),
    ],
)
def test_bad_links_say_what_to_paste(
    client: TestClient, auth: dict[str, str], service: FakeLinkService, url: str, message: str
) -> None:
    answer = post(client, auth, url)
    assert answer.status_code == 422
    error = answer.json()["error"]
    assert (error["code"], error["details"]["fields"]) == ("VALIDATION_FAILED", {"url": message})
    assert service.begun == []


def test_switched_off_reads_nothing_new(
    client: TestClient, auth: dict[str, str], service: FakeLinkService, settings: Settings
) -> None:
    off = settings.model_copy(update={"notice_link_enabled": False})
    client.app.dependency_overrides[get_settings] = lambda: off  # type: ignore[attr-defined]
    answer = post(client, auth, permalink(ENTRY))
    assert answer.status_code == 409
    error = answer.json()["error"]
    assert (error["code"], error["message"]) == (
        "NOTICE_LINK_DISABLED",
        "지금은 학교 공지 링크를 받지 않아요. 포스터로 올려 주세요.",
    )
    assert service.begun == []
    service.found["119702"] = Existing("00000000-0000-4000-8000-0000000000c1", False, "제목")
    existing = post(client, auth, permalink(ENTRY))  # 학교에 묻지 않으니 꺼 둬도 준다
    assert existing.status_code == 200 and existing.json()["status"] == "existing"


def test_links_open_when_the_policy_takes_effect(
    client: TestClient, auth: dict[str, str], service: FakeLinkService, settings: Settings
) -> None:
    """처리방침 v0.2(링크 가져오기를 적은 판)가 시행되기 전에는 새로 읽지 않는다(붙인 주소를 남기지 않는다)."""
    policy = settings.model_copy(update={"notice_link_opens_at": POLICY_V02_EFFECTIVE})
    client.app.dependency_overrides[get_settings] = lambda: policy  # type: ignore[attr-defined]
    early = post(client, auth, permalink(ENTRY))  # NOW는 11/5 00:30 KST
    assert early.status_code == 409
    error = early.json()["error"]
    assert (error["code"], error["message"]) == (
        "NOTICE_LINK_DISABLED",
        "학교 공지 링크는 11월 12일부터 받아요. 그 전에는 포스터로 올려 주세요.",
    )
    assert service.begun == [] and service.since == []
    service.found["119702"] = Existing("00000000-0000-4000-8000-0000000000c1", False, "제목")
    existing = post(client, auth, permalink(ENTRY))  # 이미 가져온 공지는 그 전에도 준다
    assert existing.status_code == 200 and existing.json()["status"] == "existing"
    del service.found["119702"]
    opened = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)  # 11/12 0시 KST
    client.app.dependency_overrides[current_time] = lambda: opened  # type: ignore[attr-defined]
    assert post(client, auth, permalink(ENTRY)).status_code == 202


def test_links_close_when_the_school_permit_ends(
    client: TestClient, auth: dict[str, str], service: FakeLinkService, settings: Settings
) -> None:
    """학교(미디어전략팀)가 허가한 시범 운영은 12/31까지다(11/24). 1/1 0시(KST)부터는 새로 읽지 않는다."""
    permit = settings.model_copy(update={"notice_link_closes_at": NOTICE_LINK_PERMIT_ENDS})
    client.app.dependency_overrides[get_settings] = lambda: permit  # type: ignore[attr-defined]
    last = datetime(2026, 12, 31, 14, 59, 59, tzinfo=UTC)  # 12/31 23:59:59 KST
    client.app.dependency_overrides[current_time] = lambda: last  # type: ignore[attr-defined]
    assert post(client, auth, permalink(ENTRY)).status_code == 202
    service.begun.clear()
    service.since.clear()
    ended = datetime(2026, 12, 31, 15, 0, tzinfo=UTC)  # 1/1 0시 KST
    client.app.dependency_overrides[current_time] = lambda: ended  # type: ignore[attr-defined]
    late = post(client, auth, permalink(ENTRY))
    assert late.status_code == 409
    error = late.json()["error"]
    assert (error["code"], error["message"]) == (
        "NOTICE_LINK_DISABLED",
        "학교 공지 링크는 12월 31일까지 받았어요. 공지 화면을 캡처해 올려 주세요.",
    )
    assert service.begun == [] and service.since == []  # 학교에 묻지 않고 하루 한도도 쓰지 않는다
    service.found["119702"] = Existing("00000000-0000-4000-8000-0000000000c1", False, "제목")
    existing = post(client, auth, permalink(ENTRY))  # 이미 가져온 공지는 닫은 뒤에도 준다
    assert existing.status_code == 200 and existing.json()["status"] == "existing"


def test_the_close_time_defaults_to_the_end_of_the_school_permit() -> None:
    """배포는 이 값을 옮기지 않으니(DEFAULTS_ONLY) 기본값이 곧 운영 값이다. 시간대 없이 적으면 KST로 본다."""
    assert Settings.model_fields["notice_link_closes_at"].default == datetime(
        2027, 1, 1, tzinfo=timezone(timedelta(hours=9))
    )
    naive = Settings(_env_file=None, notice_link_closes_at="2026-12-01T00:00:00")  # type: ignore[call-arg]
    assert naive.notice_link_closes_at == datetime(2026, 11, 30, 15, 0, tzinfo=UTC)
    # 로컬에서 미리 보려고 바꾼 값이 배포로 가지 않는다
    assert "notice_link_closes_at" in deploy_plan.DEFAULTS_ONLY


def test_a_server_without_a_model_starts_nothing(
    client: TestClient, auth: dict[str, str], service: FakeLinkService
) -> None:
    service.model = False
    answer = post(client, auth, permalink(ENTRY))
    assert answer.status_code == 502
    error = answer.json()["error"]
    assert (error["code"], error["message"]) == (
        "LLM_ERROR",
        "지금은 공지를 가져올 수 없어요. 잠시 후 다시 붙여 주세요.",
    )
    assert service.begun == [] and service.since == []  # 실행을 만들지 않아 하루 한도도 쓰지 않는다


def test_login_is_required(client: TestClient, service: FakeLinkService) -> None:
    assert client.post(LINK, json={"url": permalink(ENTRY)}).status_code == 401
    assert service.begun == []
