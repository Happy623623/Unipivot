"""플래너 API(F-43): GET·POST·PATCH·DELETE /planner/tasks. 저장소는 가짜다. SQL은 test_planner_db.py가 본다."""

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.repositories.planner import PlannerRepository, TaskRow, get_planner_repo
from app.schemas.planner import PlannerLink, PlannerMarker, PlannerResponse, PlannerTask
from tests.conftest import USER_ID, make_token

TASKS = "/api/v1/planner/tasks"
TASK_ID = "00000000-0000-4000-8000-00000000c001"
OTHER_ID = "00000000-0000-4000-8000-00000000c002"


def a_task(task_id: str = TASK_ID, source: str = "manual", **values: Any) -> PlannerTask:
    return PlannerTask(
        id=task_id,
        title=values.get("title", "스터디 자료 정리"),
        due_date=values.get("due_date", date(2026, 10, 20)),
        is_done=values.get("is_done", False),
        source=source,  # type: ignore[arg-type]
        link=values.get("link", PlannerLink(type=None, id=None, title=None, category=None)),
    )


class FakePlannerRepository:
    """라우터가 쓰는 만큼만 흉내 낸다. 할 일은 (id → source) 하나만 들고 있는다."""

    def __init__(self) -> None:
        self.rows: dict[str, TaskRow] = {TASK_ID: TaskRow(TASK_ID, "manual", False)}
        self.added: list[tuple[str, str, date]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.removed: list[str] = []
        self.read: list[dict[str, Any]] = []
        self.response = PlannerResponse(items=[a_task()], markers=[])

    async def tasks(
        self, user_id: str, *, start: date, end: date, include_done: bool
    ) -> PlannerResponse:
        self.read.append(
            {"user": user_id, "start": start, "end": end, "include_done": include_done}
        )
        return self.response

    async def task(self, user_id: str, task_id: str) -> TaskRow | None:
        return self.rows.get(task_id) if user_id == USER_ID else None

    async def add(self, user_id: str, title: str, due_date: date) -> PlannerTask:
        self.added.append((user_id, title, due_date))
        return a_task(title=title, due_date=due_date)

    async def update(self, user_id: str, task_id: str, changes: dict[str, Any]) -> PlannerTask:
        self.updated.append((task_id, changes))
        row = self.rows[task_id]
        return a_task(task_id, row.source, **changes)

    async def remove(self, user_id: str, task_id: str) -> None:
        self.removed.append(task_id)


@pytest.fixture
def planner() -> FakePlannerRepository:
    return FakePlannerRepository()


@pytest.fixture
def client(settings: Settings, planner: FakePlannerRepository) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_planner_repo] = lambda: planner
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def test_planner_requires_login(client: TestClient) -> None:
    assert client.get(f"{TASKS}?from=2026-10-01&to=2026-10-31").status_code == 401
    assert client.post(TASKS, json={"title": "x", "due_date": "2026-10-05"}).status_code == 401
    assert client.patch(f"{TASKS}/{TASK_ID}", json={"is_done": True}).status_code == 401
    assert client.delete(f"{TASKS}/{TASK_ID}").status_code == 401


def test_read_tasks_passes_the_range(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    planner.response = PlannerResponse(
        items=[
            a_task(
                source="prep_plan",
                title="재학증명서 준비",
                link=PlannerLink(
                    type="opportunity", id="o-1", title="한양브레인 장학금", category="scholarship"
                ),
            )
        ],
        markers=[
            PlannerMarker(
                date=date(2026, 10, 24),
                title="한양브레인 장학금 마감",
                opportunity_id="o-1",
                category="scholarship",
            )
        ],
    )
    res = client.get(f"{TASKS}?from=2026-10-01&to=2026-10-31&include_done=false", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert body["items"][0]["link"] == {
        "type": "opportunity",
        "id": "o-1",
        "title": "한양브레인 장학금",
        "category": "scholarship",
        "html_url": None,
    }
    assert body["markers"][0]["kind"] == "deadline"
    assert planner.read == [
        {
            "user": USER_ID,
            "start": date(2026, 10, 1),
            "end": date(2026, 10, 31),
            "include_done": False,
        }
    ]


def test_read_tasks_checks_the_range(client: TestClient, auth: dict[str, str]) -> None:
    bad = client.get(f"{TASKS}?from=2026-10-31&to=2026-10-01", headers=auth)
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "VALIDATION_FAILED")
    assert bad.json()["error"]["details"]["fields"] == {
        "to": "끝 날짜는 시작 날짜보다 뒤여야 해요."
    }
    wide = client.get(f"{TASKS}?from=2026-01-01&to=2027-12-31", headers=auth)
    assert wide.status_code == 422 and "400일" in wide.json()["error"]["details"]["fields"]["to"]
    shape = client.get(f"{TASKS}?from=10/01/2026&to=2026-10-31", headers=auth)
    assert shape.status_code == 422 and "from" in shape.json()["error"]["details"]["fields"]


def test_add_task_trims_the_title(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    res = client.post(
        TASKS, json={"title": "  스터디   자료 정리 ", "due_date": "2026-10-05"}, headers=auth
    )
    assert res.status_code == 201
    assert res.json()["title"] == "스터디 자료 정리"
    assert planner.added == [(USER_ID, "스터디 자료 정리", date(2026, 10, 5))]
    blank = client.post(TASKS, json={"title": "   ", "due_date": "2026-10-05"}, headers=auth)
    assert blank.status_code == 422 and planner.added == [
        (USER_ID, "스터디 자료 정리", date(2026, 10, 5))
    ]


def test_patch_changes_only_what_was_sent(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    res = client.patch(f"{TASKS}/{TASK_ID}", json={"is_done": True}, headers=auth)
    assert res.status_code == 200 and res.json()["is_done"] is True
    assert planner.updated == [(TASK_ID, {"is_done": True})]
    empty = client.patch(f"{TASKS}/{TASK_ID}", json={}, headers=auth)
    assert (empty.status_code, empty.json()["error"]["code"]) == (422, "VALIDATION_FAILED")
    assert len(planner.updated) == 1


def test_a_prep_task_moves_but_keeps_its_title(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    """준비 할 일은 날짜만 옮긴다(제목은 공고의 서류 이름이다)."""
    planner.rows[TASK_ID] = TaskRow(TASK_ID, "prep_plan", False)
    moved = client.patch(f"{TASKS}/{TASK_ID}", json={"due_date": "2026-10-21"}, headers=auth)
    assert moved.status_code == 200 and planner.updated == [
        (TASK_ID, {"due_date": date(2026, 10, 21)})
    ]
    renamed = client.patch(
        f"{TASKS}/{TASK_ID}", json={"title": "내 맘대로", "due_date": "2026-10-21"}, headers=auth
    )
    assert (renamed.status_code, renamed.json()["error"]["code"]) == (400, "FIELD_READ_ONLY")
    assert renamed.json()["error"]["message"] == "준비 일정으로 만든 할 일은 날짜만 옮길 수 있어요."
    assert renamed.json()["error"]["details"] == {"fields": ["title"]}
    assert len(planner.updated) == 1  # 하나라도 막히면 아무것도 바꾸지 않는다


def test_an_lms_task_only_takes_a_check(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    planner.rows[TASK_ID] = TaskRow(TASK_ID, "lms_assignment", False)
    done = client.patch(f"{TASKS}/{TASK_ID}", json={"is_done": True}, headers=auth)
    assert done.status_code == 200
    moved = client.patch(f"{TASKS}/{TASK_ID}", json={"due_date": "2026-10-21"}, headers=auth)
    assert (moved.status_code, moved.json()["error"]["code"]) == (400, "FIELD_READ_ONLY")
    assert moved.json()["error"]["message"] == "LMS에서 가져온 할 일은 완료만 바꿀 수 있어요."


def test_delete_only_removes_manual_tasks(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    assert client.delete(f"{TASKS}/{TASK_ID}", headers=auth).status_code == 204
    assert planner.removed == [TASK_ID]
    planner.rows[TASK_ID] = TaskRow(TASK_ID, "prep_plan", False)
    res = client.delete(f"{TASKS}/{TASK_ID}", headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (400, "TASK_NOT_DELETABLE")
    assert res.json()["error"]["message"] == (
        "준비 일정으로 만든 할 일은 지울 수 없어요. 공고 상세에서 확인해 주세요."
    )
    assert planner.removed == [TASK_ID]


def test_someone_elses_task_is_not_found(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    """남의 할 일·없는 할 일은 똑같이 404다(있는지조차 알려주지 않는다)."""
    patched = client.patch(f"{TASKS}/{OTHER_ID}", json={"is_done": True}, headers=auth)
    assert (patched.status_code, patched.json()["error"]["code"]) == (404, "NOT_FOUND")
    removed = client.delete(f"{TASKS}/{OTHER_ID}", headers=auth)
    assert (removed.status_code, removed.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert planner.updated == [] and planner.removed == []


def test_the_repository_matches_the_fake() -> None:
    """가짜가 실제 저장소와 같은 모양인지 본다(실제가 바뀌면 여기서 걸린다)."""
    for name in ("tasks", "task", "add", "update", "remove"):
        assert hasattr(PlannerRepository, name) and hasattr(FakePlannerRepository, name)


def test_a_syllabus_task_moves_but_keeps_its_title(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    """강의계획서에서 온 할 일도 날짜만 옮긴다(F-14가 붙으면 생긴다)."""
    planner.rows[TASK_ID] = TaskRow(TASK_ID, "syllabus", False)
    assert (
        client.patch(
            f"{TASKS}/{TASK_ID}", json={"due_date": "2026-10-21"}, headers=auth
        ).status_code
        == 200
    )
    res = client.patch(f"{TASKS}/{TASK_ID}", json={"title": "새 이름"}, headers=auth)
    assert (res.status_code, res.json()["error"]["code"]) == (400, "FIELD_READ_ONLY")
    assert res.json()["error"]["message"] == "강의계획서에서 온 할 일은 날짜만 옮길 수 있어요."


def test_one_locked_field_blocks_the_whole_change(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    """바꿀 수 있는 항목과 막힌 항목을 섞어 보내면 아무것도 바꾸지 않는다."""
    planner.rows[TASK_ID] = TaskRow(TASK_ID, "lms_assignment", False)
    res = client.patch(
        f"{TASKS}/{TASK_ID}", json={"is_done": True, "due_date": "2026-10-21"}, headers=auth
    )
    assert (res.status_code, res.json()["error"]["code"]) == (400, "FIELD_READ_ONLY")
    assert res.json()["error"]["details"] == {"fields": ["due_date"]}
    assert planner.updated == []


def test_unknown_fields_are_refused(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    """오타를 조용히 넘기지 않는다. 출처·완료를 직접 정해 만들 수도 없다."""
    typo = client.patch(f"{TASKS}/{TASK_ID}", json={"is_done": True, "titel": "오타"}, headers=auth)
    assert typo.status_code == 422 and planner.updated == []
    made = client.post(
        TASKS,
        json={"title": "x", "due_date": "2026-10-05", "source": "prep_plan", "is_done": True},
        headers=auth,
    )
    assert made.status_code == 422 and planner.added == []


def test_include_done_defaults_to_showing_everything(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    """화면은 완료한 할 일도 함께 보여 준다(체크한 것이 사라지면 안 된다)."""
    client.get(f"{TASKS}?from=2026-10-01&to=2026-10-31", headers=auth)
    assert planner.read[0]["include_done"] is True


def test_the_range_edge(
    client: TestClient, auth: dict[str, str], planner: FakePlannerRepository
) -> None:
    """상한은 400일이다(그날까지 되고 그 다음 날부터 막힌다)."""
    assert client.get(f"{TASKS}?from=2026-01-01&to=2027-02-04", headers=auth).status_code == 200
    assert client.get(f"{TASKS}?from=2026-01-01&to=2027-02-05", headers=auth).status_code == 422
    assert client.get(f"{TASKS}?from=2026-10-05&to=2026-10-05", headers=auth).status_code == 200
