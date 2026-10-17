"""GET /me, /me/profile, /me/consents, /auth/google/tokens 모델 (API 명세 v0.4 4장, web types/api.ts와 같은 이름)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.notifications import NotificationType

EnrollmentStatus = Literal["enrolled", "on_leave", "deferred_graduation", "graduated"]
# 지금 다니는(졸업했으면 마지막으로 다닌) 학위과정: 학부·석사·박사·석박사통합
DegreeProgram = Literal["bachelor", "master", "doctoral", "integrated"]
WelfareStatus = Literal["none", "near_poverty", "basic_livelihood"]
# 시도는 정식 이름만 받는다 (판정 엔진의 지역 비교 기준). 16곳 — 2026-07-01에 광주광역시와
# 전라남도가 전남광주통합특별시로 합쳐졌다. 통합 전 이름으로 저장한 프로필은 마이그레이션이 옮긴다.
RegionSido = Literal[
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "전남광주통합특별시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원특별자치도",
    "충청북도",
    "충청남도",
    "전북특별자치도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
]


class ProfileFields(BaseModel):
    department: str | None = Field(None, max_length=60)  # 학과 목록(GET /meta/departments)의 이름
    degree_program: DegreeProgram | None = None
    grade: int | None = Field(None, ge=1, le=6)
    enrollment_status: EnrollmentStatus | None = None
    semesters_completed: int | None = Field(None, ge=0, le=16)  # 마친 학기 수
    credits_total: float | None = Field(None, ge=0, le=200)
    credits_last_semester: float | None = Field(None, ge=0, le=30)
    gpa_total: float | None = Field(None, ge=0, le=4.5)
    gpa_last_semester: float | None = Field(None, ge=0, le=4.5)  # 직전학기 장학용 평점(F 포함)
    gpa_scale: float | None = Field(None, ge=4.0, le=4.5)
    birth_date: date | None = None
    military_service_months: int | None = Field(None, ge=0, le=60)
    region_sido: str | None = None  # 주민등록 주소 기준
    region_sigungu: str | None = Field(None, max_length=40)
    income_bracket: int | None = Field(None, ge=0, le=10)  # 학자금 지원구간, 0 = 기초·차상위
    median_income_pct: int | None = Field(None, ge=0, le=500)  # 기준 중위소득 % (가구)
    welfare_status: WelfareStatus | None = None
    is_international: bool | None = None  # 외국인 유학생 여부


class Profile(ProfileFields):
    gpa_scale: float = Field(4.5, ge=4.0, le=4.5)


class ProfilePatch(ProfileFields):
    """보낸 필드만 바꾸고, null을 보내면 지운다."""

    model_config = ConfigDict(extra="forbid")

    region_sido: RegionSido | None = None


PROFILE_FIELDS: tuple[str, ...] = tuple(Profile.model_fields)
COMPLETION_FIELDS: tuple[str, ...] = tuple(f for f in PROFILE_FIELDS if f != "gpa_scale")
# 선택 동의(소득·수급 정보)가 있어야 저장되는 항목. DB 제약 profiles_income_consent_chk와 같다
INCOME_FIELDS: tuple[str, ...] = ("income_bracket", "median_income_pct", "welfare_status")


def gpa_errors(profile: Profile) -> dict[str, str]:
    return {
        name: f"평점 만점({profile.gpa_scale})보다 클 수 없어요."
        for name in ("gpa_total", "gpa_last_semester")
        if (value := getattr(profile, name)) is not None and value > profile.gpa_scale
    }


class LmsSummary(BaseModel):
    status: Literal["active", "error", "disconnected"]
    last_synced_at: datetime | None


class ProfileCompletion(BaseModel):
    filled: int
    total: int


class Me(BaseModel):
    user_id: str
    display_name: str
    hyin_verified: bool
    calendar_connected: bool
    lms: LmsSummary | None
    profile_completion: ProfileCompletion
    consented: bool
    income_info_consented: bool
    unread_notifications: int


class Rejudged(BaseModel):
    changed: int
    eligible: int
    undetermined: int
    ineligible: int


class ProfileUpdateResponse(BaseModel):
    profile: Profile
    rejudged: Rejudged


class ConsentRequest(BaseModel):
    consent_version: str = Field(min_length=1, max_length=32)
    agree_terms: bool
    agree_privacy: bool
    agree_income_info: bool = False  # 소득·수급 정보 수집·이용 (선택)


class ConsentResult(BaseModel):
    terms_agreed_at: datetime
    privacy_agreed_at: datetime
    income_info_agreed_at: datetime | None
    consent_version: str


class IncomeConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agree_income_info: bool


class IncomeConsentResult(BaseModel):
    income_info_agreed_at: datetime | None


class GoogleTokensRequest(BaseModel):
    provider_token: str = Field(min_length=1)
    provider_refresh_token: str | None = None


class GoogleTokensResponse(BaseModel):
    calendar_connected: bool
    scope: str


# ── 설정 (P1, 명세 4장 `GET`·`PATCH /me/settings`) ───────────────────────────
# 알림 종류는 한 곳에서만 적는다(schemas/notifications.py). DB의 check 제약과 같은 일곱 가지다


class Settings(BaseModel):
    """알림·캘린더 설정. 행이 없으면 DB 기본값(푸시 켬·끈 종류 없음·LMS 자동 등록 켬)이다."""

    push_enabled: bool
    muted_notification_types: list[NotificationType]
    calendar_auto_lms: bool


class SettingsUpdate(BaseModel):
    """보낸 항목만 바꾼다. 아무 항목도 없으면 422다."""

    model_config = ConfigDict(extra="forbid")

    push_enabled: bool | None = None
    muted_notification_types: list[NotificationType] | None = None
    calendar_auto_lms: bool | None = None

    def changes(self) -> dict[str, Any]:
        return {name: value for name, value in self.model_dump().items() if value is not None}
