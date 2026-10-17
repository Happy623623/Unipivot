# 알림·캘린더 설정 — `GET`·`PATCH /me/settings`

> 📝 기준: API 명세 v0.4 4장 `GET`·`PATCH /me/settings` · PRD v0.9 F-45(알림 설정)·F-33 · ERD v0.9 `user_settings` · 2026-10-17
>
> 먼저 합친 것: `과목상세_구현.md`(F-14)

설정 표는 처음부터 있었고 **쓰는 쪽(알림 만들기·캘린더 자동 등록)은 이미 그 값을 본다.** 그런데 **바꿀 방법이 없었다.** 그 구멍을 메운다 — 다음 PR(LMS 과제 캘린더 자동 등록)이 "끌 수 있어야" 성립하기 때문에 먼저 넣는다.

- `GET /me/settings` — 푸시 · 끈 알림 종류 · LMS 과제 자동 캘린더 등록
- `PATCH /me/settings` — 보낸 항목만 바꾼다. 설정 행이 없으면 기본값으로 만들고 그 위에 얹는다

DB 변경 없음(`user_settings`는 ERD v0.7부터 있다). 기본값도 그대로 둔다 — 푸시 켬 · 끈 종류 없음 · **LMS 자동 등록 켬**.

## 정한 것

1. **설정 행이 없어도 답이 있다.** 온보딩만 한 사용자는 `user_settings` 행이 없다. 그때 `GET`은 DB 기본값(켬·없음·켬)을 그대로 돌려준다 — 404가 아니다.
2. **`PATCH`는 보낸 항목만 바꾼다.** 행이 없으면 먼저 기본값으로 만들고(`insert … on conflict do nothing`) 그 위에 보낸 항목만 얹는다. 두 문장을 한 트랜잭션에서 돌린다.
3. **빈 요청·모르는 항목·모르는 알림 종류는 422.** 빈 목록(`[]`)은 "모두 켜기"라는 뜻의 **정상 변경**이다(바꿀 것이 없는 것과 다르다).
4. **알림 종류 목록은 한 곳에만 적는다.** `schemas/notifications.py`의 `NotificationType`을 가져다 쓴다 — 설정 쪽에 같은 목록을 또 적으면 DB의 check 제약과 어긋나는 날이 온다. 둘이 같은지 보는 테스트를 넣었다.
5. **`calendar_auto_lms`는 기본 켬을 유지한다**(ERD 주석·명세 그대로). 끄면 **이후** 새 과제만 캘린더에 넣지 않고, 이미 넣은 일정은 건드리지 않는다.

## 레포에 넣는 법

````text
새 브랜치 feat/F-45-settings-api를 main에서 따고, docs/설정API_구현.md(방금 받은 파일)를 docs/에 넣은 뒤 아래를 해 줘.

[1] 문서 맨 아래 "코드" 절의 파일 6개를 그대로 만들거나 덮어써 줘. `#### `경로`` 아래 코드 블록이 그 파일의 전체 내용이다.
    새 파일: api/tests/test_settings_db.py
    바뀌는 파일: api/app/schemas/me.py · api/app/repositories/profiles.py · api/app/routers/me.py · api/tests/fakes.py · api/tests/test_api.py

[2] "문서에 반영하기" 절대로 docs/API_명세_v0.4.md를 고쳐 줘(1곳).

[3] DB 변경 없다. 마이그레이션을 만들지 말고 `npx supabase db push`도 하지 마.

[4] 검사: api> uv run ruff check . && uv run ruff format --check . && uv run pytest
    로컬은 DB 테스트를 건너뛴다(`847 passed, 249 skipped` 근처). CI에서는 `1096 passed`다. web은 바뀐 게 없다.

[5] 통과하면 "feat(F-45): 알림·캘린더 설정 API" 커밋으로 PR을 올려 줘. 본문에 새 엔드포인트(GET·PATCH /me/settings)와 "DB 변경 없음"을 적어 줘.
````


## 합친 뒤 확인

```bash
curl localhost:8000/api/v1/me/settings -H "Authorization: Bearer $TOKEN"
# → {"push_enabled":true,"muted_notification_types":[],"calendar_auto_lms":true}

curl -X PATCH localhost:8000/api/v1/me/settings -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"calendar_auto_lms": false}'
# → push_enabled는 그대로 true

curl -X PATCH localhost:8000/api/v1/me/settings -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"muted_notification_types": ["new_material"]}'
# → 앞서 끈 calendar_auto_lms는 false로 남아 있다

curl -i -X PATCH localhost:8000/api/v1/me/settings -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{}'
# → 422 VALIDATION_FAILED
```

## 구조

```text
api/app/schemas/me.py            Settings · SettingsUpdate(보낸 항목만 추리는 changes())
api/app/repositories/profiles.py get_settings(행이 없으면 기본값) · update_settings(만들고 얹기)
api/app/routers/me.py            GET·PATCH /me/settings
api/tests/test_settings_db.py    실제 스키마에 대고(기본값·쌓임·check 제약·격리)
```

## 확인한 것

| 확인 | 결과 |
| --- | --- |
| api 테스트 | DB 없이 `847 passed, 249 skipped`, DB를 붙이면 `1096 passed`. 새 테스트 13개(API 6 · DB 7) |
| API | 기본값 응답 · 보낸 항목만 바뀜(앞서 바꾼 값이 남음) · 빈 요청 422 · 모르는 알림 종류 422 · **아는 항목과 모르는 항목을 섞어 보내도 422**(모르는 칸을 조용히 버리지 않는다) · 두 경로 모두 로그인 필요 |
| DB(실제 스키마) | 행이 없을 때 기본값 · 첫 변경이 행을 만들고 나머지는 기본값 유지 · 변경이 쌓임 · 빈 목록으로 "끈 종류 없음"으로 되돌림 · **모르는 종류는 DB check 제약이 거절**(라우터와 DB가 같은 목록인지 확인) · 스키마의 일곱 종류가 모두 저장됨 · 남의 설정과 섞이지 않음 |
| 되돌림 시험 8가지 | 행이 없을 때 기본값 뒤집기 · 보내지 않은 항목까지 덮어쓰기 · 남의 설정까지 바꾸기 · 행을 만들지 않기 · 빈 변경 받아 주기 · 빈 목록을 "안 바꿈"으로 보기 · 모르는 종류 받아 주기 · 모르는 칸 받아 주기 → **모두 잡혔다** |
| 빌드·검사 | api `ruff check`·`ruff format --check` 통과(198 파일). web은 바뀐 것이 없다(`Settings` 타입이 이미 있다) |

되돌림 시험 중에 테스트 하나를 고쳤다. "모르는 칸은 422" 테스트가 `{"dark_mode": true}`만 보내서, `extra="forbid"`를 지워도 통과했다(모르는 칸이 버려지면 "빈 변경"이 되어 어차피 422). 아는 항목과 섞어 보내도록 고쳐서 이제 구분된다.

## 남은 것

- **web 설정 화면은 아직 목이다.** `Settings` 타입은 이미 있고 이 PR의 응답과 같다. 화면을 붙이는 PR에서 `client.ts`의 목을 이 두 경로로 바꾼다.
- **푸시 설정(`push_enabled`)을 보는 쪽은 F-33이다.** 알림 발송 배치는 이미 이 값을 읽는다(`repositories/notifications.py`). 실제 웹 푸시 발송은 VAPID 키가 있어야 한다.
- `muted_notification_types`에 "공고 알림만 끄기" 같은 묶음은 없다. 종류별로만 끈다(명세 그대로).

## 문서에 반영하기

````text
docs/API_명세_v0.4.md 한 곳만 고치면 된다. 아래 "찾을 줄"은 파일에 한 번만 나온다.

[1] 4장 `GET /me/settings` · `PATCH /me/settings` 설명
찾을 줄:
- `PATCH`는 보낸 필드만 바꾸고, 행이 없으면 기본값으로 만든다
이 줄을 아래 두 줄로 바꿔:
- `PATCH`는 보낸 필드만 바꾸고, 행이 없으면 기본값으로 만든다. 아무 필드도 보내지 않거나 모르는 필드·모르는 알림 종류를 보내면 `422 VALIDATION_FAILED`다
- 설정을 바꾼 적이 없으면 `GET`은 DB 기본값을 준다(푸시 켬 · 끈 종류 없음 · LMS 과제 자동 캘린더 등록 켬)
````

## 코드

아래 파일 6개를 그대로 만들거나 바꾼다. 샌드박스에서 `ruff`·`pytest`(DB 포함)를 통과하고 되돌림 시험 8가지를 모두 잡은 코드다.

### api (새 테스트)

#### `api/tests/test_settings_db.py`

```python
"""알림·캘린더 설정 SQL(명세 4장 `GET`·`PATCH /me/settings`)을 실제 스키마에 대고 확인한다.

설정 행은 없을 수 있다(그때는 DB 기본값이 답이다). 트랜잭션을 되돌려 지운다.
"""

from typing import Any

import psycopg
import pytest

from app.repositories.profiles import ProfileRepository
from tests.db_world import DATABASE_URL, connect, make_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]


@pytest.fixture
async def world() -> Any:
    conn = await connect()
    try:
        yield {
            "repo": ProfileRepository(conn),
            "conn": conn,
            "me": await make_user(conn),
            "other": await make_user(conn),
        }
    finally:
        await conn.rollback()
        await conn.close()


async def test_settings_without_a_row_are_the_db_defaults(world: dict[str, Any]) -> None:
    """온보딩만 한 사용자는 설정 행이 없다. 그래도 답은 기본값이어야 한다."""
    repo, me, conn = world["repo"], world["me"], world["conn"]
    row = await (
        await conn.execute("select count(*) as n from user_settings where user_id = %s", (me,))
    ).fetchone()
    assert row["n"] == 0

    found = await repo.get_settings(me)
    assert (found.push_enabled, found.calendar_auto_lms) == (True, True)
    assert found.muted_notification_types == []


async def test_the_first_change_creates_the_row(world: dict[str, Any]) -> None:
    repo, me, conn = world["repo"], world["me"], world["conn"]
    changed = await repo.update_settings(me, {"calendar_auto_lms": False})
    assert changed.calendar_auto_lms is False
    assert changed.push_enabled is True  # 나머지는 기본값 그대로다

    row = await (
        await conn.execute(
            "select push_enabled, calendar_auto_lms, muted_notification_types"
            " from user_settings where user_id = %s",
            (me,),
        )
    ).fetchone()
    assert (row["push_enabled"], row["calendar_auto_lms"]) == (True, False)
    assert row["muted_notification_types"] == []


async def test_changes_pile_up(world: dict[str, Any]) -> None:
    repo, me = world["repo"], world["me"]
    await repo.update_settings(me, {"calendar_auto_lms": False})
    await repo.update_settings(me, {"muted_notification_types": ["new_material"]})
    await repo.update_settings(me, {"push_enabled": False})

    found = await repo.get_settings(me)
    assert found.calendar_auto_lms is False
    assert found.muted_notification_types == ["new_material"]
    assert found.push_enabled is False


async def test_an_empty_list_clears_the_muted_kinds(world: dict[str, Any]) -> None:
    repo, me = world["repo"], world["me"]
    await repo.update_settings(me, {"muted_notification_types": ["new_material", "task_due"]})
    cleared = await repo.update_settings(me, {"muted_notification_types": []})
    assert cleared.muted_notification_types == []


async def test_an_unknown_kind_is_refused_by_the_database(world: dict[str, Any]) -> None:
    """라우터가 먼저 막지만, DB의 check 제약도 같은 목록을 본다(둘이 어긋나면 여기서 터진다)."""
    repo, me = world["repo"], world["me"]
    with pytest.raises(psycopg.errors.CheckViolation):
        await repo.update_settings(me, {"muted_notification_types": ["new_friend"]})
    await world["conn"].rollback()


async def test_every_kind_the_api_accepts_is_storable(world: dict[str, Any]) -> None:
    """스키마의 Literal과 DB check 제약이 같은지 한 번에 본다."""
    from app.schemas.me import NotificationType

    kinds = list(NotificationType.__args__)  # type: ignore[attr-defined]
    saved = await world["repo"].update_settings(world["me"], {"muted_notification_types": kinds})
    assert saved.muted_notification_types == kinds


async def test_my_settings_are_not_someone_elses(world: dict[str, Any]) -> None:
    repo, me, other = world["repo"], world["me"], world["other"]
    await repo.update_settings(me, {"push_enabled": False, "calendar_auto_lms": False})

    theirs = await repo.get_settings(other)
    assert (theirs.push_enabled, theirs.calendar_auto_lms) == (True, True)
    await repo.update_settings(other, {"push_enabled": True})
    mine = await repo.get_settings(me)
    assert mine.push_enabled is False  # 남의 변경이 내 설정을 건드리지 않는다
```

### api (바뀌는 파일)

#### `api/app/schemas/me.py`

```python
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
```

#### `api/app/repositories/profiles.py`

```python
"""profiles·oauth_tokens·lms_connections·notifications 조회 (ERD v0.9). 판정 결과는 opportunities.py."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection, sql

from app.db import get_conn
from app.schemas.me import (
    COMPLETION_FIELDS,
    PROFILE_FIELDS,
    ConsentResult,
    IncomeConsentResult,
    LmsSummary,
    Me,
    Profile,
    ProfileCompletion,
    Settings,
)

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"

# 선택 동의를 하면 시각을 남기고(이미 있으면 유지), 철회하면 시각과 소득·수급 값을 한 번에 지운다.
# 한 문장으로 바꿔야 DB 제약(profiles_income_consent_chk)을 지키며 철회할 수 있다
_INCOME_CONSENT_SET = (
    "income_info_agreed_at = case when %(agree)s then coalesce(income_info_agreed_at, now()) end,"
    " income_bracket = case when %(agree)s then income_bracket end,"
    " median_income_pct = case when %(agree)s then median_income_pct end,"
    " welfare_status = case when %(agree)s then welfare_status end"
)


@dataclass(frozen=True)
class Consents:
    terms_privacy: bool  # 이용약관·개인정보 (필수)
    income_info: bool  # 소득·수급 정보 (선택)


class ProfileRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def lock(self, user_id: str) -> None:
        """요청이 끝날 때까지 프로필 행을 잠근다. 읽고 비교해 저장하는 사이에 같은 사용자의 다른 요청이
        끼지 않는다. no key update라서 이 사용자의 다른 행이 profiles를 참조하며 넣는 것은 막지 않는다."""
        await self.conn.execute(
            "select 1 from profiles where id = %s for no key update", (user_id,)
        )

    async def ensure(self, user_id: str, display_name: str | None) -> None:
        """로그인 직후 profiles 행을 만든다. 이미 있으면 비어 있는 이름만 채운다."""
        await self.conn.execute(
            "insert into profiles (id, display_name) values (%s, %s) on conflict (id)"
            " do update set display_name = coalesce(profiles.display_name, excluded.display_name)",
            (user_id, display_name),
        )

    async def get_me(self, user_id: str) -> Me | None:
        filled = sql.SQL(" + ").join(
            sql.SQL("(p.{} is not null)::int").format(sql.Identifier(f)) for f in COMPLETION_FIELDS
        )
        query = sql.SQL(
            """
            select p.id, p.display_name, p.hyin_verified_at,
                   p.terms_agreed_at is not null and p.privacy_agreed_at is not null as consented,
                   p.income_info_agreed_at is not null as income_info_consented,
                   {filled} as filled,
                   exists(select 1 from oauth_tokens t where t.user_id = p.id
                          and t.provider = 'google' and t.refresh_token is not null)
                       as calendar_connected,
                   l.status as lms_status, l.last_synced_at as lms_last_synced_at,
                   (select count(*) from notifications n where n.user_id = p.id
                    and n.read_at is null and n.scheduled_at <= now()) as unread
            from profiles p left join lms_connections l on l.user_id = p.id
            where p.id = %s
            """
        ).format(filled=filled)
        row = await (await self.conn.execute(query, (user_id,))).fetchone()
        if row is None:
            return None
        lms = None
        if row["lms_status"]:
            lms = LmsSummary(status=row["lms_status"], last_synced_at=row["lms_last_synced_at"])
        return Me(
            user_id=str(row["id"]),
            display_name=row["display_name"] or "학생",
            hyin_verified=row["hyin_verified_at"] is not None,
            calendar_connected=row["calendar_connected"],
            lms=lms,
            profile_completion=ProfileCompletion(
                filled=row["filled"], total=len(COMPLETION_FIELDS)
            ),
            consented=row["consented"],
            income_info_consented=row["income_info_consented"],
            unread_notifications=row["unread"],
        )

    async def get_profile(self, user_id: str) -> Profile | None:
        query = sql.SQL("select {} from profiles where id = %s").format(
            sql.SQL(", ").join(map(sql.Identifier, PROFILE_FIELDS))
        )
        row = await (await self.conn.execute(query, (user_id,))).fetchone()
        return Profile.model_validate(row) if row else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        if not values:
            return
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder(key)) for key in values
        )
        query = sql.SQL("update profiles set {}, profile_updated_at = now() where id = %(id)s")
        await self.conn.execute(query.format(assignments), {**values, "id": user_id})

    async def get_consents(self, user_id: str) -> Consents:
        row = await (
            await self.conn.execute(
                "select terms_agreed_at is not null and privacy_agreed_at is not null as terms,"
                " income_info_agreed_at is not null as income from profiles where id = %s",
                (user_id,),
            )
        ).fetchone()
        if row is None:
            return Consents(terms_privacy=False, income_info=False)
        return Consents(terms_privacy=row["terms"], income_info=row["income"])

    async def save_consent(
        self, user_id: str, version: str, agree_income_info: bool
    ) -> ConsentResult:
        row = await (
            await self.conn.execute(
                "update profiles set terms_agreed_at = now(), privacy_agreed_at = now(),"
                f" consent_version = %(version)s, {_INCOME_CONSENT_SET} where id = %(id)s"
                " returning terms_agreed_at, privacy_agreed_at, income_info_agreed_at,"
                " consent_version",
                {"version": version, "agree": agree_income_info, "id": user_id},
            )
        ).fetchone()
        return ConsentResult.model_validate(row)

    async def set_income_consent(self, user_id: str, agree: bool) -> IncomeConsentResult:
        row = await (
            await self.conn.execute(
                f"update profiles set {_INCOME_CONSENT_SET},"
                " profile_updated_at = case when %(agree)s then profile_updated_at else now() end"
                " where id = %(id)s returning income_info_agreed_at",
                {"agree": agree, "id": user_id},
            )
        ).fetchone()
        return IncomeConsentResult.model_validate(row)

    async def get_settings(self, user_id: str) -> Settings:
        """알림·캘린더 설정. 행이 없으면 DB 기본값을 그대로 돌려준다(명세 4장)."""
        row = await (
            await self.conn.execute(
                "select push_enabled, muted_notification_types, calendar_auto_lms"
                " from user_settings where user_id = %s",
                (user_id,),
            )
        ).fetchone()
        if row is None:
            return Settings(push_enabled=True, muted_notification_types=[], calendar_auto_lms=True)
        return Settings(
            push_enabled=row["push_enabled"],
            muted_notification_types=list(row["muted_notification_types"] or []),
            calendar_auto_lms=row["calendar_auto_lms"],
        )

    async def update_settings(self, user_id: str, changes: dict[str, Any]) -> Settings:
        """보낸 항목만 바꾼다. 행이 없으면 기본값으로 만들고 그 위에 얹는다(명세 4장)."""
        columns = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(name), sql.Placeholder(name))
            for name in changes
        )
        await self.conn.execute(
            sql.SQL(
                "insert into user_settings (user_id) values (%(user)s)"
                " on conflict (user_id) do nothing"
            ),
            {"user": user_id},
        )
        await self.conn.execute(
            sql.SQL("update user_settings set {columns} where user_id = %(user)s").format(
                columns=columns
            ),
            {**changes, "user": user_id},
        )
        return await self.get_settings(user_id)

    async def save_google_tokens(self, user_id: str, access_token: str, refresh_token: str) -> None:
        """토큰은 암호화된 값만 받는다. access token 만료는 Google 기본값(1시간)보다 조금 짧게 잡는다."""
        await self.conn.execute(
            "insert into oauth_tokens (user_id, provider, access_token, refresh_token, scope,"
            " expires_at) values (%s, 'google', %s, %s, %s, now() + interval '55 minutes')"
            " on conflict (user_id, provider) do update set access_token = excluded.access_token,"
            " refresh_token = excluded.refresh_token, scope = excluded.scope,"
            " expires_at = excluded.expires_at",
            (user_id, access_token, refresh_token, CALENDAR_SCOPE),
        )


def get_profile_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> ProfileRepository:
    return ProfileRepository(conn)


ProfileRepoDep = Annotated[ProfileRepository, Depends(get_profile_repo)]
```

#### `api/app/routers/me.py`

```python
from fastapi import APIRouter
from pydantic import ValidationError

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.errors import ApiError
from app.repositories.meta import MetaRepoDep
from app.repositories.opportunities import OpportunityRepoDep
from app.repositories.profiles import ProfileRepoDep
from app.schemas.me import (
    INCOME_FIELDS,
    ConsentRequest,
    ConsentResult,
    IncomeConsentRequest,
    IncomeConsentResult,
    Me,
    Profile,
    ProfilePatch,
    ProfileUpdateResponse,
    Rejudged,
    Settings,
    SettingsUpdate,
    gpa_errors,
)

router = APIRouter(prefix="/me", tags=["내 정보"])


def _consent_required(consent: str, message: str) -> ApiError:
    """403 CONSENT_REQUIRED. details.consent: terms_privacy(필수 동의 전) 또는 income_info(선택 동의 전)."""
    return ApiError(403, "CONSENT_REQUIRED", message, {"consent": consent})


@router.get("", response_model=Me)
async def read_me(user: CurrentUserDep, repo: ProfileRepoDep) -> Me:
    me = await repo.get_me(user.id)
    if me is None:  # 첫 로그인 직후에는 프로필 행이 없어서 여기서 만든다
        await repo.ensure(user.id, user.name)
        me = await repo.get_me(user.id)
    assert me is not None
    return me


@router.get("/profile", response_model=Profile)
async def read_profile(user: CurrentUserDep, repo: ProfileRepoDep) -> Profile:
    return await repo.get_profile(user.id) or Profile()


@router.patch("/profile", response_model=ProfileUpdateResponse)
async def update_profile(
    patch: ProfilePatch,
    user: CurrentUserDep,
    repo: ProfileRepoDep,
    meta: MetaRepoDep,
    feed: OpportunityRepoDep,
    now: NowDep,
) -> ProfileUpdateResponse:
    # 동의 확인·지금 값과 비교·저장·다시 판정을 한 묶음으로: 같은 사용자의 다른 저장·철회가 끼지 않는다
    await repo.lock(user.id)
    consents = await repo.get_consents(user.id)
    if not consents.terms_privacy:
        raise _consent_required("terms_privacy", "약관에 동의한 뒤에 프로필을 저장할 수 있어요.")
    changes = patch.model_dump(exclude_unset=True)
    if not consents.income_info and any(changes.get(name) is not None for name in INCOME_FIELDS):
        raise _consent_required(
            "income_info", "소득·수급 정보는 선택 동의를 한 뒤에 저장할 수 있어요."
        )
    if changes.get("gpa_scale", 4.5) is None:
        changes["gpa_scale"] = 4.5  # 만점은 지울 수 없다
    current = await repo.get_profile(user.id) or Profile()
    try:
        merged = Profile.model_validate({**current.model_dump(), **changes})
    except ValidationError as exc:
        fields = {".".join(map(str, e["loc"])): e["msg"] for e in exc.errors()}
        raise ApiError(
            422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields}
        ) from exc
    if errors := gpa_errors(merged):
        raise ApiError(422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": errors})
    # 화면은 프로필 전체를 보내므로, 목록에서 빠진(폐지·통합) 학과라도 원래 값 그대로면 받는다
    department = changes.get("department")
    if (
        department is not None
        and department != current.department
        and not await meta.department_exists(department)
    ):
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "입력값을 확인해 주세요.",
            {"fields": {"department": "학과 목록에서 골라 주세요."}},
        )
    # 화면은 프로필 전체를 보내므로 값이 실제로 바뀐 항목만 저장한다
    updates = {
        key: getattr(merged, key)
        for key in changes
        if getattr(merged, key) != getattr(current, key)
    }
    await repo.update_profile(user.id, updates)
    # 값이 바뀌었으면 이 사용자의 활성 공고를 모두 다시 판정한다(코드 비교라 같은 요청 안에서 끝난다)
    refresh = await feed.refresh_judgments(user.id, now=now, force=bool(updates))
    counts = await feed.feed_counts(user.id, now=now)
    rejudged = Rejudged(
        changed=refresh.changed,
        eligible=counts.eligible,
        undetermined=counts.undetermined,
        ineligible=counts.ineligible,
    )
    return ProfileUpdateResponse(profile=merged, rejudged=rejudged)


@router.get("/settings", response_model=Settings)
async def read_settings(user: CurrentUserDep, repo: ProfileRepoDep) -> Settings:
    """알림·캘린더 설정(명세 4장). 설정을 바꾼 적이 없으면 기본값이다."""
    return await repo.get_settings(user.id)


@router.patch("/settings", response_model=Settings)
async def update_settings(
    body: SettingsUpdate, user: CurrentUserDep, repo: ProfileRepoDep
) -> Settings:
    """보낸 항목만 바꾼다(명세 4장). 아무 항목도 없으면 422다.

    `calendar_auto_lms`를 끄면 **이후** 새 과제만 캘린더에 넣지 않는다(이미 넣은 일정은 그대로다).
    끈 알림 종류는 그 뒤로 만들지 않는다(F-45).
    """
    changes = body.changes()
    if not changes:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "바꿀 항목을 보내 주세요.",
            {
                "fields": {
                    "settings": "push_enabled·muted_notification_types·calendar_auto_lms 중 하나는 보내야 해요."
                }
            },
        )
    return await repo.update_settings(user.id, changes)


@router.post("/consents", response_model=ConsentResult)
async def save_consents(
    body: ConsentRequest,
    user: CurrentUserDep,
    repo: ProfileRepoDep,
    feed: OpportunityRepoDep,
    now: NowDep,
) -> ConsentResult:
    """온보딩 동의 단계. 필수 2개와 선택 1개(소득·수급 정보)를 함께 받는다."""
    if not (body.agree_terms and body.agree_privacy):
        missing = {
            key: "필수 항목이에요."
            for key, agreed in (
                ("agree_terms", body.agree_terms),
                ("agree_privacy", body.agree_privacy),
            )
            if not agreed
        }
        raise ApiError(
            422, "VALIDATION_FAILED", "필수 약관에 모두 동의해 주세요.", {"fields": missing}
        )
    await repo.ensure(user.id, user.name)
    had_income = (await repo.get_consents(user.id)).income_info
    result = await repo.save_consent(user.id, body.consent_version, body.agree_income_info)
    if had_income and not body.agree_income_info:  # 선택 동의를 빼면 소득 값이 지워진다
        await feed.refresh_judgments(user.id, now=now, force=True)
    return result


@router.patch("/consents", response_model=IncomeConsentResult)
async def update_income_consent(
    body: IncomeConsentRequest,
    user: CurrentUserDep,
    repo: ProfileRepoDep,
    feed: OpportunityRepoDep,
    now: NowDep,
) -> IncomeConsentResult:
    """소득·수급 선택 동의와 철회 (F-02 소득 단계, F-06 설정). 철회하면 소득 3항목도 지운다."""
    if not (await repo.get_consents(user.id)).terms_privacy:
        raise _consent_required("terms_privacy", "약관에 먼저 동의해 주세요.")
    result = await repo.set_income_consent(user.id, body.agree_income_info)
    if not body.agree_income_info:  # 철회하면 소득 값이 지워져서 판정이 바뀔 수 있다
        await feed.refresh_judgments(user.id, now=now, force=True)
    return result
```

### api (바뀌는 테스트)

#### `api/tests/fakes.py`

```python
"""단위 테스트용 가짜 저장소. 실제 저장소와 메서드 이름·반환 타입을 맞춘다."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.repositories.opportunities import FeedPage, FeedQuery, Refresh
from app.repositories.profiles import Consents
from app.schemas.me import (
    COMPLETION_FIELDS,
    INCOME_FIELDS,
    ConsentResult,
    IncomeConsentResult,
    Me,
    Profile,
    ProfileCompletion,
    Settings,
)
from app.schemas.meta import Department
from app.schemas.metrics import (
    EligibilityMatrix,
    Latency,
    Metrics,
    ProductMetrics,
    Ratio,
    ScenarioMetrics,
    UndeterminedRate,
)
from app.schemas.opportunities import FeedCounts, OpportunityDetail, OpportunityItem


class FakeProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, str]] = {}
        self.settings: dict[str, Settings] = {}
        self.locks: list[str] = []

    async def lock(self, user_id: str) -> None:
        self.locks.append(user_id)

    async def ensure(self, user_id: str, display_name: str | None) -> None:
        row = self.profiles.setdefault(
            user_id,
            {
                "display_name": None,
                "consented_at": None,
                "income_agreed_at": None,
                "profile": Profile(),
            },
        )
        row["display_name"] = row["display_name"] or display_name

    async def get_me(self, user_id: str) -> Me | None:
        row = self.profiles.get(user_id)
        if row is None:
            return None
        filled = sum(getattr(row["profile"], f) is not None for f in COMPLETION_FIELDS)
        return Me(
            user_id=user_id,
            display_name=row["display_name"] or "학생",
            hyin_verified=False,
            calendar_connected=user_id in self.tokens,
            lms=None,
            profile_completion=ProfileCompletion(filled=filled, total=len(COMPLETION_FIELDS)),
            consented=row["consented_at"] is not None,
            income_info_consented=row["income_agreed_at"] is not None,
            unread_notifications=0,
        )

    async def get_profile(self, user_id: str) -> Profile | None:
        row = self.profiles.get(user_id)
        return row["profile"] if row else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        row = self.profiles[user_id]
        row["profile"] = row["profile"].model_copy(update=values)

    async def get_consents(self, user_id: str) -> Consents:
        row = self.profiles.get(user_id)
        if row is None:
            return Consents(terms_privacy=False, income_info=False)
        return Consents(
            terms_privacy=row["consented_at"] is not None,
            income_info=row["income_agreed_at"] is not None,
        )

    async def save_consent(
        self, user_id: str, version: str, agree_income_info: bool
    ) -> ConsentResult:
        now = datetime.now(UTC)
        row = self.profiles[user_id]
        row["consented_at"] = now
        self._set_income(row, agree_income_info, now)
        return ConsentResult(
            terms_agreed_at=now,
            privacy_agreed_at=now,
            income_info_agreed_at=row["income_agreed_at"],
            consent_version=version,
        )

    async def set_income_consent(self, user_id: str, agree: bool) -> IncomeConsentResult:
        row = self.profiles[user_id]
        self._set_income(row, agree, datetime.now(UTC))
        return IncomeConsentResult(income_info_agreed_at=row["income_agreed_at"])

    @staticmethod
    def _set_income(row: dict[str, Any], agree: bool, now: datetime) -> None:
        if agree:
            row["income_agreed_at"] = row["income_agreed_at"] or now
        else:  # 철회하면 소득 값도 지운다 (DB 제약과 같은 규칙)
            row["income_agreed_at"] = None
            row["profile"] = row["profile"].model_copy(update=dict.fromkeys(INCOME_FIELDS))

    async def get_settings(self, user_id: str) -> Settings:
        return self.settings.get(
            user_id,
            Settings(push_enabled=True, muted_notification_types=[], calendar_auto_lms=True),
        )

    async def update_settings(self, user_id: str, changes: dict[str, Any]) -> Settings:
        """실제 저장소처럼 보낸 항목만 얹는다(행이 없으면 기본값 위에)."""
        current = await self.get_settings(user_id)
        self.settings[user_id] = Settings(**{**current.model_dump(), **changes})
        return self.settings[user_id]

    async def save_google_tokens(self, user_id: str, access_token: str, refresh_token: str) -> None:
        self.tokens[user_id] = {"access_token": access_token, "refresh_token": refresh_token}


class FakeMetaRepository:
    def __init__(self) -> None:
        self.departments = [
            Department(name="인공지능학과", college="소프트웨어융합대학", field_group="공학계열"),
            Department(name="경영학부", college="경상대학", field_group="사회계열"),
        ]
        self.events: list[tuple[str, str, UUID | None]] = []

    async def list_departments(self) -> list[Department]:
        return list(self.departments)

    async def department_exists(self, name: str) -> bool:
        return any(department.name == name for department in self.departments)

    async def record_event(
        self, user_id: str, event: str, opportunity_id: UUID | None = None
    ) -> None:
        self.events.append((user_id, event, opportunity_id))


class FakeOpportunityRepository:
    """피드 API 단위 테스트용. 받은 요청을 남기고 정해 둔 목록·집계를 돌려준다."""

    def __init__(self) -> None:
        self.refreshes: list[tuple[str, bool, bool]] = []  # (user_id, force, include_expired)
        self.queries: list[FeedQuery] = []
        self.items: list[OpportunityItem] = []
        self.next_cursor: str | None = None
        self.changed = 0
        self.details: dict[str, OpportunityDetail] = {}  # 공고 id → 상세. 없으면 404
        self.detail_calls: list[tuple[str, str, str | None]] = []  # (user_id, 공고 id, 이름)
        self.openable: set[str] = set()  # 표시를 붙일 수 있는 공고 id. 없으면 404
        self.marks: dict[tuple[str, str], tuple[str, datetime]] = {}  # (user, 공고) → (표시, 시각)
        self.mark_calls: list[
            tuple[str, str, str | None, str | None]
        ] = []  # (user_id, 공고 id, 표시, 이름). 지우면 표시·이름이 None
        self.counts = FeedCounts(
            eligible=0,
            new_eligible=0,
            undetermined=0,
            missing_info=0,
            needs_review=0,
            ineligible=0,
            deadline_soon=0,
        )

    async def refresh_judgments(
        self,
        user_id: str,
        *,
        now: datetime,
        force: bool = False,
        include_expired: bool = False,
        display_name: str | None = None,
    ) -> Refresh:
        self.refreshes.append((user_id, force, include_expired))
        return Refresh(judged=0, changed=self.changed)

    async def feed_page(self, user_id: str, query: FeedQuery, *, now: datetime) -> FeedPage:
        self.queries.append(query)
        return FeedPage(items=list(self.items), next_cursor=self.next_cursor)

    async def feed_counts(self, user_id: str, *, now: datetime) -> FeedCounts:
        return self.counts

    async def detail(
        self,
        user_id: str,
        opportunity_id: str,
        *,
        now: datetime,
        display_name: str | None = None,
    ) -> OpportunityDetail | None:
        self.detail_calls.append((user_id, opportunity_id, display_name))
        return self.details.get(opportunity_id)

    async def set_mark(
        self,
        user_id: str,
        opportunity_id: str,
        mark: str,
        *,
        now: datetime,
        display_name: str | None = None,
    ) -> datetime | None:
        self.mark_calls.append((user_id, opportunity_id, mark, display_name))
        if opportunity_id not in self.openable:
            return None
        old = self.marks.get((user_id, opportunity_id))
        at = old[1] if old and old[0] == mark else now
        self.marks[(user_id, opportunity_id)] = (mark, at)
        return at

    async def clear_mark(self, user_id: str, opportunity_id: str) -> None:
        self.mark_calls.append((user_id, opportunity_id, None, None))
        self.marks.pop((user_id, opportunity_id), None)


class FakeMetricsRepository:
    """지표 집계 대역. 받은 기간만 적어 두고 빈 집계를 돌려준다."""

    def __init__(self) -> None:
        self.periods: list[tuple[date, date]] = []

    async def metrics(self, period: tuple[date, date]) -> Metrics:
        self.periods.append(period)
        start, end = period
        empty = Ratio(numerator=0, denominator=0, rate=None)
        return Metrics(
            from_date=start,
            to_date=end,
            scenarios=ScenarioMetrics(
                runs=0,
                passed=0,
                success_rate=0.0,
                latency=Latency(p50_ms=0, p95_ms=0),
                cost_usd=0.0,
                llm_calls=0,
                by_scenario=[],
            ),
            eligibility=EligibilityMatrix(
                run_started_at=None,
                checks=0,
                correct=0,
                accuracy=0.0,
                rows=[],
                eligible_to_ineligible=0,
                ineligible_to_eligible=0,
            ),
            product=ProductMetrics(
                undetermined=UndeterminedRate(**empty.model_dump(), top_missing_fields=[]),
                profile_prompt=empty,
                prepare_conversion=empty,
                lms_connect=empty,
                weekly_return=empty,
            ),
        )


class FakeLogCursor:
    """agent_log가 쓰는 커서 흉내. `returning id`면 행을 하나 준다."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self.row


class FakeLogConnection:
    """실행 로그용 autocommit 연결 흉내(DB 없이 agent_run을 돌린다).

    쓴 문장을 statements에 모아 둬서, 테스트가 실행·도구 기록이 남았는지 본다.
    """

    autocommit = True

    def __init__(self, run_id: str = "00000000-0000-4000-8000-0000000000a1") -> None:
        self.run_id = run_id
        self.statements: list[tuple[str, Any]] = []

    async def execute(self, query: str, params: Any = None) -> FakeLogCursor:
        self.statements.append((query, params))
        if "returning id" not in query:
            return FakeLogCursor(None)
        if "agent_runs" in query:
            return FakeLogCursor({"id": self.run_id})
        return FakeLogCursor({"id": "00000000-0000-4000-8000-0000000000a2"})

    def wrote(self, needle: str) -> bool:
        return any(needle in query for query, _ in self.statements)

    def outputs(self) -> dict[str, Any]:
        """도구 이름 → 그 도구가 남긴 출력. 도구는 겹치지 않으니 넣은 순서로 짝지어 읽는다."""
        open_names: list[str] = []
        found: dict[str, Any] = {}
        for query, params in self.statements:
            if not isinstance(params, tuple):
                continue
            if "insert into tool_calls" in query:
                open_names.append(params[2])
            elif "update tool_calls set output" in query and open_names:
                value = params[0]
                found[open_names.pop()] = getattr(value, "obj", value)
        return found

    def tools(self) -> list[str]:
        """기록된 도구 이름(tool_calls에 넣은 순서대로)."""
        return [
            params[2]
            for query, params in self.statements
            if "insert into tool_calls" in query and isinstance(params, tuple)
        ]
```

#### `api/tests/test_api.py`

```python
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.crypto import decrypt
from app.main import create_app
from tests.conftest import USER_ID, make_token
from tests.fakes import FakeMetaRepository, FakeProfileRepository

CONSENT = {"consent_version": "2026-10-07", "agree_terms": True, "agree_privacy": True}


def consent(client: TestClient, auth: dict[str, str], **extra: bool) -> None:
    res = client.post("/api/v1/me/consents", json={**CONSENT, **extra}, headers=auth)
    assert res.status_code == 200


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_unexpected_error_keeps_cors(settings: Settings) -> None:
    """처리하지 못한 예외도 13장 형식의 500이고, 브라우저가 읽을 수 있게 CORS 헤더가 붙는다."""
    app = create_app(settings)

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    origin = {"Origin": "http://localhost:3000"}
    with TestClient(app, raise_server_exceptions=False) as test_client:
        res = test_client.get("/api/v1/boom", headers=origin)
        assert res.status_code == 500
        assert res.json() == {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "잠시 후 다시 시도해 주세요.",
                "details": {},
            }
        }
        assert res.headers["access-control-allow-origin"] == "http://localhost:3000"
        # 다른 오류 응답도 그대로 CORS 헤더가 붙는다
        res = test_client.get("/api/v1/me", headers=origin)
        assert res.status_code == 401
        assert res.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_me_requires_login(client: TestClient) -> None:
    res = client.get("/api/v1/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_or_forged_token_is_rejected(client: TestClient) -> None:
    for token in (
        make_token(expires_in=-120),  # 시계 여유(60초)를 넘겨 만료
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
    assert body["profile_completion"] == {"filled": 0, "total": 17}


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
        "degree_program": "bachelor",
        "grade": 3,
        "gpa_last_semester": 3.9,
        "is_international": False,
    }
    res = client.patch("/api/v1/me/profile", json=patch, headers=auth)
    assert res.status_code == 200
    saved = res.json()["profile"]
    assert (saved["degree_program"], saved["grade"], saved["is_international"]) == (
        "bachelor",
        3,
        False,
    )
    assert res.json()["rejudged"] == {
        "changed": 0,
        "eligible": 0,
        "undetermined": 0,
        "ineligible": 0,
    }

    me = client.get("/api/v1/me", headers=auth).json()
    assert me["consented"] is True
    assert me["profile_completion"]["filled"] == 5

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

    res = client.patch("/api/v1/me/profile", json={"degree_program": "graduate"}, headers=auth)
    assert res.status_code == 422  # 학위과정은 bachelor·master·doctoral·integrated만
    assert list(res.json()["error"]["details"]["fields"]) == ["degree_program"]

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


# ── 설정 (명세 4장) ─────────────────────────────────────────────────────────


def test_settings_start_at_the_default(client: TestClient, auth: dict[str, str]) -> None:
    """설정을 바꾼 적이 없으면 DB 기본값이다(푸시 켬·끈 종류 없음·LMS 자동 등록 켬)."""
    body = client.get("/api/v1/me/settings", headers=auth).json()
    assert body == {
        "push_enabled": True,
        "muted_notification_types": [],
        "calendar_auto_lms": True,
    }


def test_settings_change_only_what_was_sent(
    client: TestClient, auth: dict[str, str], repo: FakeProfileRepository
) -> None:
    first = client.patch("/api/v1/me/settings", json={"calendar_auto_lms": False}, headers=auth)
    assert first.status_code == 200
    assert first.json() == {
        "push_enabled": True,  # 보내지 않은 항목은 그대로다
        "muted_notification_types": [],
        "calendar_auto_lms": False,
    }

    second = client.patch(
        "/api/v1/me/settings",
        json={"muted_notification_types": ["new_material", "new_assignment"]},
        headers=auth,
    )
    assert second.json()["muted_notification_types"] == ["new_material", "new_assignment"]
    assert second.json()["calendar_auto_lms"] is False  # 앞서 끈 것이 남아 있다
    assert repo.settings[USER_ID].calendar_auto_lms is False


def test_settings_refuse_an_empty_change(client: TestClient, auth: dict[str, str]) -> None:
    response = client.patch("/api/v1/me/settings", json={}, headers=auth)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_settings_refuse_an_unknown_notification_kind(
    client: TestClient, auth: dict[str, str]
) -> None:
    """DB의 check 제약과 같은 목록이다. 모르는 종류는 저장 전에 막는다."""
    response = client.patch(
        "/api/v1/me/settings", json={"muted_notification_types": ["new_friend"]}, headers=auth
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_settings_refuse_an_unknown_field(client: TestClient, auth: dict[str, str]) -> None:
    """아는 항목과 섞어 보내야 "모르는 칸은 버린다"와 구분된다(아는 항목만 있으면 200이 된다)."""
    response = client.patch(
        "/api/v1/me/settings", json={"push_enabled": False, "dark_mode": True}, headers=auth
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_settings_need_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/me/settings").status_code == 401
    assert client.patch("/api/v1/me/settings", json={"push_enabled": False}).status_code == 401
```

