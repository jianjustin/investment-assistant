"""Plan-1 trade plan math: ATR14, rule levels, validity, earnings flags, sizing.

Pure functions; SQL and transactions live elsewhere. All prices come from
price_bars OHLC (split-adjusted, not dividend-adjusted). Levels are rounded to
cents half-up; ref_price and atr keep full precision and are frozen into the
plan at generation. Changing a constant means a new PLAN_VERSION.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any

from investment_assistant.config import WorkbenchConfig
from investment_assistant.data.calendar import add_trading_days

PLAN_VERSION = 'plan-1'
CONTEXT_VERSION = 'context-1'
ENTRY_ATR = Decimal('0.5')
STOP_ATR = Decimal('2')
TARGET_ATR = Decimal('4')
TRAIL_ATR_MULTIPLE = Decimal('3')
VALID_SESSIONS = 3
EARNINGS_WARN_SESSIONS = 10
ATR_PERIOD = 14
MIN_BARS = ATR_PERIOD + 1

CENT = Decimal('0.01')
SIX = Decimal('0.000001')  # price_bars NUMERIC(18,6): freeze ref_price/atr at storable precision
LEVEL_KEYS = ('entry_low', 'entry_high', 'stop', 'target1')


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _cent(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _freeze(value: Decimal) -> Decimal:
    return value.quantize(SIX, rounding=ROUND_HALF_UP)


def _floor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def atr14(bars: list[dict[str, Any]]) -> Decimal | None:
    """Wilder ATR over the last 14 true ranges; None when fewer than 15 bars are given."""
    if len(bars) < MIN_BARS:
        return None
    trs: list[Decimal] = []
    prev_close: Decimal | None = None
    for bar in bars[-MIN_BARS:]:
        high, low = _dec(bar['high']), _dec(bar['low'])
        if prev_close is not None:
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = _dec(bar['close'])
    atr = sum(trs[:ATR_PERIOD]) / ATR_PERIOD
    for tr in trs[ATR_PERIOD:]:
        atr = (atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
    return atr


def rule_levels(ref_price: Decimal, atr: Decimal) -> dict[str, Decimal]:
    """Entry band ±0.5 ATR around the reference close, stop 2 ATR below, target1 4 ATR above."""
    return {
        'entry_low': _cent(ref_price - ENTRY_ATR * atr),
        'entry_high': _cent(ref_price + ENTRY_ATR * atr),
        'stop': _cent(ref_price - STOP_ATR * atr),
        'target1': _cent(ref_price + TARGET_ATR * atr),
    }


def levels_ordered(levels: dict[str, Decimal]) -> bool:
    return levels['stop'] < levels['entry_low'] <= levels['entry_high'] < levels['target1']


def validity(signal_date: date) -> tuple[date, date]:
    """The plan may fill from T+1 through T+3, trading days only."""
    return add_trading_days(signal_date, 1), add_trading_days(signal_date, VALID_SESSIONS)


def earnings_flags(row: dict[str, Any] | None, *, signal_date: date, valid_from: date,
                   valid_until: date) -> tuple[list[str], list[str]]:
    """(invalid_reasons, warnings) for the next earnings date known at the cutoff."""
    if row is None or row.get('status') != 'known' or not row.get('earnings_date'):
        return [], ['earnings_unknown']
    earnings_date = row['earnings_date']
    if valid_from <= earnings_date <= valid_until:
        return ['earnings_in_validity'], []
    if earnings_date < signal_date:
        return [], ['earnings_unknown']
    if earnings_date <= add_trading_days(signal_date, EARNINGS_WARN_SESSIONS):
        return [], ['earnings_within_10d']
    return [], []


def size(*, snapshot: dict[str, Any] | None, ref_price: Decimal, stop: Decimal, entry_high: Decimal,
         ticker_value: Decimal, total_value: Decimal, params: WorkbenchConfig) -> tuple[dict[str, Any], list[str]]:
    """Share count as the smallest of the risk budget and the two exposure caps.

    No snapshot means no equity is known: per-share risk only, status no_equity.
    A non-positive result means no room under the caps (reason no_room, shares 0).
    """
    per_share_risk = ref_price - stop
    base = {'risk_pct': params.risk_pct, 'single_cap': params.single_cap, 'total_cap': params.total_cap,
            'per_share_risk': per_share_risk}
    if snapshot is None:
        return ({'equity': None, 'snapshot_id': None, 'snapshot_as_of': None, **base,
                 'risk_amount': None, 'shares': None, 'applied_cap': None, 'status': 'no_equity'}, [])
    equity = _dec(snapshot['equity'])
    risk_amount = equity * _dec(params.risk_pct)
    caps = (
        ('risk', _floor(risk_amount / per_share_risk)),
        ('single', _floor((equity * _dec(params.single_cap) - ticker_value) / entry_high)),
        ('total', _floor((equity * _dec(params.total_cap) - total_value) / entry_high)),
    )
    applied_cap, shares = min(caps, key=lambda cap: cap[1])
    invalid = ['no_room'] if shares <= 0 else []
    status = 'no_room' if shares <= 0 else ('sized' if applied_cap == 'risk' else 'capped')
    return ({'equity': equity, 'snapshot_id': snapshot['id'], 'snapshot_as_of': snapshot['as_of'], **base,
             'risk_amount': risk_amount, 'shares': shares, 'applied_cap': applied_cap, 'status': status},
            invalid)


def validate_levels(raw: dict[str, Any]) -> dict[str, Decimal]:
    """User-submitted levels: numeric, finite, positive and strictly ordered."""
    levels: dict[str, Decimal] = {}
    for key in LEVEL_KEYS:
        try:
            value = _dec(raw[key])
        except (InvalidOperation, TypeError, KeyError):
            raise ValueError(f'{key} must be a number') from None
        if not value.is_finite() or value <= 0:
            raise ValueError(f'{key} must be a positive number')
        levels[key] = value
    if not levels_ordered(levels):
        raise ValueError('levels must satisfy stop < entry_low <= entry_high < target1')
    return levels


def _inputs(bars: list[dict[str, Any]], earnings_row: dict[str, Any] | None,
            snapshot: dict[str, Any] | None, exposure: dict[str, Any]) -> dict[str, Any]:
    return {
        'bar_ids': [b['id'] for b in bars[-MIN_BARS:]],
        'earnings_date_id': earnings_row['id'] if earnings_row else None,
        'snapshot_id': snapshot['id'] if snapshot else None,
        'exposure': exposure,
    }


def context_flags(context: dict | None) -> list[str]:
    """Advisory flags from frozen market context; never affect levels or sizing."""
    if not context:
        return []
    flags: list[str] = []
    regime = context.get('regime')
    if regime is None:
        flags.append('regime_unavailable')
    elif regime.get('label') == 'risk_off':
        flags.append('regime_risk_off')
    sector = context.get('sector')
    if sector and sector.get('state') == 'weak':
        flags.append('sector_weak')
    return flags


def _freeze_inputs(inputs: dict[str, Any], context: dict | None) -> dict[str, Any]:
    """Context is frozen verbatim into inputs; no context keeps the P1 shape exactly."""
    if context is None:
        return inputs
    return {**inputs, 'context': context}


def build_rule_plan(*, ticker: str, signal_date: date, bars: list[dict[str, Any]], earnings_row: dict[str, Any] | None,
                    snapshot: dict[str, Any] | None, exposure: dict[str, Any],
                    params: WorkbenchConfig, context: dict | None = None) -> dict[str, Any]:
    """The rule plan for a buy unit; {'skip': 'atr_unavailable'} when the bars cannot price it."""
    atr = _freeze(atr14(bars)) if (raw := atr14(bars)) is not None else None
    if atr is None or atr <= 0:
        return {'skip': 'atr_unavailable'}
    ref_price = _freeze(_dec(bars[-1]['close']))
    levels = rule_levels(ref_price, atr)
    if not levels_ordered(levels):
        return {'skip': 'atr_unavailable'}
    valid_from, valid_until = validity(signal_date)
    invalid, warnings = earnings_flags(earnings_row, signal_date=signal_date, valid_from=valid_from,
                                       valid_until=valid_until)
    sizing, size_invalid = size(snapshot=snapshot, ref_price=ref_price, stop=levels['stop'],
                                entry_high=levels['entry_high'], ticker_value=exposure['ticker_value'],
                                total_value=exposure['total_value'], params=params)
    invalid_reasons = [*invalid, *size_invalid]
    return {
        'ticker': ticker, 'signal_date': signal_date, 'kind': 'rule', 'based_on_id': None,
        'plan_version': PLAN_VERSION, 'ref_price': ref_price, 'atr': atr, **levels,
        'trail_atr_multiple': TRAIL_ATR_MULTIPLE, 'valid_from': valid_from, 'valid_until': valid_until,
        'sizing': sizing, 'status': 'invalid' if invalid_reasons else 'ok',
        'invalid_reasons': invalid_reasons, 'warnings': [*warnings, *context_flags(context)],
        'inputs': _freeze_inputs(_inputs(bars, earnings_row, snapshot, exposure), context),
    }


def build_own_plan(*, rule_plan: dict[str, Any] | None, levels: dict[str, Decimal], ticker: str,
                   signal_date: date, bars: list[dict[str, Any]], earnings_row: dict[str, Any] | None,
                   snapshot: dict[str, Any] | None, exposure: dict[str, Any],
                   params: WorkbenchConfig, context: dict | None = None) -> dict[str, Any]:
    """A user-confirmed variant; rule-plan invalid reasons demote to warnings (spec §4.5)."""
    valid_from, valid_until = validity(signal_date)
    invalid, warnings = earnings_flags(earnings_row, signal_date=signal_date, valid_from=valid_from,
                                       valid_until=valid_until)
    atr = _freeze(atr14(bars)) if (raw := atr14(bars)) is not None else None
    if atr is None:
        atr = rule_plan['atr'] if rule_plan is not None and rule_plan.get('atr') is not None else Decimal(0)
    ref_price = _freeze(_dec(bars[-1]['close']))
    # Risk per share is priced from the user's own entry band (its midpoint, as the rule
    # plan's ref sits mid-band), not the signal close the own levels may sit above.
    own_entry = (levels['entry_low'] + levels['entry_high']) / 2
    sizing, size_invalid = size(snapshot=snapshot, ref_price=own_entry, stop=levels['stop'],
                                entry_high=levels['entry_high'], ticker_value=exposure['ticker_value'],
                                total_value=exposure['total_value'], params=params)
    return {
        'ticker': ticker, 'signal_date': signal_date, 'kind': 'own',
        'based_on_id': rule_plan['id'] if rule_plan is not None else None,
        'plan_version': PLAN_VERSION, 'ref_price': ref_price, 'atr': atr, **levels,
        'trail_atr_multiple': TRAIL_ATR_MULTIPLE, 'valid_from': valid_from, 'valid_until': valid_until,
        'sizing': sizing, 'status': 'ok', 'invalid_reasons': [],
        'warnings': [*warnings, *invalid, *size_invalid, *context_flags(context)],
        'inputs': _freeze_inputs(_inputs(bars, earnings_row, snapshot, exposure), context),
    }
