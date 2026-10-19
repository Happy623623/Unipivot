import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.repositories.meta import get_meta_repo
from app.repositories.opportunities import get_opportunity_repo
from app.repositories.profiles import get_profile_repo
from app.runtime import event_loop_factory
from tests.fakes import FakeMetaRepository, FakeOpportunityRepository, FakeProfileRepository

JWT_SECRET = "unit-test-jwt-secret-not-used-anywhere-else"
USER_ID = "00000000-0000-4000-8000-000000000001"


def pytest_configure(config: pytest.Config) -> None:
    """시험은 개발자 PC의 `api/.env`를 읽지 않는다. 환경 변수(CI의 DATABASE_URL 등)는 그대로 읽는다.

    CI에는 `.env`가 없다. PC에서 `api` 폴더에 들어가 돌리면 `Settings()`가 그 파일을 읽어서, "키가 없을
    때" 시험(온통청년·Google·스케줄러)이 PC에서만 깨진다(10/19 #60에서 3건). 시험 파일을 모으기 전에
    끄려고 fixture가 아니라 이 훅에서 끈다(모듈을 읽을 때 만드는 설정도 있다).
    """
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()


def make_token(
    sub: str = USER_ID, secret: str = JWT_SECRET, expires_in: int = 3600, **claims: Any
) -> str:
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + expires_in,
        "email": "student@example.com",
        "user_metadata": {"full_name": "테스트 학생"},
        **claims,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def anyio_backend() -> str | tuple[str, dict[str, Any]]:
    factory = event_loop_factory()  # Windows: 명령줄 도구와 같은 Selector 루프(psycopg 비동기 연결)
    return ("asyncio", {"loop_factory": factory}) if factory else "asyncio"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="",  # 단위 테스트는 DB 없이 돈다
        supabase_jwt_secret=JWT_SECRET,
        token_encryption_key=Fernet.generate_key().decode(),
    )


@pytest.fixture
def repo() -> FakeProfileRepository:
    return FakeProfileRepository()


@pytest.fixture
def meta() -> FakeMetaRepository:
    return FakeMetaRepository()


@pytest.fixture
def feed() -> FakeOpportunityRepository:
    return FakeOpportunityRepository()


@pytest.fixture
def client(
    settings: Settings,
    repo: FakeProfileRepository,
    meta: FakeMetaRepository,
    feed: FakeOpportunityRepository,
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_profile_repo] = lambda: repo
    app.dependency_overrides[get_meta_repo] = lambda: meta
    app.dependency_overrides[get_opportunity_repo] = lambda: feed
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}
