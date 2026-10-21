"""설정 이름(app/config.py). 저장소 키는 새 이름 SUPABASE_SECRET_KEY로 읽고, 예전 이름 SUPABASE_SERVICE_ROLE_KEY도 읽는다.

키 값은 시험용 모양만 쓴다(실제 키가 아니다).
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.uploads.storage import storage_settings_problem

NEW = "sb_secret_" + "Nw5" * 10 + "a"  # 시험용 값이다
OLD = "sb_secret_" + "Od3" * 10 + "b"
PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"


@pytest.fixture(autouse=True)
def no_storage_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """셸에 저장소 설정이 있어도 이 시험은 그것과 상관없이 돈다."""
    for name in (
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_URL",
        "SUPABASE_STORAGE_BASE",
        "SUPABASE_STORAGE_BUCKET",
    ):
        monkeypatch.delenv(name, raising=False)


def test_the_new_name_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_SECRET_KEY", NEW)
    assert Settings(_env_file=None).supabase_secret_key == NEW  # type: ignore[call-arg]


def test_the_old_name_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """api/.env를 고치지 않아도 그대로 돈다."""
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", OLD)
    settings = Settings(_env_file=None, supabase_url=PROJECT_URL)  # type: ignore[call-arg]
    assert settings.supabase_secret_key == OLD
    assert storage_settings_problem(settings) is None


def test_the_new_name_wins_when_both_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_SECRET_KEY", NEW)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", OLD)
    assert Settings(_env_file=None).supabase_secret_key == NEW  # type: ignore[call-arg]


def test_the_env_file_reads_either_name(tmp_path: Path) -> None:
    old = tmp_path / "old.env"
    old.write_text(f"SUPABASE_SERVICE_ROLE_KEY={OLD}\n")
    new = tmp_path / "new.env"
    new.write_text(f"SUPABASE_SECRET_KEY={NEW}\n")
    assert Settings(_env_file=old).supabase_secret_key == OLD  # type: ignore[call-arg]
    assert Settings(_env_file=new).supabase_secret_key == NEW  # type: ignore[call-arg]


def test_sources_keep_their_order_whichever_name_they_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """환경 변수가 .env를 이기고, 코드에서 준 값이 환경 변수를 이긴다(이름이 달라도). pydantic-settings 2.14부터 맞다."""
    env_file = tmp_path / ".env"
    env_file.write_text(f"SUPABASE_SECRET_KEY={NEW}\n")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", OLD)
    assert Settings(_env_file=env_file).supabase_secret_key == OLD  # type: ignore[call-arg]
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", NEW)
    given = Settings(_env_file=None, supabase_service_role_key=OLD)  # type: ignore[call-arg]
    assert given.supabase_secret_key == OLD


def test_the_problem_text_names_the_new_variable() -> None:
    """고칠 점 문구는 새 이름으로 말한다(예전 이름으로 넣었어도 같은 값이다)."""
    found = storage_settings_problem(Settings(_env_file=None, supabase_url=PROJECT_URL))  # type: ignore[call-arg]
    assert found is not None and "SUPABASE_SECRET_KEY" in found and "SERVICE_ROLE" not in found
