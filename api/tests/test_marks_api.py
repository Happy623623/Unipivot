"""관심 표시 API(F-45): PUT·DELETE /opportunities/{id}/mark와 피드의 include_not_interested.
저장소는 가짜다. SQL은 test_marks_db.py가 본다."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.clock import current_time
from app.repositories.opportunities import Cursor, FeedQuery, encode_cursor
from tests.conftest import USER_ID
from tests.fakes import FakeOpportunityRepository
from tests.test_feed_api import FEED, ITEM

OPPORTUNITY_ID = "00000000-0000-4000-8000-0000000000bb"
MARK = f"/api/v1/opportunities/{OPPORTUNITY_ID}/mark"
NOW = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)


def fixed_now(client: TestClient, now: datetime = NOW) -> None:
    client.app.dependency_overrides[current_time] = lambda: now  # type: ignore[attr-defined]


def test_mark_requires_login(client: TestClient) -> None:
    assert client.put(MARK, json={"mark": "interested"}).status_code == 401
    assert client.delete(MARK).status_code == 401


def test_mark_and_change(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    fixed_now(client)
    feed.openable.add(OPPORTUNITY_ID)
    res = client.put(MARK, json={"mark": "interested"}, headers=auth)
    assert res.status_code == 200
    assert res.json() == {"mark": "interested", "marked_at": "2026-10-13T21:30:00+09:00"}
    fixed_now(client, NOW + timedelta(hours=1))
    res = client.put(MARK, json={"mark": "interested"}, headers=auth)  # 같은 표시는 처음 시각
    assert res.json() == {"mark": "interested", "marked_at": "2026-10-13T21:30:00+09:00"}
    res = client.put(MARK, json={"mark": "not_interested"}, headers=auth)  # 다른 표시로 바꾼다
    assert res.json() == {"mark": "not_interested", "marked_at": "2026-10-13T22:30:00+09:00"}
    assert feed.mark_calls == [
        (USER_ID, OPPORTUNITY_ID, mark, "테스트 학생")
        for mark in ("interested", "interested", "not_interested")
    ]
    assert feed.marks == {(USER_ID, OPPORTUNITY_ID): ("not_interested", NOW + timedelta(hours=1))}


def test_mark_hidden_or_unknown_opportunity_is_not_found(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    res = client.put(MARK, json={"mark": "interested"}, headers=auth)
    assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"
    assert res.json()["error"]["message"] == "공고를 찾을 수 없어요."


def test_mark_rejects_bad_input(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    feed.openable.add(OPPORTUNITY_ID)
    for body in ({"mark": "maybe"}, {"mark": None}, {}):
        res = client.put(MARK, json=body, headers=auth)
        assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_FAILED"
        assert "mark" in res.json()["error"]["details"]["fields"]
    res = client.put(
        "/api/v1/opportunities/not-a-uuid/mark", json={"mark": "interested"}, headers=auth
    )
    assert res.status_code == 422
    assert "opportunity_id" in res.json()["error"]["details"]["fields"]
    assert feed.mark_calls == []


def test_unmark_is_204_even_without_a_mark(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    feed.openable.add(OPPORTUNITY_ID)
    client.put(MARK, json={"mark": "interested"}, headers=auth)
    for _ in range(2):  # 두 번째는 지울 표시가 없다
        res = client.delete(MARK, headers=auth)
        assert res.status_code == 204 and res.content == b""
    assert feed.marks == {}
    assert feed.mark_calls[1:] == [(USER_ID, OPPORTUNITY_ID, None, None)] * 2
    res = client.delete("/api/v1/opportunities/not-a-uuid/mark", headers=auth)
    assert res.status_code == 422


def test_feed_passes_include_not_interested_and_my_mark(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    feed.items = [ITEM.model_copy(update={"my_mark": "not_interested"}), ITEM]
    res = client.get(FEED, params={"include_not_interested": "true"}, headers=auth)
    assert res.status_code == 200
    assert [item["my_mark"] for item in res.json()["items"]] == ["not_interested", None]
    client.get(FEED, headers=auth)
    assert [query.include_not_interested for query in feed.queries] == [True, False]
    res = client.get(FEED, params={"include_not_interested": "maybe"}, headers=auth)
    assert res.status_code == 422
    assert "include_not_interested" in res.json()["error"]["details"]["fields"]


def test_cursor_belongs_to_one_mark_view(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    """관심 없음 공고를 넣은 목록과 뺀 목록은 다른 목록이다. cursor를 섞어 쓰지 않는다."""
    cursor = encode_cursor(Cursor(scope=FeedQuery().scope(), value=None, id=ITEM.id))
    assert client.get(FEED, params={"cursor": cursor}, headers=auth).status_code == 200
    res = client.get(
        FEED, params={"cursor": cursor, "include_not_interested": "true"}, headers=auth
    )
    assert res.status_code == 422 and "cursor" in res.json()["error"]["details"]["fields"]
    assert FeedQuery(include_not_interested=True).scope() != FeedQuery().scope()
