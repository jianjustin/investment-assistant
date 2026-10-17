from datetime import date

from investment_assistant.data import calendar as cal


def test_weekends_are_not_trading_days():
    assert cal.is_trading_day(date(2024, 3, 2)) is False  # Saturday
    assert cal.is_trading_day(date(2024, 3, 3)) is False  # Sunday
    assert cal.is_trading_day(date(2024, 3, 4)) is True    # Monday


def test_fixed_holidays_observed():
    # 2024-01-01 元旦；2024-07-04 独立日；2024-12-25 圣诞
    assert cal.is_trading_day(date(2024, 1, 1)) is False
    assert cal.is_trading_day(date(2024, 7, 4)) is False
    assert cal.is_trading_day(date(2024, 12, 25)) is False


def test_floating_holidays_observed():
    assert cal.is_trading_day(date(2024, 1, 15)) is False   # MLK: 1月第3个周一
    assert cal.is_trading_day(date(2024, 11, 28)) is False  # 感恩节: 11月第4个周四
    assert cal.is_trading_day(date(2024, 9, 2)) is False     # 劳动节: 9月第1个周一
    assert cal.is_trading_day(date(2024, 3, 29)) is False    # Good Friday 2024


def test_holiday_on_weekend_observed_adjacent_weekday():
    # 2021-07-04 是周日 → 观察日 7-05 周一休市
    assert cal.is_trading_day(date(2021, 7, 5)) is False
    # 2021-12-25 是周六 → 观察日 12-24 周五休市
    assert cal.is_trading_day(date(2021, 12, 24)) is False


def test_saturday_new_year_does_not_close_prior_dec31_on_nyse():
    # NYSE differs from federal observed-holiday rules: 2021-12-31 was OPEN.
    assert cal.is_trading_day(date(2021, 12, 31)) is True
    assert cal.is_trading_day(date(2019, 12, 31)) is True


def test_add_trading_days_skips_weekend():
    # 周五 +1 交易日 → 下周一
    assert cal.add_trading_days(date(2024, 3, 1), 1) == date(2024, 3, 4)


def test_add_trading_days_skips_holiday():
    # 2024-01-12(周五) +1 交易日：1-13/14 周末、1-15 MLK → 落 1-16
    assert cal.add_trading_days(date(2024, 1, 12), 1) == date(2024, 1, 16)


def test_add_five_trading_days_over_holiday():
    # 2024-11-25(周一) +5 交易日，跨 11-28 感恩节(周四休) → 12-03
    assert cal.add_trading_days(date(2024, 11, 25), 5) == date(2024, 12, 3)


def test_trading_days_between_inclusive_sorted():
    days = cal.trading_days_between(date(2024, 3, 1), date(2024, 3, 6))
    # 3-1(五),3-4(一),3-5(二),3-6(三) ; 3-2/3-3 周末剔除
    assert days == [date(2024, 3, 1), date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)]


def test_juneteenth_nyse_first_observed_in_2022_not_2021():
    assert cal.is_trading_day(date(2020, 6, 19)) is True
    assert cal.is_trading_day(date(2021, 6, 18)) is True
    assert cal.is_trading_day(date(2022, 6, 20)) is False
    assert cal.is_trading_day(date(2023, 6, 19)) is False


def test_good_friday_is_computed_outside_old_lookup_range():
    assert cal.is_trading_day(date(2019, 4, 19)) is False
    assert cal.is_trading_day(date(2031, 4, 11)) is False
    assert cal.add_trading_days(date(2019, 4, 18), 1) == date(2019, 4, 22)


def test_sunday_new_year_closes_monday_but_not_previous_friday():
    assert cal.is_trading_day(date(2022, 12, 30)) is True
    assert cal.is_trading_day(date(2023, 1, 2)) is False


def test_extraordinary_modern_nyse_closures():
    for d in (date(2001, 9, 11), date(2001, 9, 14), date(2004, 6, 11),
              date(2007, 1, 2), date(2012, 10, 29), date(2012, 10, 30),
              date(2018, 12, 5), date(2025, 1, 9)):
        assert cal.is_trading_day(d) is False
    assert cal.add_trading_days(date(2025, 1, 8), 1) == date(2025, 1, 10)


def test_early_close_is_still_a_session_for_horizon():
    assert cal.is_trading_day(date(2024, 11, 29)) is True
    assert cal.add_trading_days(date(2024, 11, 27), 1) == date(2024, 11, 29)


def test_conservative_cutoff_uses_new_york_date_and_excludes_entire_current_session():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    cases = [
        (datetime(2024, 3, 11, 10, tzinfo=ny), date(2024, 3, 8)),
        (datetime(2024, 3, 11, 18, tzinfo=ny), date(2024, 3, 8)),
        (datetime(2024, 3, 12, 1, tzinfo=ZoneInfo("UTC")), date(2024, 3, 8)),
        (datetime(2024, 3, 12, 8, tzinfo=ny), date(2024, 3, 11)),
        (datetime(2025, 1, 10, 10, tzinfo=ny), date(2025, 1, 8)),
        (datetime(2024, 11, 30, 10, tzinfo=ny), date(2024, 11, 29)),
        (datetime(2024, 12, 2, 10, tzinfo=ny), date(2024, 11, 29)),
    ]
    for now, expected in cases:
        assert cal.last_completed_trading_day(now) == expected
