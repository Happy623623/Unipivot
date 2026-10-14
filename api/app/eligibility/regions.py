"""거주지역 비교. 요건 값은 "시도" 또는 "시도 시군구" 문자열이다."""

from __future__ import annotations

from typing import Literal

Verdict = Literal["match", "no", "less_specific", "unparseable"]

#: 시도 16곳. 2026-07-01에 광주광역시와 전라남도가 전남광주통합특별시로 합쳐졌다.
#: 통합 전 이름("광주광역시"·"전라남도")은 별칭으로 받아 통합 이름으로 정규화한다. 통합 전에 올라온
#: 공고와 통합 전 이름으로 저장한 프로필이 남아 있고, 둘을 같은 지역으로 봐야 판정이 된다.
#: 그래서 통합 전이라면 갈렸을 조합(광주 사람 × "전라남도" 요건)도 이제 같은 지역으로 맞는다 —
#: 행정구역이 하나가 됐으니 맞고, 어긋나더라도 '지원 가능' 쪽이라 규칙 0-9(확실할 때만 부적격)와 같은 방향이다.
_SIDO: dict[str, tuple[str, ...]] = {
    "서울특별시": ("서울", "서울시"),
    "부산광역시": ("부산", "부산시"),
    "대구광역시": ("대구", "대구시"),
    "인천광역시": ("인천", "인천시"),
    # "광주시"는 경기도 광주시와 겹쳐서 받지 않는다
    "전남광주통합특별시": (
        "전남광주",
        "광주전남",
        "전남광주특별시",
        "광주광역시",
        "광주",
        "전라남도",
        "전남",
    ),
    "대전광역시": ("대전", "대전시"),
    "울산광역시": ("울산", "울산시"),
    "세종특별자치시": ("세종", "세종시"),
    "경기도": ("경기",),
    "강원특별자치도": ("강원", "강원도"),
    "충청북도": ("충북",),
    "충청남도": ("충남",),
    "전북특별자치도": ("전북", "전라북도"),
    "경상북도": ("경북",),
    "경상남도": ("경남",),
    "제주특별자치도": ("제주", "제주도"),
}
SIDO_ALIASES: dict[str, str] = {
    alias: name for name, aliases in _SIDO.items() for alias in (name, *aliases)
}
_WHOLE_AREA = {"전체", "전역", "일원"}


def normalize_sido(name: str | None) -> str | None:
    """시도 이름 → 정식 이름. 모르는 이름이면 None."""
    if not name:
        return None
    return SIDO_ALIASES.get(name.strip())


def normalize_sigungu(name: str | None, sido: str | None = None) -> str | None:
    """시군구 이름의 공백 정리. 비어 있으면 None.

    앞에 프로필 시도 이름(별칭 포함, sido는 정규화한 이름)이 붙어 있으면 뗀다: "서울 중랑구" → "중랑구".
    다른 시도 이름은 떼지 않는다(경기도 학생의 "광주"는 광주광역시가 아니라 광주시다). 시도 이름만 있으면
    정식 이름일 때만 뗀다("서울특별시" → 없음). 약칭 하나는 그대로 둔다("제주"는 제주시일 수 있다)."""
    if not name:
        return None
    tokens = name.split()
    if sido is not None and tokens and normalize_sido(tokens[0]) == sido:
        if len(tokens) > 1 or tokens[0] == sido:
            tokens = tokens[1:]
    return " ".join(tokens) or None


def parse_region(text: str) -> tuple[str, str | None] | None:
    """요건 값 → (시도, 시군구). 시도로 시작하지 않으면 None (시군구 이름은 여러 시도에 겹친다)."""
    tokens = text.split()
    sido = normalize_sido(tokens[0]) if tokens else None
    if sido is None:
        return None
    rest = [token for token in tokens[1:] if token not in _WHOLE_AREA]
    return sido, (" ".join(rest) or None)


def region_verdict(entry: tuple[str, str | None] | None, sido: str, sigungu: str | None) -> Verdict:
    """요건 값 하나와 프로필 지역(정규화한 값) 비교."""
    if entry is None:
        return "unparseable"
    entry_sido, entry_sigungu = entry
    if entry_sido != sido:
        return "no"
    if entry_sigungu is None:
        return "match"
    if sigungu is None:
        return "less_specific"
    wanted = [_core(token) for token in entry_sigungu.split()]
    have = [_core(token) for token in sigungu.split()]
    if have[: len(wanted)] == wanted:
        return "match"  # "안산시"는 "안산시 단원구"를 포함한다
    if len(have) < len(wanted) and wanted[: len(have)] == have:
        return "less_specific"  # 요건은 구 단위(안산시 단원구), 프로필은 시 단위(안산시)
    return "no"


def _core(token: str) -> str:
    """끝의 시·군·구를 뗀 이름. "안산"과 "안산시"를 같게 본다."""
    return token[:-1] if len(token) > 1 and token[-1] in "시군구" else token
