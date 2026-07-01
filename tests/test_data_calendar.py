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


def test_new_years_observed_rolls_back_to_prior_dec31():
    # 2022-01-01 是周六 → 观察日为 2021-12-31（周五），NYSE 休市
    assert cal.is_trading_day(date(2021, 12, 31)) is False
    # 正向对照：2019-12-31 是周二，且 2020-01-01 是周三（非周六），应为交易日
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
