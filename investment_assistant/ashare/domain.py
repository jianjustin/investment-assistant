"""Identity, periods and derived research calculations owned by the workbench."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from investment_assistant.ashare.vendor.holidays_cn import CLOSED_DATES

SHANGHAI = ZoneInfo('Asia/Shanghai')
CALENDAR_START = date(2025, 1, 1)
CALENDAR_END = date(2026, 12, 31)
CALENDAR_SOURCE = 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml'
BENCHMARKS = {
    'CN:index:000300.SH': {
        'symbol': '000300.SH', 'name': '沪深300', 'secid': '1.000300',
        'methodology': '沪深市场规模大、流动性好的300只证券；采用发布方价格指数，未重建历史成分。',
        'source_url': 'https://www.csindex.com.cn/#/indices/family/detail?indexCode=000300',
    },
    'CN:index:931865.CSI': {
        'symbol': '931865.CSI', 'name': '中证半导体产业指数', 'secid': '2.931865',
        'methodology': '半导体材料、设备和应用等领域不超过40只证券，半年调样；非纯DDR5接口芯片指数。未接入历史成分。',
        'source_url': 'https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/931865factsheet.pdf',
    },
}


def stock_id(symbol: str) -> str:
    symbol = str(symbol).strip().upper()
    if symbol.startswith('CN:STOCK:'):
        symbol = symbol[9:]
    if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', symbol):
        raise ValueError('A股须使用含交易所的代码，例如 688008.SH；指数须显式指定类型')
    code, exchange = symbol.split('.')
    valid = (exchange == 'SH' and code.startswith(('600', '601', '603', '605', '688', '689'))
             or exchange == 'SZ' and code.startswith(('000', '001', '002', '003', '300', '301'))
             or exchange == 'BJ' and code.startswith(('4', '8', '92')))
    if not valid:
        raise ValueError('代码不属于所选交易所的A股股票号段；不能把指数当股票')
    return 'CN:stock:' + symbol


def security_id(value: str) -> str:
    if value in BENCHMARKS:
        return value
    return stock_id(value)


def is_cn_symbol(value: str) -> bool:
    return bool(re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(value).upper()) or value.startswith('CN:'))


def us_only(symbols: list[str]) -> list[str]:
    return [s for s in symbols if not is_cn_symbol(s)]


def today_cn() -> date:
    return datetime.now(SHANGHAI).date()


def trading_day(day: date) -> bool:
    if not CALENDAR_START <= day <= CALENDAR_END:
        raise ValueError('A股交易日历仅核实2025–2026年；请求日期尚未核实')
    return day.weekday() < 5 and day.isoformat() not in CLOSED_DATES


def trading_dates(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)
            if trading_day(start + timedelta(days=i))]


def last_closed_session(now: datetime | None = None) -> date:
    local = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    d = local.date()
    if local.hour < 16:
        d -= timedelta(days=1)
    while not trading_day(d):
        d -= timedelta(days=1)
    return d


FLOW_FIELDS = ('revenue', 'parent_profit', 'deducted_profit', 'operating_cashflow', 'gross_profit')


def financial_periods(rows: list[dict]) -> list[dict]:
    """YTD flows → quarters only with the preceding same-year cumulative observation.

    Balance-sheet stocks and EPS are never differenced. TTM is four consecutive
    quarters, not mechanical annualisation. Every calculation retains input IDs.
    """
    by_period = {r['period_end']: r for r in rows}
    quarters = {}
    for period, row in sorted(by_period.items()):
        d = date.fromisoformat(period)
        if (d.month, d.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
            continue
        prev_end = date(d.year, d.month - 2, 1) - timedelta(days=1) if d.month > 3 else None
        prior = by_period.get(prev_end.isoformat()) if prev_end else None
        quarter = {}
        for field in FLOW_FIELDS:
            value = row.get(field)
            prev = prior.get(field) if prior else None
            quarter[field] = value if d.month == 3 else (value - prev if value is not None and prev is not None else None)
        rev, gross = quarter['revenue'], quarter['gross_profit']
        quarter['gross_margin_pct'] = gross / rev * 100 if gross is not None and rev and rev > 0 else None
        quarters[period] = {**row, 'quarter': quarter,
                            'quarter_formula': 'Q1=累计；Qn=当期累计−同年前季累计；资产负债为期末存量',
                            'quarter_inputs': [row.get('id')] + ([prior.get('id')] if prior else []),
                            'quarter_missing_reason': None if d.month == 3 or prior else '缺少同年前一季度累计数据，不补零'}
    result = []
    for period, row in sorted(quarters.items(), reverse=True):
        d = date.fromisoformat(period)
        keys = []
        for _ in range(4):
            keys.append(d.isoformat())
            d = date(d.year, d.month - 2, 1) - timedelta(days=1)
        ttm = {}
        for field in FLOW_FIELDS:
            values = [quarters[k]['quarter'].get(field) if k in quarters else None for k in keys]
            ttm[field] = sum(values) if all(v is not None for v in values) else None
        result.append({**row, 'ttm': ttm, 'ttm_periods': keys,
                       'ttm_formula': '最近四个连续单季度之和；缺一期则留空'})
    return result


def performance(rows: list[dict]) -> dict:
    valid = sorted([r for r in rows if r.get('close') is not None and r['close'] > 0], key=lambda r: r['date'])
    if len(valid) < 2:
        return {'return_pct': None, 'max_drawdown_pct': None, 'reason': '至少需要两条有效收盘价'}
    high, drawdown = valid[0]['close'], 0.0
    for row in valid:
        high = max(high, row['close'])
        drawdown = min(drawdown, row['close'] / high - 1)
    return {'return_pct': (valid[-1]['close'] / valid[0]['close'] - 1) * 100,
            'max_drawdown_pct': drawdown * 100, 'start': valid[0]['date'], 'end': valid[-1]['date'],
            'count': len(valid), 'formula': '区间收益=末日收盘/首日收盘−1；最大回撤=min(当日收盘/此前最高收盘−1)'}


def comparison(stock: list[dict], benchmark: list[dict]) -> dict:
    a = {r['date']: r for r in stock if r.get('close') and r['close'] > 0}
    b = {r['date']: r for r in benchmark if r.get('close') and r['close'] > 0}
    common = sorted(a.keys() & b.keys())
    if len(common) < 2:
        return {'status': 'insufficient', 'series': [], 'relative_return_pp': None}
    ar, br = performance([a[k] for k in common]), performance([b[k] for k in common])
    return {'status': 'ready', 'start': common[0], 'end': common[-1], 'common_sessions': len(common),
            'excluded_stock_sessions': len(a) - len(common), 'excluded_benchmark_sessions': len(b) - len(common),
            'stock_return_pct': ar['return_pct'], 'benchmark_return_pct': br['return_pct'],
            'relative_return_pp': ar['return_pct'] - br['return_pct'],
            'formula': '仅共同交易日，首日归一为100；相对收益=个股收益率−指数收益率（百分点），非回归alpha',
            'series': [{'date': k, 'stock': a[k]['close'] / a[common[0]]['close'] * 100,
                        'benchmark': b[k]['close'] / b[common[0]]['close'] * 100} for k in common]}
