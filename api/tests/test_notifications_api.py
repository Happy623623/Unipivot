"""알림함(F-35) 단위 테스트: 인증, 읽음 요청 모양, cursor 오류, 조사 붙이기. DB 없이 돈다."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.clock import current_time
from app.config import Settings, get_settings
from app.eligibility import KST
from app.eligibility.catalog import INPUT_LABELS
from app.main import create_app
from app.repositories.notifications import (
    DEADLINE_DAYS,
    NOTIFY_HOUR,
    PROFILE_DAILY,
    _link,
    _particle,
    get_notification_repo,
    needed_phrases,
)
from app.schemas.notifications import NotificationList, ReadRequest
from tests.conftest import USER_ID

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=KST)
PICKED = "00000000-0000-4000-8000-000000000009"
LIST = "/api/v1/notifications"
READ = "/api/v1/notifications/read"


class FakeNotificationRepository:
    """알림 저장소 대역. 받은 인자만 적어 둔다."""

    def __init__(self) -> None:
        self.listings: list[dict[str, Any]] = []
        self.reads: list[Any] = []
        self.fail_cursor = False

    async def listing(self, user_id: str, **kwargs: Any) -> NotificationList:
        if self.fail_cursor:
            raise ValueError("잘못된 cursor")
        self.listings.append({"user_id": user_id, **kwargs})
        return NotificationList(items=[], unread_count=0, next_cursor=None)

    async def read(self, user_id: str, *, now: datetime, ids: Any = None) -> int:
        self.reads.append({"user_id": user_id, "ids": ids})
        return 0


@pytest.fixture
def notifications() -> FakeNotificationRepository:
    return FakeNotificationRepository()


@pytest.fixture
def client(settings: Settings, notifications: FakeNotificationRepository) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_notification_repo] = lambda: notifications
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as test_client:
        yield test_client


def test_the_inbox_needs_a_login(client: TestClient) -> None:
    assert client.get(LIST).status_code == 401
    assert client.post(READ, json={"all": True}).status_code == 401


def test_the_inbox_passes_the_query_through(
    client: TestClient, auth: dict[str, str], notifications: FakeNotificationRepository
) -> None:
    response = client.get(LIST, headers=auth, params={"unread_only": True, "limit": 5})
    assert response.status_code == 200
    assert notifications.listings == [
        {"user_id": USER_ID, "now": NOW, "unread_only": True, "limit": 5, "cursor": None}
    ]


def test_a_broken_cursor_says_to_start_over(
    client: TestClient, auth: dict[str, str], notifications: FakeNotificationRepository
) -> None:
    notifications.fail_cursor = True
    response = client.get(LIST, headers=auth, params={"cursor": "망가진값"})
    assert response.status_code == 422
    assert "cursor" in response.json()["error"]["details"]["fields"]


@pytest.mark.parametrize("limit", [0, 51])
def test_the_limit_has_bounds(client: TestClient, auth: dict[str, str], limit: int) -> None:
    assert client.get(LIST, headers=auth, params={"limit": limit}).status_code == 422


def test_read_takes_ids_or_all_but_not_both_or_neither() -> None:
    """명세 10장: 둘 중 하나다. 둘 다 보내면 무엇을 읽은 셈인지 알 수 없다."""
    assert ReadRequest(all=True).ids is None
    assert ReadRequest(ids=[UUID(PICKED)]).all is False
    for payload in ({}, {"all": False}, {"ids": []}):
        with pytest.raises(ValidationError, match="ids 또는 all"):
            ReadRequest(**payload)
    with pytest.raises(ValidationError, match="ids 또는 all"):
        ReadRequest(all=True, ids=[UUID(PICKED)])


def test_reading_all_sends_no_ids(
    client: TestClient, auth: dict[str, str], notifications: FakeNotificationRepository
) -> None:
    client.post(READ, headers=auth, json={"all": True})
    client.post(READ, headers=auth, json={"ids": [PICKED]})
    assert [item["ids"] for item in notifications.reads] == [None, [UUID(PICKED)]]
    assert {item["user_id"] for item in notifications.reads} == {USER_ID}


def test_an_unknown_field_in_read_is_refused(client: TestClient, auth: dict[str, str]) -> None:
    assert client.post(READ, headers=auth, json={"everything": True}).status_code == 422


# ── 문구와 링크 ─────────────────────────────────────────────────────────────


def test_the_object_particle_follows_the_last_letter() -> None:
    """ "거주지역을 입력하면"과 "나이를 입력하면"이 둘 다 맞아야 한다."""
    assert _particle("거주지역") == "을"
    assert _particle("나이") == "를"
    assert _particle("학년") == "을"
    assert _particle("학과") == "를"
    assert _particle("GPA") == "을"  # 한글이 아니면 안전한 쪽


def test_every_asked_field_has_a_phrase() -> None:
    """물어볼 항목이 늘어도 문구가 비지 않는다(SQL이 이 표에서 이름을 찾는다)."""
    phrases = needed_phrases()
    assert set(phrases) == set(INPUT_LABELS)
    assert phrases["region"] == "거주지역을"
    assert phrases["age"] == "나이를"


def test_the_link_points_at_the_first_target_it_has() -> None:
    empty = dict.fromkeys(
        (
            "opportunity_id",
            "planner_task_id",
            "lms_assignment_id",
            "lms_module_item_id",
            "lms_announcement_id",
            "course_id",
        ),
        None,
    )
    assert _link({**empty, "type": "deadline_soon"}) is None
    opportunity = _link({**empty, "type": "deadline_soon", "opportunity_id": "o-1"})
    assert opportunity is not None
    assert (opportunity.type, opportunity.id, opportunity.focus) == ("opportunity", "o-1", None)
    # 정보 필요 알림은 상세에서 입력창을 바로 연다(명세 10장)
    needs = _link({**empty, "type": "profile_needed", "opportunity_id": "o-2"})
    assert needs is not None and needs.focus == "profile_input"
    # lms_* 링크에는 과목 id를 함께 내려준다
    material = _link(
        {**empty, "type": "new_material", "lms_module_item_id": "m-1", "course_id": "c-1"}
    )
    assert material is not None
    assert (material.type, material.course_id) == ("lms_module_item", "c-1")


def test_the_notification_rules_match_the_documents() -> None:
    assert DEADLINE_DAYS == (3, 1)  # PRD F-33: D-3과 D-1에 한 번씩
    assert NOTIFY_HOUR == 9  # 명세 10장 예시가 09:00+09:00
    assert PROFILE_DAILY == 1  # ERD: 하루 1건 제한은 발송 배치가 건다


def _sub(auth: dict[str, str]) -> str:
    import jwt

    return str(
        jwt.decode(auth["Authorization"].split()[1], options={"verify_signature": False})["sub"]
    )
