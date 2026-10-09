from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """api/.env에서 읽는 설정. 각 값의 의미는 .env.example 참고."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    token_encryption_key: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]
    api_prefix: str = "/api/v1"
    # Gemini 플랫폼(Google Cloud). 모델 ID는 단가표(app/pricing.py) 키와 같아야 한다
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    extraction_model: str = "gemini-3.8-flash"
    vision_model: str = "gemini-3.8-flash"
    extraction_max_reads: int = 4  # 요건 추출 읽기 도구 상한(PRD 14장 미결, W2–3에 확정)
    extraction_max_tokens: int = 150_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
