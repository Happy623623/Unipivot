"""GET /opportunities/{id}/alternatives(F-23). 저장소는 가짜다. SQL은 test_recommend_db.py가 본다."""

from fastapi.testclient import TestClient

from tests.conftest import USER_ID
from tests.fakes import FakeOpportunityRepository
from tests.test_feed_api import ITEM

TARGET = "00000000-0000-4000-8000-0000000000bb"
URL = f"/api/v1/opportunities/{TARGET}/alternatives"


def test_alternatives_require_login(client: TestClient) -> None:
    assert client.get(URL).status_code == 401


def test_alternatives_refresh_judgments_then_list_items(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    feed.alternative_items[TARGET] = [ITEM]
    res = client.get(URL, headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert [item["id"] for item in body["items"]] == [ITEM.id]
    assert body["items"][0]["eligibility"]["display_status"] == "missing_info"  # 피드 아이템 모양
    # 후보(피드의 활성 공고)를 먼저 다시 판정한 뒤 고른다. 기준 공고는 저장소가 그 자리에서 판정한다
    assert feed.refreshes == [(USER_ID, False, False)]
    assert feed.alternative_calls == [(USER_ID, TARGET, 1)]


def test_no_alternatives_is_an_empty_list(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    feed.alternative_items[TARGET] = []  # 지원 어려움이 아니거나 고를 공고가 없다
    res = client.get(URL, headers=auth)
    assert (res.status_code, res.json()) == (200, {"items": []})


def test_unopenable_opportunity_is_not_found(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    res = client.get(URL, headers=auth)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_malformed_id_is_a_validation_error(client: TestClient, auth: dict[str, str]) -> None:
    res = client.get("/api/v1/opportunities/not-a-uuid/alternatives", headers=auth)
    assert res.status_code == 422
    assert "opportunity_id" in res.json()["error"]["details"]["fields"]
