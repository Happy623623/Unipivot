from fastapi import APIRouter
from pydantic import ValidationError

from app.auth import CurrentUserDep
from app.errors import ApiError
from app.repositories.meta import MetaRepoDep
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
    patch: ProfilePatch, user: CurrentUserDep, repo: ProfileRepoDep, meta: MetaRepoDep
) -> ProfileUpdateResponse:
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
    await repo.update_profile(user.id, {key: getattr(merged, key) for key in changes})
    # TODO(Dev1): 판정 엔진(app/eligibility)으로 이 사용자의 판정을 다시 계산하고 changed를 채운다 (S1-5)
    counts = await repo.eligibility_counts(user.id)
    return ProfileUpdateResponse(profile=merged, rejudged=Rejudged(changed=0, **counts))


@router.post("/consents", response_model=ConsentResult)
async def save_consents(
    body: ConsentRequest, user: CurrentUserDep, repo: ProfileRepoDep
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
    return await repo.save_consent(user.id, body.consent_version, body.agree_income_info)


@router.patch("/consents", response_model=IncomeConsentResult)
async def update_income_consent(
    body: IncomeConsentRequest, user: CurrentUserDep, repo: ProfileRepoDep
) -> IncomeConsentResult:
    """소득·수급 선택 동의와 철회 (F-02 소득 단계, F-06 설정). 철회하면 소득 3항목도 지운다."""
    if not (await repo.get_consents(user.id)).terms_privacy:
        raise _consent_required("terms_privacy", "약관에 먼저 동의해 주세요.")
    result = await repo.set_income_consent(user.id, body.agree_income_info)
    # TODO(Dev1): 철회했으면 판정 엔진으로 이 사용자의 판정을 다시 계산한다 (S1-5)
    return result
