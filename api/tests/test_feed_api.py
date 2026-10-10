"""GET /opportunities와 프로필 저장 뒤 다시 판정(S1-5). 저장소는 가짜다. SQL은 test_feed_db.py가 본다."""

import base64
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.eligibility import KST
from app.repositories.opportunities import (
    Cursor,
    FeedQuery,
    decode_cursor,
    display_status,
    encode_cursor,
)
from app.schemas.opportunities import (
    CATEGORIES,
    ELIGIBILITY_STATUSES,
    SOURCE_TYPES,
    FeedCounts,
    FeedEligibility,
    OpportunityItem,
)
from tests.conftest import USER_ID
from tests.fakes import FakeOpportunityRepository, FakeProfileRepository

FEED = "/api/v1/opportunities"
CONSENT = {"consent_version": "2026-10-07", "agree_terms": True, "agree_privacy": True}
ITEM = OpportunityItem(
    id="00000000-0000-4000-8000-0000000000aa",
    title="2026-2 한양브레인 장학금",
    organizer="학생지원팀",
    category="scholarship",
    source_type="school_notice",
    deadline_at=datetime(2026, 10, 15, 23, 59, tzinfo=KST),  # 저장소는 KST로 바꿔 준다
    d_day=3,
    easy_summary="직전학기 성적이 좋은 학생에게 등록금 일부를 감면해 줘요.",
    eligibility=FeedEligibility(
        status="undetermined",
        display_status="missing_info",
        summary="직전학기 이수학점 입력 필요",
        missing_fields=["credits_last_semester"],
    ),
    needs_review=False,
    uploaded_by_me=False,
    course_name=None,
    prepared=False,
    is_new=True,
)


def test_feed_requires_login(client: TestClient) -> None:
    assert client.get(FEED).status_code == 401


def test_feed_passes_filters_and_returns_counts(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    feed.items, feed.next_cursor = [ITEM], "다음"
    feed.counts = FeedCounts(
        eligible=8,
        new_eligible=2,
        undetermined=3,
        missing_info=2,
        needs_review=1,
        ineligible=9,
        deadline_soon=2,
    )
    res = client.get(
        FEED,
        params={
            "eligibility": "eligible, undetermined",
            "category": "scholarship,etc,scholarship",
            "source_type": "school_notice",
            "sort": "recent",
            "include_expired": "true",
            "limit": 5,
        },
        headers=auth,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["next_cursor"] == "다음" and body["counts"]["ineligible"] == 9
    assert body["items"][0]["deadline_at"] == "2026-10-15T23:59:00+09:00"
    assert body["items"][0]["eligibility"]["display_status"] == "missing_info"
    assert feed.refreshes == [(USER_ID, False, True)]  # 읽기 전에 낡은 판정만 다시 계산
    assert feed.queries == [
        FeedQuery(
            eligibility=frozenset({"eligible", "undetermined"}),
            categories=("scholarship", "etc"),
            source_types=("school_notice",),
            sort="recent",
            include_expired=True,
            limit=5,
        )
    ]
    client.get(FEED, params={"eligibility": "ineligible,all"}, headers=auth)
    assert feed.queries[-1].eligibility is None  # all이 있으면 거르지 않는다


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"eligibility": "maybe"}, "eligibility"),
        ({"category": "food"}, "category"),
        ({"source_type": "blog"}, "source_type"),
        ({"sort": "popular"}, "sort"),
        ({"limit": 0}, "limit"),
        ({"limit": 51}, "limit"),
        ({"cursor": "not-a-cursor"}, "cursor"),
    ],
)
def test_feed_rejects_bad_parameters(
    client: TestClient, auth: dict[str, str], params: dict[str, object], field: str
) -> None:
    res = client.get(FEED, params=params, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_FAILED"
    assert field in res.json()["error"]["details"]["fields"]


def test_feed_reports_all_bad_filters_at_once(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    params = {"eligibility": "maybe", "category": "food", "source_type": "blog", "cursor": "zz"}
    res = client.get(FEED, params=params, headers=auth)
    assert res.status_code == 422
    assert set(res.json()["error"]["details"]["fields"]) == set(params)
    assert feed.refreshes == []  # 잘못된 요청은 판정을 건드리지 않는다


def test_cursor_belongs_to_one_list(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    home = FeedQuery(eligibility=frozenset({"eligible", "undetermined"}), categories=("etc",))
    cursor = encode_cursor(Cursor(scope=home.scope(), value=None, id=ITEM.id))
    same = {"eligibility": "undetermined,eligible", "category": "etc", "cursor": cursor}
    assert client.get(FEED, params=same, headers=auth).status_code == 200  # 순서는 상관없다
    assert feed.queries[-1].cursor == decode_cursor(cursor)
    for changed in (
        {**same, "sort": "recent"},
        {**same, "category": "etc,contest"},
        {**same, "eligibility": "eligible"},
        {**same, "include_expired": "true"},
    ):
        res = client.get(FEED, params=changed, headers=auth)
        assert res.status_code == 422 and "cursor" in res.json()["error"]["details"]["fields"]


def test_cursor_round_trip_and_errors() -> None:
    moment = datetime(2026, 10, 15, 14, 59, 0, 123456, tzinfo=UTC)
    scope = FeedQuery().scope()
    for cursor in (
        Cursor(scope=scope, value=moment, id=ITEM.id),
        Cursor(scope=scope, value=None, id=ITEM.id),  # 정렬 값이 없는 행(상시 공고)까지 온 경우
    ):
        assert decode_cursor(encode_cursor(cursor)) == cursor
    no_scope = {"v": None, "id": ITEM.id}
    bad = [
        "!!!",
        encode_cursor(Cursor(scope=scope, value=moment, id=ITEM.id))[:-3],
        base64.urlsafe_b64encode(json.dumps(no_scope).encode()).decode(),
        encode_cursor(Cursor(scope=scope, value=moment, id="12345")),
        encode_cursor(Cursor(scope=scope, value=datetime(2026, 10, 15), id=ITEM.id)),
    ]
    for text in bad:
        with pytest.raises(ValueError):
            decode_cursor(text)
    assert FeedQuery(sort="recent").scope() != scope
    everything = FeedQuery(
        eligibility=frozenset(ELIGIBILITY_STATUSES),
        categories=CATEGORIES,
        source_types=SOURCE_TYPES,
    )
    assert everything.scope() == scope  # 모든 값을 고른 필터는 필터 없음과 같은 목록이다
    assert [display_status(s, m) for s, m in [("undetermined", ["age"]), ("undetermined", [])]] == [
        "missing_info",
        "needs_review",
    ]


def test_profile_save_and_income_withdrawal_rejudge(
    client: TestClient,
    auth: dict[str, str],
    repo: FakeProfileRepository,
    feed: FakeOpportunityRepository,
) -> None:
    assert client.post("/api/v1/me/consents", json=CONSENT, headers=auth).status_code == 200
    assert feed.refreshes == []  # 첫 동의: 지울 소득 값이 없다
    feed.changed = 2
    feed.counts = feed.counts.model_copy(update={"eligible": 5, "ineligible": 1})
    res = client.patch("/api/v1/me/profile", json={"grade": 3}, headers=auth)
    assert res.json()["rejudged"] == {
        "changed": 2,
        "eligible": 5,
        "undetermined": 0,
        "ineligible": 1,
    }
    assert repo.locks == [USER_ID]  # 동의 확인 전에 프로필 행을 잠근다
    assert feed.refreshes[-1] == (USER_ID, True, False)  # 활성 공고를 모두 다시 판정
    for same in ({}, {"grade": 3}):  # 바뀐 값이 없으면 낡은 판정만
        client.patch("/api/v1/me/profile", json=same, headers=auth)
        assert feed.refreshes[-1] == (USER_ID, False, False)

    feed.refreshes.clear()
    client.patch("/api/v1/me/consents", json={"agree_income_info": True}, headers=auth)
    assert feed.refreshes == []  # 동의만으로는 값이 바뀌지 않는다
    client.patch("/api/v1/me/consents", json={"agree_income_info": False}, headers=auth)
    assert feed.refreshes == [(USER_ID, True, False)]

    client.patch("/api/v1/me/consents", json={"agree_income_info": True}, headers=auth)
    client.post("/api/v1/me/consents", json=CONSENT, headers=auth)  # 다시 동의하며 선택 동의를 뺌
    assert feed.refreshes[-1] == (USER_ID, True, False)
