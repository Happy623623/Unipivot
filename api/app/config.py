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
    guide_model: str = "gemini-3.5-flash-lite"  # 준비하기의 서류 안내(짧은 구조화 답)
    extraction_max_reads: int = 4  # 요건 추출 읽기 도구 상한(PRD 14장 미결, W2–3에 확정)
    extraction_max_tokens: int = 150_000
    youth_api_key: str = ""  # 온통청년 OPEN API 인증키(청년정책 수집, app/youth)
    # 포스터·계획서 업로드 파일을 두는 Supabase Storage(F-13). 버킷은 대시보드에서 비공개로 만든다
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "uploads"
    # 마감일 캘린더 등록(F-32). Supabase Google 로그인에 쓰는 OAuth 앱의 값과 같아야 한다.
    # 비워 두면 access token(55분)이 만료된 뒤 다시 연결해야 한다(갱신을 못 한다)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # 시험용으로만 바꾼다(가짜 Google로 E2E를 돌릴 때)
    google_token_url: str = "https://oauth2.googleapis.com/token"
    google_calendar_api_base: str = "https://www.googleapis.com/calendar/v3"
    # 비우면 SUPABASE_URL에서 만든다(https://<ref>.supabase.co/storage/v1)
    supabase_storage_base: str = ""
    # LearningX(Canvas) API. 시험용으로만 바꾼다(녹화 응답을 재생할 때)
    lms_api_base: str = "https://learning.hanyang.ac.kr"
    # /internal/* 호출에 쓰는 서비스 키(명세 12장의 X-Internal-Key). 비우면 그 경로가 모두 403이다
    internal_api_key: str = ""

    @property
    def storage_base_url(self) -> str:
        """Storage REST 주소. 시험용 주소를 넣었으면 그것을 쓴다."""
        if self.supabase_storage_base:
            return self.supabase_storage_base.rstrip("/")
        return f"{self.supabase_url.rstrip('/')}/storage/v1" if self.supabase_url else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
