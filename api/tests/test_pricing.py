"""단가표 (PRD 7장 비용). 래퍼가 쓰는 모델 ID와 단가표 키가 같아야 비용이 계산된다."""

from datetime import date
from decimal import Decimal

from app.pricing import PRICES, cost_usd


def test_price_table_lists_candidate_models_in_date_order() -> None:
    assert set(PRICES) == {
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("anthropic", "claude-sonnet-5-5"),
        ("google", "gemini-3.8-flash"),
        ("google", "gemini-3.5-flash-lite"),
    }
    for history in PRICES.values():
        dates = [price.effective_from for price in history]
        assert dates == sorted(dates)


def test_costs_from_price_table() -> None:
    # 입력 15,150 · 출력 1,500 토큰
    on = date(2026, 10, 7)
    assert cost_usd("anthropic", "claude-haiku-4-5-20251001", 15_150, 1_500, on) == Decimal(
        "0.022650"
    )
    assert cost_usd("google", "gemini-3.5-flash-lite", 15_150, 1_500, on) == Decimal("0.008295")


def test_gemini_flash_price_doubles_in_2027() -> None:
    million = 1_000_000
    before = cost_usd("google", "gemini-3.8-flash", million, million, date(2026, 12, 31))
    after = cost_usd("google", "gemini-3.8-flash", million, million, date(2027, 1, 1))
    assert (before, after) == (Decimal("4.500000"), Decimal("9.000000"))
