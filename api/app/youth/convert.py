"""온통청년 정책 한 건 → 공고 행 값과 요건 (판정엔진_규칙.md 11장).

정책 칸 중 프로필로 판정할 수 있는 것은 코드로 요건을 만든다(LLM을 쓰지 않는다). 프로필에 없는 조건
(취업 상태, 결혼, 연소득 금액, 특화 대상)과 서술형 자격은 기타 조건(원문 확인)이다. 칸 하나가 묶음 하나이고,
한 칸에 여러 값이 있으면 같은 묶음 안의 "또는"이다. "제한없음" 코드와 빈 값은 조건을 만들지 않는다.

가져오는 범위(10/13 결정): 승인된 정책 중 신청 기간이 상시이거나 마감 전이고, 사업 기간이 끝나지 않았고,
서울·인천·경기를 한 곳이라도 고른 정책(전국 포함). 나머지는 Skip이다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time
from typing import Any, NamedTuple

from app.eligibility import KST, Requirement, requirement_problem
from app.extraction.models import RequirementDraft
from app.youth.regions import RegionTable

DETAIL_URL = "https://www.youthcenter.go.kr/youthPolicy/ythPlcyTotalSearch/ythPlcyDetail/{}"
# 기타 조건 글(requirements.value.text)은 판정표와 카드 사유에 보여 짧게 자른다. 전체 글은 근거(evidence_text,
# 판정표 행을 펼치면 보이는 "공고 원문")에 둔다
TEXT_MAX = 150
EVIDENCE_MAX = 1000
SUMMARY_MAX = 400  # 쉬운 설명 길이(요건 추출과 같다)
_START_TIME = time(0, 0)
_DEADLINE_TIME = time(23, 59)  # 날짜만 있는 마감은 그날 23:59 KST(요건 추출과 같다)
_PERIOD = re.compile(r"(\d{8})\s*~\s*(\d{8})")
_MILITARY = re.compile(r"병역|군\s*복무|제대\s*군인|군필|의무\s*복무|군\s*제대")
_GRADUATING = re.compile(r"졸업\s*예정")
# 자격 조건이 적히는 글 칸(병역 연장·졸업예정자를 찾는다)
_CONDITION_TEXTS = ("addAplyQlfcCndCn", "ptcpPrpTrgtCn", "etcMttrCn", "plcySprtCn")
_TRIVIAL = frozenset(
    {"-", "--", "---", ".", "x", "없음", "무관", "해당없음", "해당 없음", "제한없음", "제한 없음"}
    | {"해당사항없음", "해당사항 없음", "해당 사항 없음"}
)
_INCOME_LABEL = re.compile(
    r"^소득\s*[:：]\s*"
)  # "소득 : 기준 중위소득 60% 이하"처럼 칸 이름을 앞에 쓴 글

APPROVED = "0044002"  # 정책승인상태: 승인
APPLY_PERIOD, APPLY_ALWAYS, APPLY_CLOSED = "0057001", "0057002", "0057003"  # 특정기간·상시·마감
BUSINESS_PERIOD = "0056001"  # 사업기간: 특정기간
INCOME_ANY, INCOME_YEARLY = "0043001", "0043002"  # 소득조건: 무관·연소득(그 밖은 기타)
NO_LIMIT = {
    "mrgSttsCd": "0055003",
    "jobCd": "0013010",
    "schoolCd": "0049010",
    "plcyMajorCd": "0011009",
    "sbizCd": "0014010",
}
MARRIAGE = {"0055001": "기혼", "0055002": "미혼"}
JOB = {
    "0013001": "재직자",
    "0013002": "자영업자",
    "0013003": "미취업자",
    "0013004": "프리랜서",
    "0013005": "일용근로자",
    "0013006": "(예비)창업자",
    "0013007": "단기근로자",
    "0013008": "영농종사자",
    "0013009": "기타",
}
SCHOOL = {
    "0049001": "고졸 미만",
    "0049002": "고교 재학",
    "0049003": "고졸 예정",
    "0049004": "고교 졸업",
    "0049005": "대학 재학",
    "0049006": "대졸 예정",
    "0049007": "대학 졸업",
    "0049008": "석·박사",
    "0049009": "기타",
}
MAJOR = {
    "0011001": "인문계열",
    "0011002": "사회계열",
    "0011003": "상경계열",
    "0011004": "이학계열",
    "0011005": "공학계열",
    "0011006": "예체능계열",
    "0011007": "농산업계열",
    "0011008": "기타",
}
SPECIAL = {
    "0014001": "중소기업",
    "0014002": "여성",
    "0014003": "기초생활수급자",
    "0014004": "한부모가정",
    "0014005": "장애인",
    "0014006": "농업인",
    "0014007": "군인",
    "0014008": "지역인재",
    "0014009": "기타",
}
# 전공 → 학과 계열(departments.field_group, 교육부 대계열). 이학은 자연계열, 농산업은 ERICA에 없는 계열이다
MAJOR_FIELD_GROUPS = {
    "0011001": "인문계열",
    "0011002": "사회계열",
    "0011004": "자연계열",
    "0011005": "공학계열",
    "0011006": "예체능계열",
    "0011007": "농산업계열",
}
MAJOR_COLLEGES = {"0011003": "경상대학"}  # 상경계열은 ERICA 경상대학(경영·경제·보험계리·회계세무)
CHILD_MAX = 14  # 지원 연령 상한이 이 나이 이하면 자녀 나이로 본다
OPEN_MIN = 25  # 상한 없이 이 나이 이상만 적은 지원 연령은 믿지 않는다
UNIVERSITY = frozenset({"0049005", "0049006", "0049007", "0049008"})
GRADUATE = ["master", "doctoral", "integrated"]  # 석·박사(degree_program)
_NAMES = {
    "mrgSttsCd": MARRIAGE,
    "jobCd": JOB,
    "schoolCd": SCHOOL,
    "plcyMajorCd": MAJOR,
    "sbizCd": SPECIAL,
}
_RAW_SECTIONS = (
    ("plcyExplnCn", "정책 설명"),
    ("plcySprtCn", "지원 내용"),
    ("addAplyQlfcCndCn", "추가 자격"),
    ("ptcpPrpTrgtCn", "참여 제한"),
    ("earnEtcCn", "소득"),
    ("plcyAplyMthdCn", "신청 방법"),
    ("srngMthdCn", "심사 방법"),
    ("sbmsnDcmntCn", "제출 서류"),
    ("etcMttrCn", "기타"),
    ("aplyUrlAddr", "신청 사이트"),
    ("refUrlAddr1", "참고 사이트"),
    ("refUrlAddr2", "참고 사이트"),
)


class Condition(NamedTuple):
    """요건 한 줄이 될 조건. ambiguous면 판정 엔진이 늘 모름(원문 확인)으로 본다."""

    field: str
    operator: str
    value: Any
    basis: str | None
    evidence: str | None
    ambiguous: bool = False


@dataclass(frozen=True)
class Skip:
    reason: str  # 마감 · 사업 종료 · 수도권 밖 · 승인 안 됨
    expired: bool  # True면 이미 넣은 공고를 만료로, False면 숨김으로 바꾼다


@dataclass(frozen=True)
class PolicyRecord:
    external_id: str
    title: str
    organizer: str | None
    original_url: str
    raw_text: str
    easy_summary: str | None
    apply_start_at: datetime | None
    deadline_at: datetime | None
    requirements: tuple[RequirementDraft, ...]
    review_reasons: tuple[str, ...]
    content_hash: str  # 변환 결과가 바뀌었는지 본다(이 값이 같으면 다시 저장하지 않는다)


def convert(policy: Mapping[str, Any], today: date, table: RegionTable) -> PolicyRecord | Skip:
    """정책 한 건. today는 KST 날짜다."""
    if _text(policy.get("plcyAprvSttsCd")) not in (None, APPROVED):
        return Skip("승인 안 됨", expired=False)
    if policy.get("aplyPrdSeCd") == APPLY_CLOSED:
        return Skip("마감", expired=True)
    period, reasons = _apply_period(policy, today)
    if period is not None and period[1] < today:
        return Skip("마감", expired=True)
    business_end = _day(policy.get("bizPrdEndYmd"))
    if policy.get("bizPrdSeCd") == BUSINESS_PERIOD and business_end and business_end < today:
        return Skip("사업 종료", expired=True)
    codes = _codes(policy.get("zipCd"))
    if not table.covers_capital(codes):
        return Skip("수도권 밖", expired=False)
    registered = _day(str(policy.get("frstRegDt") or "")[:10].replace("-", ""))
    clauses: list[list[Condition]] = [
        _age(policy),
        _region(codes, registered, table),
        _school(policy),
        _major(policy),
        _special(policy),
        _job(policy),
        _marriage(policy),
        _income(policy),
        _free_text(policy, "addAplyQlfcCndCn", "추가 자격"),
        _free_text(policy, "ptcpPrpTrgtCn", "참여 제한"),
    ]
    requirements, broken = _checked(_drafts(clause for clause in clauses if clause))
    if broken:
        reasons.append("온통청년 조건 일부를 판정할 수 있는 모양으로 바꾸지 못함")
    if any(c.ambiguous for clause in clauses for c in clause if c.field == "age"):
        reasons.append(
            "지원 연령이 상한 없이 높은 나이만 적혀 있어 정책 대상과 맞는지 확인이 필요함"
        )
    values = {
        "external_id": str(policy["plcyNo"]),
        "title": _text(policy.get("plcyNm")) or "제목 없는 청년정책",
        "organizer": _text(policy.get("sprvsnInstCdNm")) or _text(policy.get("rgtrInstCdNm")),
        "original_url": DETAIL_URL.format(policy["plcyNo"]),
        "raw_text": _raw_text(policy),
        "easy_summary": _cut(_text(policy.get("plcyExplnCn")), SUMMARY_MAX),
        "apply_start_at": datetime.combine(period[0], _START_TIME, KST) if period else None,
        "deadline_at": datetime.combine(period[1], _DEADLINE_TIME, KST) if period else None,
        "requirements": requirements,
        "review_reasons": tuple(reasons),
    }
    return PolicyRecord(**values, content_hash=_hash(values))


def _apply_period(
    policy: Mapping[str, Any], today: date
) -> tuple[tuple[date, date] | None, list[str]]:
    """신청 기간. 기간이 여럿이면 끝나지 않은 첫 기간, 모두 끝났으면 마지막 기간이다. 상시는 None이다."""
    if policy.get("aplyPrdSeCd") == APPLY_ALWAYS:
        return None, []
    periods = []
    for start, end in _PERIOD.findall(str(policy.get("aplyYmd") or "")):
        first, last = _day(start), _day(end)
        if first and last:
            periods.append((first, last))
    if not periods:
        if policy.get("aplyPrdSeCd") == APPLY_PERIOD:
            return None, ["신청 기간을 읽지 못함"]
        return None, []
    return next((period for period in periods if period[1] >= today), periods[-1]), []


def _age(policy: Mapping[str, Any]) -> list[Condition]:
    """지원 연령(만 나이). 0~0과 1~99는 제한 없음이다. 연령 제한 여부(sprtTrgtAgeLmtYn)는 숫자와 맞지 않는
    정책이 많아 쓰지 않는다. 병역 연장을 적은 정책은 상한을 복무 기간만큼(최대 36개월) 늘린다.

    숫자를 그대로 믿으면 지원할 수 있는 학생을 지원 어려움으로 보는 두 모양은 판정하지 않는다(10/13 실제 자료).
    - 상한이 CHILD_MAX세 이하: 부모급여(0~1세)·아이돌봄(0~12세)처럼 자녀 나이다. 기타 조건(원문 확인)
    - 상한 없이 하한만 OPEN_MIN세 이상: 인천 정책 16건이 34~99세인데, 대학생 학자금·천원의 아침밥처럼
      대상과 맞지 않는다. 나이 조건은 남기되 모호한 조건(원문 확인)으로 둔다
    """
    low, high = _whole(policy.get("sprtTrgtMinAge")), _whole(policy.get("sprtTrgtMaxAge"))
    has_low, has_high = low > 1, 0 < high < 99
    if not has_low and not has_high:
        return []
    if has_high and high <= CHILD_MAX:
        text = f"지원 대상 나이: 만 {low}~{high}세(자녀 나이일 수 있음)"
        return [_other(text, f"온통청년 지원 연령 {low}~{high}세")]
    if not has_high:
        evidence = f"온통청년 지원 연령 {low}세 이상"
        return [Condition("age", "gte", low, None, evidence, ambiguous=low >= OPEN_MIN)]
    value: dict[str, Any] = {"min": low, "max": high} if has_low else {"max": high}
    if _mentions_military_extension(policy):
        value["military_extension"] = {"max_months": 36}
    evidence = (
        f"온통청년 지원 연령 {low}~{high}세" if has_low else f"온통청년 지원 연령 {high}세 이하"
    )
    return [Condition("age", "between", value, None, evidence)]


def _mentions_military_extension(policy: Mapping[str, Any]) -> bool:
    return any(
        _MILITARY.search(text) and "연장" in text for text in _texts(policy, _CONDITION_TEXTS)
    )


def _mentions(policy: Mapping[str, Any], pattern: re.Pattern[str]) -> bool:
    return any(pattern.search(text) for text in _texts(policy, _CONDITION_TEXTS))


def _texts(policy: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [text for key in keys if (text := _text(policy.get(key)))]


def _region(codes: list[str], registered: date | None, table: RegionTable) -> list[Condition]:
    condition = table.condition(codes, registered)
    if condition is None:
        return []
    evidence = f"온통청년 지역 코드 {len(codes)}곳"
    found: list[Condition] = []
    if condition.values:
        found.append(Condition("region", "in", list(condition.values), "unspecified", evidence))
    if condition.uncertain:
        found.append(_other("거주지역 원문 확인: " + ", ".join(condition.uncertain), evidence))
    return found


def _school(policy: Mapping[str, Any]) -> list[Condition]:
    """학력(최종 학력). 대학 재학은 재학·휴학·졸업유예, 대학 졸업은 졸업이거나 대학원 과정(대학을 마쳤다),
    석·박사는 대학원 과정이다. 대졸 예정·기타는 원문 확인이다. 대학 학력을 고르고 대졸 예정은 고르지 않았는데
    글에 졸업예정자가 있으면 대졸 예정도 고른 것으로 본다. 고교 학력만 고른 정책은 대학생에게 맞는지 몰라
    원문 확인이다."""
    chosen = _choices(policy, "schoolCd")
    if not chosen:
        return []
    evidence = "온통청년 학력 요건: " + "·".join(SCHOOL.get(code, code) for code in chosen)
    university = bool(UNIVERSITY & set(chosen))
    if university and "0049006" not in chosen and _mentions(policy, _GRADUATING):
        chosen = [*chosen, "0049006"]
        evidence += "(글에 졸업예정자가 있음)"
    found: list[Condition] = []
    statuses = []
    if "0049005" in chosen:
        statuses += ["enrolled", "on_leave", "deferred_graduation"]
    if "0049007" in chosen:
        statuses.append("graduated")
    if statuses:
        found.append(Condition("enrollment_status", "in", statuses, None, evidence))
    if "0049007" in chosen or "0049008" in chosen:
        found.append(Condition("degree_program", "in", GRADUATE, None, evidence))
    if university:
        unsure = [code for code in chosen if code in ("0049006", "0049009") or code not in SCHOOL]
    else:
        unsure = chosen
    if unsure:
        found.append(
            _other("학력: " + "·".join(SCHOOL.get(code, code) for code in unsure), evidence)
        )
    return found


def _major(policy: Mapping[str, Any]) -> list[Condition]:
    chosen = _choices(policy, "plcyMajorCd")
    if not chosen:
        return []
    evidence = "온통청년 전공 요건: " + "·".join(MAJOR.get(code, code) for code in chosen)
    groups = list(dict.fromkeys(MAJOR_FIELD_GROUPS[c] for c in chosen if c in MAJOR_FIELD_GROUPS))
    colleges = [MAJOR_COLLEGES[code] for code in chosen if code in MAJOR_COLLEGES]
    unsure = [c for c in chosen if c not in MAJOR_FIELD_GROUPS and c not in MAJOR_COLLEGES]
    found: list[Condition] = []
    if groups:
        found.append(Condition("department", "in", groups, "field_group", evidence))
    if colleges:
        found.append(Condition("department", "in", colleges, "college", evidence))
    if unsure:
        found.append(
            _other("전공: " + "·".join(MAJOR.get(code, code) for code in unsure), evidence)
        )
    return found


def _special(policy: Mapping[str, Any]) -> list[Condition]:
    chosen = _choices(policy, "sbizCd")
    if not chosen:
        return []
    evidence = "온통청년 특화 요건: " + "·".join(SPECIAL.get(code, code) for code in chosen)
    found: list[Condition] = []
    if "0014003" in chosen:
        found.append(Condition("welfare_status", "eq", "basic_livelihood", None, evidence))
    others = [SPECIAL.get(code, code) for code in chosen if code != "0014003"]
    if others:
        found.append(_other("특화 대상: " + "·".join(others), evidence))
    return found


def _job(policy: Mapping[str, Any]) -> list[Condition]:
    chosen = _choices(policy, "jobCd")
    if not chosen:
        return []
    names = "·".join(JOB.get(code, code) for code in chosen)
    return [_other(f"취업 상태: {names}", f"온통청년 취업 요건: {names}")]


def _marriage(policy: Mapping[str, Any]) -> list[Condition]:
    chosen = _choices(policy, "mrgSttsCd")
    if not chosen:
        return []
    names = "·".join(MARRIAGE.get(code, code) for code in chosen)
    return [_other(f"결혼: {names}", f"온통청년 결혼 요건: {names}")]


def _income(policy: Mapping[str, Any]) -> list[Condition]:
    """소득. 연소득 금액(만 원)은 프로필에 없고, 기타는 글(earnEtcCn)이라 둘 다 원문 확인이다."""
    code = _text(policy.get("earnCndSeCd"))
    if code in (None, INCOME_ANY):
        return []
    note = _meaningful(_INCOME_LABEL.sub("", _text(policy.get("earnEtcCn")) or ""))
    if code == INCOME_YEARLY:
        low, high = _whole(policy.get("earnMinAmt")), _whole(policy.get("earnMaxAmt"))
        parts = [f"{low:,}만 원 이상"] if low > 1 else []
        parts += [f"{high:,}만 원 이하"] if high > 0 else []
        text = "연소득 " + " ".join(parts) if parts else "연소득 조건이 있음"
        text += f" ({note})" if note else ""
    else:
        text = f"소득: {note}" if note else "소득 조건이 있음"
    return [_other(text, f"온통청년 {text}")]


def _free_text(policy: Mapping[str, Any], key: str, name: str) -> list[Condition]:
    text = _meaningful(policy.get(key))
    return [_other(f"{name}: {text}", f"온통청년 {name}: {text}")] if text else []


def _other(text: str, evidence: str) -> Condition:
    """기타 조건(원문 확인). 글이 길면 앞부분만 쓰고 전체는 근거에 둔다."""
    if len(text) > TEXT_MAX:
        evidence = f"온통청년 {text}"
    return Condition(
        "other", "eq", {"text": _cut(text, TEXT_MAX)}, None, _cut(evidence, EVIDENCE_MAX)
    )


def _drafts(clauses: Iterable[list[Condition]]) -> list[RequirementDraft]:
    drafts = []
    for clause_no, clause in enumerate(clauses, 1):
        for condition in clause:
            drafts.append(
                RequirementDraft(
                    clause_no=clause_no,
                    field=condition.field,
                    operator=condition.operator,
                    value=condition.value,
                    basis=condition.basis,
                    evidence_text=condition.evidence,
                    is_ambiguous=condition.ambiguous,
                )
            )
    return drafts


def _checked(drafts: list[RequirementDraft]) -> tuple[tuple[RequirementDraft, ...], bool]:
    """판정 엔진이 받을 수 있는 모양인지 본다(요건 추출과 같은 검사). 아니면 그 조건만 모호한 기타 조건으로 바꾼다.
    정책 자료가 틀린 경우다(예: 최소 나이가 최대 나이보다 큼)."""
    checked, broken = [], False
    for draft in drafts:
        requirement = Requirement(
            id="draft",
            clause_no=draft.clause_no,
            field=draft.field,
            operator=draft.operator,
            value=draft.value,
            basis=draft.basis,
        )
        if requirement_problem(requirement) is None:
            checked.append(draft)
            continue
        broken = True
        text = _cut(draft.evidence_text or "원문 확인 필요", TEXT_MAX)
        checked.append(
            replace(
                draft,
                field="other",
                operator="eq",
                value={"text": text},
                basis=None,
                is_ambiguous=True,
            )
        )
    return tuple(checked), broken


def _choices(policy: Mapping[str, Any], key: str) -> list[str]:
    """쉼표로 나눈 코드. 제한없음 코드가 있거나 모든 코드를 골랐으면 조건이 없다."""
    codes = _codes(policy.get(key))
    if not codes or NO_LIMIT[key] in codes or set(_NAMES[key]) <= set(codes):
        return []
    return codes


def _codes(value: Any) -> list[str]:
    return list(dict.fromkeys(code.strip() for code in str(value or "").split(",") if code.strip()))


def _raw_text(policy: Mapping[str, Any]) -> str:
    """공고 원문(opportunities.raw_text). 칸마다 "이름: 내용"이고, 내용의 줄바꿈은 둔다."""
    sections = []
    for key, name in _RAW_SECTIONS:
        if _meaningful(policy.get(key)):
            lines = (" ".join(line.split()) for line in str(policy[key]).splitlines())
            sections.append(f"{name}: " + "\n".join(line for line in lines if line))
    return "\n".join(sections)


def _meaningful(value: Any) -> str | None:
    """빈 값·"-"·"해당없음" 같은 글은 None이다. 공백·줄바꿈은 한 칸으로 줄인다."""
    text = _text(value)
    if text is None or text.lower() in _TRIVIAL or not re.search(r"[0-9A-Za-z가-힣]", text):
        return None
    return text


def _text(value: Any) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    return text or None


def _cut(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _whole(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _day(value: Any) -> date | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _hash(values: Mapping[str, Any]) -> str:
    def plain(item: Any) -> Any:
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, RequirementDraft):
            return asdict(item)
        if isinstance(item, tuple | list):
            return [plain(part) for part in item]
        return item

    text = json.dumps({key: plain(item) for key, item in values.items()}, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()
