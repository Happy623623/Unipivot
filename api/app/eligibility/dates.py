"""날짜 규칙: KST 변환, 판정 기준일, 만 나이."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

# 한국은 서머타임이 없어 고정 오프셋이 정확하다. Windows에서도 tzdata 없이 동작한다
KST = timezone(timedelta(hours=9), "KST")


def to_kst_date(moment: datetime) -> date:
    """timestamptz → KST 날짜. 23:59 KST 마감은 그날이다."""
    if moment.tzinfo is None:
        raise ValueError("시각에는 시간대가 있어야 한다 (timestamptz)")
    return moment.astimezone(KST).date()


def resolve_basis_date(
    eligibility_basis_date: date | None, deadline_at: datetime | None, today: date
) -> date:
    """판정 기준일: 공고에 적힌 기준일 → 신청 마감일(KST) → 판정하는 날(today, 호출하는 쪽이 넘김)."""
    if eligibility_basis_date is not None:
        return eligibility_basis_date
    if deadline_at is not None:
        return to_kst_date(deadline_at)
    return today


def months_after(birth: date, months: int) -> date:
    """출생일로부터 months개월이 차는 날.

    민법 기간 계산(출생일 산입, 해당 날짜가 없으면 그 달 말일에 만료)을 따라,
    그 달에 같은 날짜가 없으면 다음 달 1일이다. 2월 29일생은 평년에 3월 1일에 나이가 오른다.
    """
    total = birth.month - 1 + months
    year, month = birth.year + total // 12, total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    if birth.day <= last_day:
        return date(year, month, birth.day)
    return date(year, month, last_day) + timedelta(days=1)


def age_on(birth: date, on: date) -> int:
    """on 날짜의 만 나이."""
    years = on.year - birth.year
    if months_after(birth, 12 * years) > on:
        years -= 1
    return years
