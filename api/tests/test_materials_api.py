"""강의자료 요약 API(F-15)의 인증·입력 검사. 실제 흐름(저장소 → 모델 → DB)은 test_materials_db.py가 본다."""

from fastapi.testclient import TestClient

from app.materials.service import get_material_service
from app.repositories.materials import get_material_repos

FILE_ID = "00000000-0000-4000-8000-0000000000f5"


def test_the_material_endpoints_require_login(client: TestClient) -> None:
    assert client.post("/api/v1/materials", json={"file_id": FILE_ID}).status_code == 401
    assert client.get(f"/api/v1/materials/{FILE_ID}").status_code == 401
    assert client.get("/api/v1/materials").status_code == 401


def test_a_malformed_request_is_a_validation_error(
    client: TestClient, auth: dict[str, str]
) -> None:
    # 입력이 틀리면 DB·저장소를 쓰기 전에 422다(DB 없는 시험이라 쓰면 503이다 — 그래서 대역을 끼운다)
    client.app.dependency_overrides[get_material_repos] = lambda: None  # type: ignore[attr-defined]
    client.app.dependency_overrides[get_material_service] = lambda: None  # type: ignore[attr-defined]
    for body in ({}, {"file_id": "파일"}, {"file_id": FILE_ID, "pages": [1, 2]}):
        response = client.post("/api/v1/materials", json=body, headers=auth)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert client.get("/api/v1/materials/파일", headers=auth).status_code == 422
    assert client.get("/api/v1/materials", params={"limit": 51}, headers=auth).status_code == 422
