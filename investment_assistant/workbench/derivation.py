"""Plan derivation chain (v2.4): expand how every stored plan number follows from its frozen inputs.

Pure functions, no database, no network, no clock. Each step states its formula and the substituted
values, recomputes the result with ``Decimal`` from exactly those values, and compares it with the stored
value. This module is a second, independent implementation of the ``plan-1`` math: it never calls
``plans.py`` computation functions, and its constants are declared here (a test asserts they equal the
ones in ``plans.py``, so changing a formula without a new ``PLAN_VERSION`` fails the suite).

Rounding: ``atr`` and ``ref_price`` to 6 places, the four price levels to cents (both half-up), the three
share caps floored. Comparison is exact ``Decimal`` equality. Numbers leave this module as strings,
dates as ISO text, reasons and warnings as sorted lists.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Callable

from investment_assistant.data.calendar import add_trading_days

DERIVATION_VERSION = 'derivation-1'
REGISTERED_VERSIONS = ('plan-1', 'agent-1')

ENTRY_ATR = Decimal('0.5')
STOP_ATR = Decimal('2')
TARGET_ATR = Decimal('4')
TRAIL_ATR_MULTIPLE = Decimal('3')
VALID_SESSIONS = 3
EARNINGS_WARN_SESSIONS = 10
ATR_PERIOD = 14
MIN_BARS = ATR_PERIOD + 1

EVIDENCE_TEXT = '规则 v1 与 `plan-1` 都未经验证（Phase 0 Gate HOLD）。推导一致只说明算术正确，不说明规则有效。'
TRIGGER_NOTE = '触发段只复核候选冻结的取值是否满足阈值，不从原始日线重算均线。'

_CENT = Decimal('0.01')
_SIX = Decimal('0.000001')
_NO_STORED = object()   # a step with nothing stored to compare against
_NONE_TEXT = '无'


@dataclass
class Rows:
    """The raw rows a plan's ``inputs`` point at, read back by id (Decimals for numbers)."""

    bars: list[dict] | None = None          # in ``inputs.bar_ids`` order
    earnings: dict | None = None
    snapshot: dict | None = None
    regime: dict | None = None
    agent_run: dict | None = None
    rule_plan: dict | None = None
    candidates: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)   # e.g. ``price_bars:<id>``


# ---------------------------------------------------------------- value helpers

def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _opt_dec(value: Any) -> Decimal | None:
    return None if value is None else _dec(value)


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _fmt(value: Decimal) -> str:
    return format(value, 'f')


def _ser(value: Any) -> Any:
    """Result/stored value as emitted: strings for numbers and dates, sorted lists, None stays None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return _fmt(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set, frozenset)):
        return sorted({str(v) for v in value})
    return str(value)


def _sub(value: Any) -> str:
    """A substituted value as display text."""
    if value is None:
        return _NONE_TEXT
    if isinstance(value, (list, tuple, set, frozenset)):
        return ', '.join(sorted({str(v) for v in value})) or _NONE_TEXT
    return _ser(value)


def _norm(value: Any) -> Any:
    """Comparison form: reasons and warnings compare as sets, everything else exactly."""
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(str(v) for v in value)
    return value


def _jsonable(value: Any) -> Any:
    """Frozen rows for display: numbers become strings, dates ISO, ids text."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, Decimal):
        return _fmt(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return str(value)


def _quantize(value: Decimal, places: Decimal) -> Decimal:
    return value.quantize(places, rounding=ROUND_HALF_UP)


def _floor_div(numerator: Decimal, denominator: Decimal) -> int | None:
    """⌊numerator / denominator⌋; None when the divisor is not positive (cannot size)."""
    if denominator <= 0:
        return None
    return int((numerator / denominator).to_integral_value(rounding=ROUND_FLOOR))


def _step(key: str, label: str, formula: str, substitutions: dict[str, Any], result: Any,
          stored: Any = _NO_STORED, source: str = 'formula') -> dict[str, Any]:
    consistent: bool | None
    if stored is _NO_STORED:
        consistent, stored_out = None, None
    else:
        consistent, stored_out = _norm(result) == _norm(stored), _ser(stored)
    return {'key': key, 'label': label, 'formula': formula,
            'substitutions': {k: _sub(v) for k, v in substitutions.items()},
            'result': _ser(result), 'stored': stored_out, 'source': source, 'consistent': consistent}


# ---------------------------------------------------------------- inputs section

def _bar_view(bar: dict[str, Any]) -> dict[str, Any]:
    return {'id': _jsonable(bar.get('id')), 'price_date': _jsonable(bar.get('price_date')),
            'open': _jsonable(bar.get('open')), 'high': _jsonable(bar.get('high')),
            'low': _jsonable(bar.get('low')), 'close': _jsonable(bar.get('close')),
            'revision': _jsonable(bar.get('revision'))}


def _inputs_view(plan: dict[str, Any], rows: Rows) -> dict[str, Any]:
    inp = plan.get('inputs') or {}
    ctx = inp.get('context') or {}
    sizing = plan.get('sizing') or {}
    exposure = inp.get('exposure') or {}
    regime = ctx.get('regime')
    if rows.regime is not None:
        regime = {k: rows.regime.get(k) for k in ('id', 'label', 'calc_version') if k in rows.regime}
    ref = rows.bars[-1] if rows.bars else None
    return _jsonable({
        'bar_ids': list(inp.get('bar_ids') or []),
        'bars': [_bar_view(b) for b in rows.bars] if rows.bars is not None else None,
        'bars_note': '拆股调整、未分红调整',
        'ref_price': {'value': plan.get('ref_price'), 'source_bar_id': ref.get('id') if ref else None},
        'earnings': ({'id': rows.earnings.get('id'), 'status': rows.earnings.get('status'),
                      'earnings_date': rows.earnings.get('earnings_date'),
                      'fetched_at': rows.earnings.get('fetched_at')}
                     if rows.earnings is not None else None),
        'earnings_note': None if rows.earnings is not None else '无记录',
        'snapshot': ({'id': rows.snapshot.get('id'), 'as_of': rows.snapshot.get('as_of'),
                      'equity': rows.snapshot.get('equity')} if rows.snapshot is not None else None),
        'snapshot_note': None if rows.snapshot is not None else '无快照（no_equity）',
        'exposure': {'ticker_value': exposure.get('ticker_value'), 'total_value': exposure.get('total_value'),
                     'note': '生成时冻结，不重算'},
        'sizing_params': {'risk_pct': sizing.get('risk_pct'), 'single_cap': sizing.get('single_cap'),
                          'total_cap': sizing.get('total_cap'), 'note': '取计划冻结值，不读当前配置'},
        'regime': regime,
        'sector': ctx.get('sector'),
        'next_earnings': ctx.get('next_earnings'),
        'pool_tier': ctx.get('pool_tier'),
        'source': ctx.get('source'),
        'screen': ctx.get('screen'),
        'agent_run': rows.agent_run,
    })


# ---------------------------------------------------------------- plan-1 rule plan

def _rule_missing(plan: dict[str, Any], rows: Rows) -> list[str]:
    inp = plan.get('inputs') or {}
    missing: list[str] = []
    bar_ids = [str(i) for i in inp.get('bar_ids') or []]
    if (rows.bars is None or len(rows.bars) != MIN_BARS or len(bar_ids) != MIN_BARS
            or [str(b.get('id')) for b in rows.bars] != bar_ids):
        missing.append('bar_ids')
    if inp.get('snapshot_id') is not None and rows.snapshot is None:
        missing.append(f"account_snapshots:{inp['snapshot_id']}")
    if inp.get('earnings_date_id') is not None and rows.earnings is None:
        missing.append(f"earnings_dates:{inp['earnings_date_id']}")
    if inp.get('snapshot_id') is not None and rows.snapshot is not None:
        exposure = inp.get('exposure') or {}
        missing += [f'exposure.{k}' for k in ('ticker_value', 'total_value') if exposure.get(k) is None]
        sizing = plan.get('sizing') or {}
        missing += [f'sizing.{k}' for k in ('risk_pct', 'single_cap', 'total_cap') if sizing.get(k) is None]
    return missing


def _earnings_flag(row: dict[str, Any] | None, signal: date, valid_from: date, valid_until: date,
                   warn_until: date) -> str:
    if row is None or row.get('status') != 'known' or not row.get('earnings_date'):
        return 'earnings_unknown'
    earnings_date = _date(row['earnings_date'])
    if valid_from <= earnings_date <= valid_until:
        return 'earnings_in_validity'
    if earnings_date < signal:
        return 'earnings_unknown'
    if earnings_date <= warn_until:
        return 'earnings_within_10d'
    return 'none'


def _context_flags(ctx: dict[str, Any] | None) -> tuple[list[str], str, str]:
    """(flags, regime label shown, sector state shown) from the context frozen in the plan."""
    if not ctx:
        return [], _NONE_TEXT, _NONE_TEXT
    flags: list[str] = []
    regime = ctx.get('regime')
    if regime is None:
        flags.append('regime_unavailable')
    elif regime.get('label') == 'risk_off':
        flags.append('regime_risk_off')
    sector = ctx.get('sector')
    if sector and sector.get('state') == 'weak':
        flags.append('sector_weak')
    return (flags, (regime or {}).get('label') or _NONE_TEXT, (sector or {}).get('state') or _NONE_TEXT)


def _derive_rule(plan: dict[str, Any], rows: Rows) -> tuple[list[dict], list[dict], list[str]]:
    """Steps, checks and missing items for a ``plan-1`` rule plan."""
    missing = _rule_missing(plan, rows)
    if 'bar_ids' in missing:
        return [], [], missing   # no bars, no ATR: nothing downstream can be derived
    inp = plan.get('inputs') or {}
    sizing = plan.get('sizing') or {}
    bars = rows.bars or []
    snapshot_ok = not any(m.startswith(('account_snapshots:', 'exposure.', 'sizing.')) for m in missing)
    earnings_ok = not any(m.startswith('earnings_dates:') for m in missing)
    signal = _date(plan['signal_date'])
    steps: list[dict[str, Any]] = []

    # True ranges: the last 14 of the 15 bars, each against the previous close.
    trs: list[Decimal] = []
    for i in range(1, MIN_BARS):
        high, low, prev_close = _dec(bars[i]['high']), _dec(bars[i]['low']), _dec(bars[i - 1]['close'])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        steps.append(_step(f'tr_{i}', f'真实波幅 TR{i}', 'max(H − L, |H − C前|, |L − C前|)',
                           {'H': high, 'L': low, 'C前': prev_close}, tr))

    atr = _quantize(sum(trs, Decimal(0)) / ATR_PERIOD, _SIX)
    steps.append(_step('atr', 'ATR14', '(tr_1 + … + tr_14) / 14，四舍五入到 6 位（15 根日线恰好 14 个 TR，'
                                       'Wilder 递推退化为算术平均）',
                       {f'tr_{i}': tr for i, tr in enumerate(trs, 1)}, atr, _opt_dec(plan.get('atr'))))
    ref_price = _quantize(_dec(bars[-1]['close']), _SIX)
    steps.append(_step('ref_price', '参考价', 'close(最后一根)，四舍五入到 6 位',
                       {'close': _dec(bars[-1]['close'])}, ref_price, _opt_dec(plan.get('ref_price'))))

    levels = {
        'entry_low': _quantize(ref_price - ENTRY_ATR * atr, _CENT),
        'entry_high': _quantize(ref_price + ENTRY_ATR * atr, _CENT),
        'stop': _quantize(ref_price - STOP_ATR * atr, _CENT),
        'target1': _quantize(ref_price + TARGET_ATR * atr, _CENT),
    }
    level_specs = (
        ('entry_low', '入场下沿', 'ref_price − 0.5 × atr，四舍五入到分', 'ENTRY_ATR', ENTRY_ATR),
        ('entry_high', '入场上沿', 'ref_price + 0.5 × atr，四舍五入到分', 'ENTRY_ATR', ENTRY_ATR),
        ('stop', '止损', 'ref_price − 2 × atr，四舍五入到分', 'STOP_ATR', STOP_ATR),
        ('target1', '目标一', 'ref_price + 4 × atr，四舍五入到分', 'TARGET_ATR', TARGET_ATR),
    )
    for key, label, formula, const_name, const in level_specs:
        steps.append(_step(key, label, formula, {'ref_price': ref_price, const_name: const, 'atr': atr},
                           levels[key], _opt_dec(plan.get(key))))
    steps.append(_step('trail_atr_multiple', '移动止损倍数', '常量 3', {'TRAIL_ATR_MULTIPLE': TRAIL_ATR_MULTIPLE},
                       TRAIL_ATR_MULTIPLE, _opt_dec(plan.get('trail_atr_multiple'))))

    valid_from = add_trading_days(signal, 1)
    valid_until = add_trading_days(signal, VALID_SESSIONS)
    steps.append(_step('valid_from', '有效期起', '信号日后第 1 个交易日', {'signal_date': signal}, valid_from,
                       _date(plan['valid_from'])))
    steps.append(_step('valid_until', '有效期止', '信号日后第 3 个交易日',
                       {'signal_date': signal, 'VALID_SESSIONS': VALID_SESSIONS}, valid_until,
                       _date(plan['valid_until'])))

    earn_invalid: list[str] = []
    earn_warn: list[str] = []
    if earnings_ok:
        warn_until = add_trading_days(signal, EARNINGS_WARN_SESSIONS)
        row = rows.earnings
        flag = _earnings_flag(row, signal, valid_from, valid_until, warn_until)
        if flag == 'earnings_in_validity':
            earn_invalid = [flag]
        elif flag != 'none':
            earn_warn = [flag]
        steps.append(_step(
            'earnings_flag', '财报标记',
            '有效期内有已知财报 → earnings_in_validity（作废）；信号日起 10 个交易日内 → earnings_within_10d；'
            '未知或已过 → earnings_unknown',
            {'earnings_status': (row or {}).get('status'),
             'earnings_date': _date(row['earnings_date']) if row and row.get('earnings_date') else None,
             'valid_from': valid_from, 'valid_until': valid_until, 'signal_date': signal,
             'signal_date+10': warn_until}, flag))

    ctx = inp.get('context')
    context_flags, regime_label, sector_state = _context_flags(ctx)
    steps.append(_step('context_flags', '市场环境提示',
                       '区制缺失 → regime_unavailable；区制为 risk_off → regime_risk_off；行业偏弱 → sector_weak',
                       {'regime': regime_label, 'sector_state': sector_state}, context_flags))

    shares: int | None = None
    size_invalid: list[str] = []
    if snapshot_ok:
        exposure = inp.get('exposure') or {}
        per_share_risk = ref_price - levels['stop']
        steps.append(_step('per_share_risk', '每股风险', 'ref_price − stop',
                           {'ref_price': ref_price, 'stop': levels['stop']}, per_share_risk,
                           _opt_dec(sizing.get('per_share_risk'))))
        if rows.snapshot is None:
            steps.append(_step('risk_amount', '风险预算', '无资金快照，不定仓', {}, None,
                               _opt_dec(sizing.get('risk_amount'))))
            steps.append(_step('shares', '股数', '无资金快照，不定仓', {}, None, _opt_int(sizing.get('shares'))))
            steps.append(_step('applied_cap', '生效上限', '无资金快照，不定仓', {}, None, sizing.get('applied_cap')))
            steps.append(_step('sizing.status', '定仓状态', '无资金快照 → no_equity', {}, 'no_equity',
                               sizing.get('status')))
        else:
            equity = _dec(rows.snapshot['equity'])
            risk_pct, single_cap, total_cap = (_dec(sizing[k]) for k in ('risk_pct', 'single_cap', 'total_cap'))
            ticker_value, total_value = _dec(exposure['ticker_value']), _dec(exposure['total_value'])
            steps.append(_step('equity', '资金', '资金快照 equity', {'snapshot_as_of': rows.snapshot.get('as_of')},
                               equity, _opt_dec(sizing.get('equity')), source='frozen'))
            steps.append(_step('ticker_value', '该票市值', '生成时冻结，不重算', {}, ticker_value, source='frozen'))
            steps.append(_step('total_value', '总持仓市值', '生成时冻结，不重算', {}, total_value, source='frozen'))
            risk_amount = equity * risk_pct
            steps.append(_step('risk_amount', '风险预算', 'equity × risk_pct',
                               {'equity': equity, 'risk_pct': risk_pct}, risk_amount,
                               _opt_dec(sizing.get('risk_amount'))))
            cap_risk = _floor_div(risk_amount, per_share_risk)
            cap_single = _floor_div(equity * single_cap - ticker_value, levels['entry_high'])
            cap_total = _floor_div(equity * total_cap - total_value, levels['entry_high'])
            steps.append(_step('cap_risk', '风险上限股数', '⌊risk_amount / per_share_risk⌋，向下取整',
                               {'risk_amount': risk_amount, 'per_share_risk': per_share_risk}, cap_risk))
            steps.append(_step('cap_single', '单票上限股数',
                               '⌊(equity × single_cap − ticker_value) / entry_high⌋，向下取整',
                               {'equity': equity, 'single_cap': single_cap, 'ticker_value': ticker_value,
                                'entry_high': levels['entry_high']}, cap_single))
            steps.append(_step('cap_total', '总仓上限股数',
                               '⌊(equity × total_cap − total_value) / entry_high⌋，向下取整',
                               {'equity': equity, 'total_cap': total_cap, 'total_value': total_value,
                                'entry_high': levels['entry_high']}, cap_total))
            caps = (('risk', cap_risk), ('single', cap_single), ('total', cap_total))
            applied_cap: str | None = None
            if all(value is not None for _, value in caps):
                applied_cap, shares = min(caps, key=lambda cap: cap[1])
            cap_subs = {'cap_risk': cap_risk, 'cap_single': cap_single, 'cap_total': cap_total}
            steps.append(_step('shares', '股数', 'min(cap_risk, cap_single, cap_total)', cap_subs, shares,
                               _opt_int(sizing.get('shares'))))
            steps.append(_step('applied_cap', '生效上限', 'cap_risk / cap_single / cap_total 中取到最小值的一个'
                                                          '（并列取靠前者）', cap_subs, applied_cap,
                               sizing.get('applied_cap')))
            status = (None if shares is None else 'no_room' if shares <= 0
                      else 'sized' if applied_cap == 'risk' else 'capped')
            steps.append(_step('sizing.status', '定仓状态',
                               'shares ≤ 0 → no_room；风险上限生效 → sized；否则 → capped',
                               {'shares': shares, 'applied_cap': applied_cap}, status, sizing.get('status')))
            if shares is not None and shares <= 0:
                size_invalid = ['no_room']

    if snapshot_ok and earnings_ok:
        invalid = [*earn_invalid, *size_invalid]
        warnings = [*earn_warn, *context_flags]
        steps.append(_step('invalid_reasons', '作废原因', '财报作废 + no_room',
                           {'earnings': earn_invalid, 'sizing': size_invalid}, invalid,
                           plan.get('invalid_reasons') or []))
        steps.append(_step('warnings', '提示', '财报提示 + 区制 / 行业提示',
                           {'earnings': earn_warn, 'context': context_flags}, warnings,
                           plan.get('warnings') or []))
        steps.append(_step('status', '计划状态', '有作废原因 → invalid；否则 → ok', {'invalid_reasons': invalid},
                           'invalid' if invalid else 'ok', plan.get('status')))

    ordered = levels['stop'] < levels['entry_low'] <= levels['entry_high'] < levels['target1']
    checks = [{'key': 'levels_ordered', 'label': '价位顺序', 'formula': 'stop < entry_low ≤ entry_high < target1',
               'substitutions': {k: _fmt(v) for k, v in levels.items()}, 'holds': ordered}]
    return steps, checks, missing


# ---------------------------------------------------------------- dispatch and verdict

# (plan_version, kind) -> derivation function. Own and agent plans register here later.
_DERIVERS: dict[tuple[str, str], Callable[[dict[str, Any], Rows], tuple[list[dict], list[dict], list[str]]]] = {
    ('plan-1', 'rule'): _derive_rule,
}


def consistency(steps: list[dict[str, Any]], trigger: list[dict[str, Any]], missing: list[str]) -> dict[str, Any]:
    """consistent / mismatch / incomplete; missing rows or an unregistered version outrank a mismatch.

    ``trigger`` carries the trigger section's clauses; a violated clause counts as a mismatch once the
    trigger section is derived (it is empty for rule plans so far).
    """
    mismatches = [{'key': s['key'], 'result': s['result'], 'stored': s['stored']}
                  for s in steps if s['consistent'] is False]
    mismatches += [{'key': t['key'], 'result': t.get('result'), 'stored': t.get('stored')}
                   for t in trigger if t.get('result') == 'violated']
    missing = sorted(set(missing))
    status = 'incomplete' if missing else 'mismatch' if mismatches else 'consistent'
    return {'status': status, 'mismatches': mismatches, 'missing': missing}


def derive_plan(plan: dict[str, Any], rows: Rows) -> dict[str, Any]:
    """The full derivation of one stored plan against the rows its ``inputs`` point at."""
    version, kind = plan.get('plan_version'), plan.get('kind')
    missing = list(rows.missing)
    steps: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    if version not in REGISTERED_VERSIONS:
        missing.append('unknown_plan_version')
    elif (version, kind) not in _DERIVERS:
        missing.append(f'no_derivation:{kind}')
    else:
        steps, checks, more = _DERIVERS[(version, kind)](plan, rows)
        missing += more
    trigger: list[dict[str, Any]] = []
    return {
        'derivation_version': DERIVATION_VERSION,
        'plan': {'id': _ser(plan.get('id')), 'ticker': plan.get('ticker'),
                 'signal_date': _ser(_date(plan['signal_date'])) if plan.get('signal_date') else None,
                 'kind': kind, 'plan_version': version, 'status': plan.get('status')},
        'trigger': trigger,
        'inputs': _inputs_view(plan, rows),
        'steps': steps,
        'checks': checks,
        'consistency': consistency(steps, trigger, missing),
        'evidence': EVIDENCE_TEXT,
    }
