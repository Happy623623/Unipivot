from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import ValidationError

from app.account import delete_account
from app.auth import CurrentUserDep
from app.calendar.service import CalendarServiceDep
from app.clock import NowDep
from app.config import Settings as AppSettings  # 아래 Settings는 알림 설정 응답 모델이다
from app.config import get_settings
from app.errors import ApiError
from app.repositories.files import FileRepoDep
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
from app.uploads.storage import StorageDep

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


@router.delete("", status_code=204, response_class=Response)
async def delete_me(
    user: CurrentUserDep,
    files: FileRepoDep,
    storage: StorageDep,
    calendar: CalendarServiceDep,
    profiles: ProfileRepoDep,
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> Response:
    """탈퇴 (API 4장, F-06). 파일 → Google 권한 → profiles 순으로 지운다(app/account.py).

    파일을 지우지 못하면 502 `STORAGE_API_ERROR`로 멈추고 아무것도 바꾸지 않는다. 파일이 있는데
    저장소 설정에 고칠 점이 있으면 지우기 전에 같은 502로 멈춘다.
    """
    await delete_account(
        user.id,
        files=files,
        storage=storage,
        calendar=calendar,
        profiles=profiles,
        settings=settings,
    )
    return Response(status_code=204)
