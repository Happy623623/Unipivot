from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.crypto import decrypt
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeMetaRepository, FakeProfileRepository

CONSENT = {"consent_version": "2026-10-07", "agree_terms": True, "agree_privacy": True}


def consent(client: TestClient, auth: dict[str, str], **extra: bool) -> None:
    res = client.post("/api/v1/me/consents", json={**CONSENT, **extra}, headers=auth)
    assert res.status_code == 200


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_me_requires_login(client: TestClient) -> None:
    res = client.get("/api/v1/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_or_forged_token_is_rejected(client: TestClient) -> None:
    for token in (
        make_token(expires_in=-10),
        make_token(secret="forged-secret-forged-secret-forged"),
    ):
        res = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_first_me_creates_profile(client: TestClient, auth: dict[str, str]) -> None:
    body = client.get("/api/v1/me", headers=auth).json()
    assert body["user_id"] == USER_ID
    assert body["display_name"] == "테스트 학생"
    assert (body["consented"], body["income_info_consented"], body["calendar_connected"]) == (
        False,
        False,
        False,
    )
    assert body["profile_completion"] == {"filled": 0, "total": 16}


def test_profile_update_needs_consent(client: TestClient, auth: dict[str, str]) -> None:
    client.get("/api/v1/me", headers=auth)
    res = client.patch("/api/v1/me/profile", json={"grade": 3}, headers=auth)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert res.json()["error"]["details"] == {"consent": "terms_privacy"}


def test_consent_requires_both(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post("/api/v1/me/consents", json={**CONSENT, "agree_privacy": False}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {"agree_privacy": "필수 항목이에요."}


def test_onboarding_flow(client: TestClient, auth: dict[str, str]) -> None:
    res = client.post("/api/v1/me/consents", json=CONSENT, headers=auth)
    assert res.status_code == 200
    assert res.json()["consent_version"] == "2026-10-07"
    assert res.json()["income_info_agreed_at"] is None  # 선택 동의는 하지 않음

    patch = {
        "department": "인공지능학과",
        "grade": 3,
        "gpa_last_semester": 3.9,
        "is_international": False,
    }
    res = client.patch("/api/v1/me/profile", json=patch, headers=auth)
    assert res.status_code == 200
    assert (res.json()["profile"]["grade"], res.json()["profile"]["is_international"]) == (3, False)
    assert res.json()["rejudged"] == {
        "changed": 0,
        "eligible": 0,
        "undetermined": 0,
        "ineligible": 0,
    }

    me = client.get("/api/v1/me", headers=auth).json()
    assert me["consented"] is True
    assert me["profile_completion"]["filled"] == 4

    client.patch("/api/v1/me/profile", json={"grade": None}, headers=auth)  # null이면 지운다
    assert client.get("/api/v1/me/profile", headers=auth).json()["grade"] is None


def test_profile_validation(client: TestClient, auth: dict[str, str]) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"grade": 9}, headers=auth)
    assert res.status_code == 422
    assert "grade" in res.json()["error"]["details"]["fields"]

    res = client.patch(
        "/api/v1/me/profile", json={"gpa_scale": 4.3, "gpa_total": 4.4}, headers=auth
    )
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {
        "gpa_total": "평점 만점(4.3)보다 클 수 없어요."
    }

    res = client.patch("/api/v1/me/profile", json={"nickname": "x"}, headers=auth)
    assert res.status_code == 422  # 명세에 없는 필드는 받지 않는다

    res = client.patch("/api/v1/me/profile", json={"department": "없는학과"}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {"department": "학과 목록에서 골라 주세요."}

    res = client.patch("/api/v1/me/profile", json={"region_sido": "경기"}, headers=auth)
    assert res.status_code == 422  # 시도는 정식 이름만 (경기도)


def test_department_removed_from_list_is_kept(
    client: TestClient, auth: dict[str, str], meta: FakeMetaRepository
) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"department": "경영학부"}, headers=auth)
    assert res.status_code == 200
    meta.departments = [d for d in meta.departments if d.name != "경영학부"]  # 학과가 목록에서 빠짐

    body = {"department": "경영학부", "grade": 2}  # 화면은 프로필 전체를 다시 보낸다
    res = client.patch("/api/v1/me/profile", json=body, headers=auth)
    assert res.status_code == 200
    assert (res.json()["profile"]["department"], res.json()["profile"]["grade"]) == ("경영학부", 2)
    res = client.patch("/api/v1/me/profile", json={"department": "인공지능학과"}, headers=auth)
    assert res.status_code == 200  # 바꿀 때는 목록에 있는 학과로


def test_income_needs_optional_consent(
    client: TestClient, auth: dict[str, str], repo: FakeProfileRepository
) -> None:
    consent(client, auth)
    res = client.patch("/api/v1/me/profile", json={"income_bracket": 6}, headers=auth)
    assert res.status_code == 403
    assert res.json()["error"]["details"] == {"consent": "income_info"}
    res = client.patch("/api/v1/me/profile", json={"income_bracket": None}, headers=auth)
    assert res.status_code == 200  # 지우는 것은 동의 없이도 된다

    res = client.patch("/api/v1/me/consents", json={"agree_income_info": True}, headers=auth)
    assert res.status_code == 200 and res.json()["income_info_agreed_at"] is not None
    res = client.patch(
        "/api/v1/me/profile", json={"income_bracket": 6, "welfare_status": "none"}, headers=auth
    )
    assert res.status_code == 200
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is True

    res = client.patch("/api/v1/me/consents", json={"agree_income_info": False}, headers=auth)
    assert res.status_code == 200 and res.json()["income_info_agreed_at"] is None
    profile = client.get("/api/v1/me/profile", headers=auth).json()
    assert (profile["income_bracket"], profile["welfare_status"]) == (None, None)  # 철회하면 지운다
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is False


def test_income_consent_order(client: TestClient, auth: dict[str, str]) -> None:
    client.get("/api/v1/me", headers=auth)
    res = client.patch("/api/v1/me/consents", json={"agree_income_info": True}, headers=auth)
    assert res.status_code == 403  # 필수 동의가 먼저
    assert res.json()["error"]["details"] == {"consent": "terms_privacy"}

    consent(client, auth, agree_income_info=True)  # 온보딩에서 선택 동의까지 한 번에
    assert client.get("/api/v1/me", headers=auth).json()["income_info_consented"] is True
    res = client.patch(
        "/api/v1/me/consents", json={"agree_income_info": True, "extra": 1}, headers=auth
    )
    assert res.status_code == 422


def test_departments(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get("/api/v1/meta/departments").status_code == 401
    res = client.get("/api/v1/meta/departments", headers=auth)
    assert res.status_code == 200
    assert res.json()["items"][0] == {
        "name": "인공지능학과",
        "college": "소프트웨어융합대학",
        "field_group": "공학계열",
    }


def test_events(client: TestClient, auth: dict[str, str], meta: FakeMetaRepository) -> None:
    res = client.post("/api/v1/events", json={"event": "app_open"}, headers=auth)
    assert (res.status_code, res.content) == (204, b"")
    assert meta.events == [(USER_ID, "app_open", None)]

    res = client.post("/api/v1/events", json={"event": "lms_connected"}, headers=auth)
    assert res.status_code == 422  # 서버가 직접 기록하는 이벤트
    res = client.post(
        "/api/v1/events",
        json={"event": "profile_prompt_shown", "opportunity_id": "not-a-uuid"},
        headers=auth,
    )
    assert res.status_code == 422

    opportunity_id = "00000000-0000-4000-8000-0000000000aa"
    body = {"event": "profile_prompt_shown", "opportunity_id": opportunity_id}
    assert client.post("/api/v1/events", json=body, headers=auth).status_code == 204
    assert meta.events[-1] == (USER_ID, "profile_prompt_shown", UUID(opportunity_id))


def test_google_tokens(
    client: TestClient, auth: dict[str, str], repo: FakeProfileRepository, settings: Settings
) -> None:
    res = client.post("/api/v1/auth/google/tokens", json={"provider_token": "ya29.a"}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "GOOGLE_REFRESH_TOKEN_MISSING"

    body = {"provider_token": "ya29.a", "provider_refresh_token": "1//refresh"}
    res = client.post("/api/v1/auth/google/tokens", json=body, headers=auth)
    assert res.status_code == 200
    assert res.json() == {"calendar_connected": True, "scope": "calendar.events"}

    stored = repo.tokens[USER_ID]["refresh_token"]
    assert stored != "1//refresh"  # 암호화해서 저장한다
    assert decrypt(stored, settings.token_encryption_key) == "1//refresh"
    assert client.get("/api/v1/me", headers=auth).json()["calendar_connected"] is True
