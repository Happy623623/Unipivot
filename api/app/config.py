from datetime import datetime, timedelta, timezone
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_KST = timezone(timedelta(hours=9))
# 처리방침 v0.2(학교 공지 링크를 적은 판)의 시행 시각. web/src/app/privacy/page.tsx의 EFFECTIVE와 같은 날이다
POLICY_V02_EFFECTIVE = datetime(2026, 11, 12, tzinfo=_KST)
# 처리방침 v0.3(주차학습 강의 수강 여부를 적은 판)의 시행 시각. web/src/app/privacy/page.tsx의 EFFECTIVE와 같은 날이다
POLICY_V03_EFFECTIVE = datetime(2026, 11, 28, tzinfo=_KST)
# 주차학습 강의 수강 여부를 적은 동의 문구의 버전(web lib/consent.ts의 CONSENT_VERSION). 이 버전 이상에 동의한
# 학생만 읽는다 — 옛 문구에 동의한 학생은 다시 동의할 때까지 읽지 않는다
LECTURE_CONSENT_VERSION = "2026-11-24"


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
    classify_model: str = "gemini-3.5-flash-lite"  # 과목 공지 갈래 나누기(F-53, 짧은 구조화 답)
    summary_model: str = "gemini-3.5-flash-lite"  # 강의자료 요약(F-15 축소판, 입력이 길다)
    # 강의자료 요약의 입력 토큰 상한(사용자 선택 10/21). 넘으면 요약하지 않고 413 MATERIAL_TOO_LONG이다
    material_max_tokens: int = 30_000
    # 웹 푸시 VAPID(F-33). 비면 푸시를 보내지 않고 알림함에만 쌓는다.
    # 키는 `uv run python -m app.push.keys`로 만든다 — 레포에 넣지 않는다
    vapid_private_key: str = ""
    vapid_subject: str = ""  # mailto: 또는 서비스 주소(푸시 서비스가 연락할 곳)
    extraction_max_reads: int = 4  # 요건 추출 읽기 도구 상한(PRD 14장 미결, W2–3에 확정)
    extraction_max_tokens: int = 150_000
    youth_api_key: str = ""  # 온통청년 OPEN API 인증키(청년정책 수집, app/youth)
    # 포스터·계획서 업로드(F-13)와 공지 첨부(F-54) 파일을 두는 Supabase Storage. 버킷은 대시보드에서
    # 비공개로 만든다. 키는 API Keys의 secret key(sb_secret_…)다. 환경 변수 이름은 SUPABASE_SECRET_KEY이고, 예전 이름
    # SUPABASE_SERVICE_ROLE_KEY도 그대로 읽는다(둘 다 있으면 새 이름). 예전 service_role JWT 키도 받는다
    supabase_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("supabase_secret_key", "supabase_service_role_key"),
    )
    supabase_storage_bucket: str = "uploads"
    # 마감일 캘린더 등록(F-32). Supabase Google 로그인에 쓰는 OAuth 앱의 값과 같아야 한다.
    # 비워 두면 access token(55분)이 만료된 뒤 다시 연결해야 한다(갱신을 못 한다)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # 시험용으로만 바꾼다(가짜 Google로 E2E를 돌릴 때)
    google_token_url: str = "https://oauth2.googleapis.com/token"
    google_revoke_url: str = "https://oauth2.googleapis.com/revoke"  # 연결 해제 때 권한 폐기(F-06)
    google_calendar_api_base: str = "https://www.googleapis.com/calendar/v3"
    # 비우면 SUPABASE_URL에서 만든다(https://<ref>.supabase.co/storage/v1)
    supabase_storage_base: str = ""
    # LearningX(Canvas) API. 시험용으로만 바꾼다(녹화 응답을 재생할 때)
    lms_api_base: str = "https://learning.hanyang.ac.kr"
    # /internal/* 호출에 쓰는 서비스 키(명세 12장의 X-Internal-Key). 비우면 그 경로가 모두 403이다
    internal_api_key: str = ""
    # 서버 안 스케줄러(app/scheduler.py) — 1분마다 예약표(job_schedule)를 본다. 꺼 두면 정기 작업은
    # /internal/jobs/*(tick 포함)로만 돈다. 바깥 크론이 tick을 불러도 예약표 덕에 작업마다 한 번만 돈다
    scheduler_enabled: bool = False
    # 학교 공지 링크 가져오기(B안, POST /notices/link). 학교가 멈춰 달라고 하면 false로 두고 deploy한다 —
    # 새로 읽기만 멈추고(409 NOTICE_LINK_DISABLED) 이미 가져온 공지는 그대로 준다
    notice_link_enabled: bool = True
    # 링크 가져오기를 여는 시각. 그 전에는 새로 읽지 않는다(409 NOTICE_LINK_DISABLED) — 이 기능을 적은 처리방침이
    # 시행되기 전에 붙인 공지 주소를 남기지 않는다. 로컬에서 미리 보려면 지난 시각을 넣는다(배포에는 옮기지 않는다)
    notice_link_opens_at: datetime | None = POLICY_V02_EFFECTIVE
    # 주차학습 강의를 들었는지 읽기(11/24, LMS 동기화). 학교가 멈춰 달라고 하면 false로 두고 deploy한다 —
    # 새로 읽지 않고 저장해 둔 것만 보인다
    lecture_progress_enabled: bool = True
    # 읽기 시작하는 시각. 그 전에는 읽지 않는다 — 이 처리를 적은 처리방침(v0.3)이 시행되기 전이다.
    # 로컬에서 미리 보려면 지난 시각을 넣는다(배포에는 옮기지 않는다)
    lecture_progress_opens_at: datetime | None = POLICY_V03_EFFECTIVE

    @field_validator("notice_link_opens_at", "lecture_progress_opens_at")
    @classmethod
    def _kst_if_no_offset(cls, value: datetime | None) -> datetime | None:
        """시간대를 빼고 적었으면 KST로 본다(서버 시계와 견줄 수 있게)."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=_KST)
        return value

    @property
    def storage_base_url(self) -> str:
        """Storage REST 주소. 시험용 주소를 넣었으면 그것을 쓴다."""
        if self.supabase_storage_base:
            return self.supabase_storage_base.rstrip("/")
        return f"{self.supabase_url.rstrip('/')}/storage/v1" if self.supabase_url else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
