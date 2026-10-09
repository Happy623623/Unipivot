"""모델 단가표 (PRD 7장 비용). 비용을 이 표로 계산해서, 단가가 바뀌어도 개선 전후를 같은 기준으로 비교한다.

PRICES에는 실제로 쓰는 모델을 각 사의 공식 가격표에서 옮겨 적는다.
값은 100만 토큰당 USD이고, 같은 모델은 적용 시작일 순서로 둔다. 표에 없는 모델을 부르면 KeyError가 난다.
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


# (provider, model) → 적용 시작일 순서의 단가
# TODO(Dev1): 쓰기로 정한 모델의 단가를 공식 가격표에서 채운다 (PRD 14장 "LLM 작업별 기본 모델")
PRICES: dict[tuple[str, str], tuple[Price, ...]] = {}


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
