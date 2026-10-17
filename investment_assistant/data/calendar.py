from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

# Modern NYSE full-day exceptional closures, not federal/bank holidays.
# Earlier historical calendars (notably pre-1998) are not exhaustive.
_SPECIAL_CLOSURES = frozenset({
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),
    date(2004, 6, 11), date(2007, 1, 2),
    date(2012, 10, 29), date(2012, 10, 30),
    date(2018, 12, 5), date(2025, 1, 9),
})


def _good_friday(year: int) -> date:
    """Gregorian computus: Good Friday is two days before Easter Sunday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day0 = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day0 + 1) - timedelta(days=2)


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
    # NYSE does NOT observe a Saturday New Year on the preceding Friday.
    # E.g. 2021-12-31 was open; Sunday New Year still closes the next Monday.
    new_year = date(year, 1, 1)
    if new_year.isoweekday() != 6:
        days.add(_observed(new_year))
    if year >= 2022:  # NYSE first observed Juneteenth in 2022, not 2021.
        days.add(_observed(date(year, 6, 19)))
    days.add(_observed(date(year, 7, 4)))      # Independence Day
    days.add(_observed(date(year, 12, 25)))    # Christmas
    # 浮动假日
    if year >= 1998:  # NYSE first observed MLK Day in 1998.
        days.add(_nth_weekday(year, 1, 1, 3))
    days.add(_nth_weekday(year, 2, 1, 3))      # Presidents' Day: 2月第3个周一
    days.add(_last_weekday(year, 5, 1))         # Memorial Day: 5月最后一个周一
    days.add(_nth_weekday(year, 9, 1, 1))      # Labor Day: 9月第1个周一
    days.add(_nth_weekday(year, 11, 4, 4))     # Thanksgiving: 11月第4个周四
    days.add(_good_friday(year))
    days.update(d for d in _SPECIAL_CLOSURES if d.year == year)
    return frozenset(days)


def last_completed_trading_day(now: datetime | None = None) -> date:
    """Conservative cutoff: the NYSE session strictly before today's NY date.

    Deliberately excludes the entire current session, even after the close. This
    needs no network/early-close schedule and never treats an intraday bar as a
    completed daily close. Early-close dates themselves remain trading sessions.
    """
    current = now if now is not None else datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    today_ny = current.astimezone(ZoneInfo("America/New_York")).date()
    return add_trading_days(today_ny, -1)


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
