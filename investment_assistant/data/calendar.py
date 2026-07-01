from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# Good Friday（复活节前周五）——浮动且依赖教会历，近年用已知日期表覆盖。
_GOOD_FRIDAY: dict[int, date] = {
    2020: date(2020, 4, 10), 2021: date(2021, 4, 2), 2022: date(2022, 4, 15),
    2023: date(2023, 4, 7), 2024: date(2024, 3, 29), 2025: date(2025, 4, 18),
    2026: date(2026, 4, 3), 2027: date(2027, 3, 26), 2028: date(2028, 4, 14),
    2029: date(2029, 3, 30), 2030: date(2030, 4, 19),
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """该月第 n 个 weekday（weekday: 周一=1..周日=7）。"""
    d = date(year, month, 1)
    offset = (weekday - d.isoweekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """该月最后一个 weekday（用于阵亡将士纪念日：5月最后一个周一）。"""
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.isoweekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed(d: date) -> date:
    """固定假日逢周末顺延规则：周六→前一个周五，周日→后一个周一。"""
    if d.isoweekday() == 6:
        return d - timedelta(days=1)
    if d.isoweekday() == 7:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def nyse_holidays(year: int) -> frozenset[date]:
    days: set[date] = set()
    # 固定假日（逢周末顺延到相邻工作日）
    days.add(_observed(date(year, 1, 1)))     # New Year's Day
    # 跨年修正：若下一年 1 月 1 日是周六，其观察日为本年 12 月 31 日，需纳入本年假日
    next_ny = date(year + 1, 1, 1)
    if next_ny.isoweekday() == 6:
        days.add(date(year, 12, 31))
    days.add(_observed(date(year, 6, 19)))     # Juneteenth（2021 起，早年无害）
    days.add(_observed(date(year, 7, 4)))      # Independence Day
    days.add(_observed(date(year, 12, 25)))    # Christmas
    # 浮动假日
    days.add(_nth_weekday(year, 1, 1, 3))      # MLK: 1月第3个周一
    days.add(_nth_weekday(year, 2, 1, 3))      # Presidents' Day: 2月第3个周一
    days.add(_last_weekday(year, 5, 1))         # Memorial Day: 5月最后一个周一
    days.add(_nth_weekday(year, 9, 1, 1))      # Labor Day: 9月第1个周一
    days.add(_nth_weekday(year, 11, 4, 4))     # Thanksgiving: 11月第4个周四
    if year in _GOOD_FRIDAY:
        days.add(_GOOD_FRIDAY[year])
    return frozenset(days)


def is_trading_day(d: date) -> bool:
    if d.isoweekday() >= 6:  # Sat/Sun
        return False
    return d not in nyse_holidays(d.year)


def add_trading_days(d: date, n: int) -> date:
    if n == 0:
        return d
    step = 1 if n > 0 else -1
    remaining = abs(n)
    cur = d
    while remaining > 0:
        cur = cur + timedelta(days=step)
        if is_trading_day(cur):
            remaining -= 1
    return cur


def trading_days_between(start: date, end: date) -> list[date]:
    if end < start:
        return []
    out: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out
