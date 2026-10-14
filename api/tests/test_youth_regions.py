"""온통청년 지역 코드 → 거주지역 조건(판정엔진_규칙.md 11장). 코드표는 법정동코드 2026-09-29 판이다."""

from datetime import date

import pytest

from app.eligibility.regions import parse_region
from app.youth.regions import RegionCondition, RegionTable, region_table
from tests.youth_samples import INCHEON_BEFORE_JULY, NATIONWIDE

TABLE = region_table()
BEFORE_JULY, AFTER_JULY = date(2026, 5, 4), date(2026, 8, 1)


def leaves(prefix: str) -> list[str]:
    return sorted(code for code in TABLE.leaves if code.startswith(prefix))


def test_table() -> None:
    """끝 지역 256곳(온통청년 전국 정책과 같다), 시도 16곳(세종 포함)."""
    assert len(TABLE.leaves) == 256 and len(TABLE.by_sido) == 16
    assert TABLE.names["41273"] == "경기도 안산시 단원구"
    assert TABLE.children["41270"] == {"41271", "41273"}
    assert "43740" in TABLE.leaves  # 영동군(43740)과 증평군(43745)은 부모·자식이 아니다


def test_nationwide_has_no_condition() -> None:
    assert TABLE.condition(NATIONWIDE.split(",")) is None
    assert TABLE.condition([]) is None


@pytest.mark.parametrize(
    ("codes", "values"),
    [
        (leaves("41"), ("경기도",)),
        (["41271", "41273"], ("경기도 안산시",)),  # 한 시의 구를 모두 고르면 시 이름
        (["41270"], ("경기도 안산시",)),  # 시 코드는 그 아래 구 전부
        (["41590"], ("경기도 화성시",)),  # 2026 화성시 구 신설 전 코드로 쓰인 349건
        (["41271"], ("경기도 안산시 상록구",)),
        (["11110", "41271"], ("서울특별시 종로구", "경기도 안산시 상록구")),
        (leaves("41") + leaves("11"), ("서울특별시", "경기도")),
        (["36110"], ("세종특별자치시",)),
    ],
)
def test_names(codes: list[str], values: tuple[str, ...]) -> None:
    assert TABLE.condition(codes) == RegionCondition(values, ())
    assert all(parse_region(value) is not None for value in values)  # 판정 엔진이 읽는 이름


def test_incheon_2026_split() -> None:
    """7월 전 정책은 옛 중구·서구를 제물포구·검단구로만 옮겼다. 인천 나머지가 다 있으면 인천 전체다."""
    codes = INCHEON_BEFORE_JULY.split(",")
    assert TABLE.condition(codes, BEFORE_JULY) == RegionCondition(("인천광역시",), ())
    after = TABLE.condition(codes, AFTER_JULY)  # 7월 뒤 등록이면 보정하지 않는다
    assert after is not None and "인천광역시 영종구" in after.uncertain
    assert "인천광역시 서해구" in after.uncertain and len(after.values) == 9
    # 일부만 고른 7월 전 정책: 영종구는 원문 확인
    assert TABLE.condition(["28125"], BEFORE_JULY) == RegionCondition(
        ("인천광역시 제물포구",), ("인천광역시 영종구",)
    )
    # 전국 + 인천 보정 = 전국
    nationwide = [code for code in NATIONWIDE.split(",") if code not in ("28155", "28275")]
    assert TABLE.condition(nationwide, BEFORE_JULY) is None
    assert TABLE.condition(nationwide, AFTER_JULY) is not None


def test_merged_sido_is_judgeable() -> None:
    """2026-07-01에 합쳐진 전남광주통합특별시는 판정할 수 있는 이름이다.

    통합 직후에는 판정 엔진이 통합 전 이름만 알아서 전남·광주 정책이 통째로 원문 확인으로 빠졌다.
    엔진에 통합 이름을 넣은 뒤(app/eligibility/regions.py) 시·군·구 단위까지 판정된다."""
    assert TABLE.condition(["12110"]) == RegionCondition(("전남광주통합특별시 목포시",), ())
    assert TABLE.condition(leaves("12")) == RegionCondition(("전남광주통합특별시",), ())
    # 거의 다 고르고 한 곳만 빠지면, 빠진 곳은 원문 확인이다(아는 시도의 '빠진 곳' 규칙)
    south = leaves("12")
    gwangyang = next(code for code in south if TABLE.names[code].endswith(" 광양시"))
    almost = TABLE.condition(["11110", *[code for code in south if code != gwangyang]])
    assert almost is not None
    assert almost.uncertain == ("전남광주통합특별시 광양시",)
    assert "서울특별시 종로구" in almost.values and "전남광주통합특별시 목포시" in almost.values


def test_unknown_sido_is_uncertain() -> None:
    """판정 엔진이 모르는 시도는 원문 확인이다. 지금 표에는 그런 시도가 없어서 가짜 표로 확인한다.

    다음 행정구역 개편으로 엔진이 모르는 이름이 들어와도, 틀린 판정 대신 원문 확인으로 빠지게 하는 분기다."""
    table = RegionTable(
        [
            ("90", "없는특별시", True),
            ("90110", "없는특별시 가구", True),
            ("90120", "없는특별시 나구", True),
            ("11", "서울특별시", True),
            ("11110", "서울특별시 종로구", True),
            ("11140", "서울특별시 중구", True),
        ]
    )
    assert table.condition(["90110"]) == RegionCondition((), ("없는특별시 가구",))
    assert table.condition(["90110", "90120"]) == RegionCondition((), ("없는특별시",))
    # 아는 시도는 시·군·구 이름으로, 모르는 시도는 원문 확인으로 갈린다
    assert table.condition(["11110", "90110"]) == RegionCondition(
        ("서울특별시 종로구",), ("없는특별시 가구",)
    )


def test_uncertain_places() -> None:
    """없어진 코드, 모르는 코드, 거의 다 고르고 빠진 곳은 원문 확인이다."""
    assert TABLE.condition(["28110", "28177"]) == RegionCondition(
        ("인천광역시 미추홀구",), ("인천광역시 중구(없어진 지역)",)
    )
    assert TABLE.condition(["99999"]) == RegionCondition((), ("지역 코드 99999",))
    seoul = leaves("11")
    almost = TABLE.condition([code for code in seoul if code not in ("11500", "11710")])
    assert almost is not None and almost.uncertain == ("서울특별시 강서구", "서울특별시 송파구")
    assert len(almost.values) == 23
    few = TABLE.condition(seoul[:3])  # 세 곳만 고르면 빠진 곳은 그냥 대상이 아니다
    assert few is not None and few.uncertain == ()


def test_covers_capital() -> None:
    assert TABLE.covers_capital(["26110", "11110"])
    assert TABLE.covers_capital(["28110"])  # 없어진 인천 코드도 센다
    assert not TABLE.covers_capital(["26110", "12110"])
