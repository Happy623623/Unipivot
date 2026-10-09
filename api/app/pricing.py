"""모델 단가표 (PRD 7장 비용). 비용을 이 표로 계산해서, 단가가 바뀌어도 개선 전후를 같은 기준으로 비교한다.

값은 100만 토큰당 USD이고, 같은 모델은 적용 시작일 순서로 둔다. 단가가 바뀌면 기존 줄을 고치지 말고
새 적용일로 한 줄을 더한다(지난 호출의 비용이 그대로 남는다). 표에 없는 모델을 부르면 KeyError가 난다.
출력 단가는 생각(thinking) 토큰에도 붙으므로, record_llm의 output_tokens에는 생각 토큰을 포함해 넘긴다
(Gemini는 candidates_token_count + thoughts_token_count, Claude는 usage.output_tokens).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Price:
    effective_from: date
    input_per_mtok: Decimal
    output_per_mtok: Decimal


# 2026-10-07에 공식 가격표에서 확인한 단가 (Gemini는 결제를 연결한 유료 등급 Standard)
# https://platform.claude.com/docs/en/about-claude/pricing
# https://ai.google.dev/gemini-api/docs/pricing
_CHECKED = date(2026, 10, 7)

# (provider, model) → 적용 시작일 순서의 단가. model은 API에 보내는 ID와 똑같이 쓴다
PRICES: dict[tuple[str, str], tuple[Price, ...]] = {
    ("anthropic", "claude-haiku-4-5-20251001"): (
        Price(_CHECKED, Decimal("1.00"), Decimal("5.00")),
    ),
    ("anthropic", "claude-sonnet-5-5"): (Price(_CHECKED, Decimal("2.00"), Decimal("10.00")),),
    ("google", "gemini-3.8-flash"): (
        Price(_CHECKED, Decimal("0.75"), Decimal("3.75")),  # 2026-12-31까지
        Price(date(2027, 1, 1), Decimal("1.50"), Decimal("7.50")),
    ),
    ("google", "gemini-3.5-flash-lite"): (Price(_CHECKED, Decimal("0.30"), Decimal("2.50")),),
}


def price_on(
    provider: str,
    model: str,
    on: date,
    prices: Mapping[tuple[str, str], tuple[Price, ...]] = PRICES,
) -> Price:
    history = prices.get((provider, model))
    if not history:
        raise KeyError(
            f"단가표에 없는 모델: {provider}/{model}. app/pricing.py의 PRICES에 넣어 주세요."
        )
    applicable = [price for price in history if price.effective_from <= on]
    if not applicable:
        raise KeyError(f"{provider}/{model}의 {on} 기준 단가가 없어요.")
    return max(applicable, key=lambda price: price.effective_from)


def cost_usd(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    on: date,
    prices: Mapping[tuple[str, str], tuple[Price, ...]] = PRICES,
) -> Decimal:
    """on 날짜에 적용되는 단가로 계산한 비용 (소수점 6자리, llm_calls.cost_usd와 같은 자릿수)."""
    price = price_on(provider, model, on, prices)
    total = price.input_per_mtok * input_tokens + price.output_per_mtok * output_tokens
    return (total / Decimal(1_000_000)).quantize(Decimal("0.000001"))
