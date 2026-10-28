"""Pure functions behind the instrument page's new blocks (v2.6 spec §9.1–§9.2, D14, D16).

``focus`` writes the "what to watch today" lines, ``key_data`` is the Agent tools' own indicator snapshot
computed on request (nothing stored), ``context_view`` the background block (next earnings, regime, industry
ETF). No database access here: ``service.instrument`` reads the rows and hands them in.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from investment_assistant.data.calendar import trading_days_between
from investment_assistant.workbench import labels, reasoning
from investment_assistant.workbench.agent import tools

SH = ZoneInfo('Asia/Shanghai')
EARNINGS_WITHIN_SESSIONS = 10
NONE_TEXT = '今天没有触发，也没有进行中的计划或持仓'
CONFLICT_NOTE = '· 同日有买有卖，默认观察'
OUTCOME_TEXT = {'maintain': '维持', 'revise': '修订', 'invalidate': '作废', 'skipped': '跳过', 'error': '出错'}
DECIDED_BY_TEXT = {'agent': 'Agent', 'host': '系统规则'}
MODE_TEXT = {'entry': '入场期', 'holding': '持仓期'}


def _money(value: Any) -> str:
    try:
        return f'{Decimal(str(value)):.2f}'
    except Exception:    # noqa: BLE001 - display only
        return str(value)


def _quantity(value: Any) -> str:
    text = format(Decimal(str(value)), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _percent(ratio: float) -> str:
    return f'{ratio * 100:.1f}%'


def _beijing(moment: datetime | None) -> str:
    return moment.astimezone(SH).strftime('%Y-%m-%d %H:%M') if moment is not None else '-'


def sessions_until(day: date, session: date) -> int:
    """Trading days in (session, day]; 0 for the session itself and for any earlier day."""
    return len(trading_days_between(session + timedelta(days=1), day))


def _position_item(position: dict) -> dict:
    stop = position.get('stop')
    if stop is None:
        stop_text = '当前止损 无（无计划，按回撤规则）'
    else:
        basis = '按你决定的计划' if position.get('plan_id') else '无计划，按回撤规则'
        stop_text = f'当前止损 {_money(stop)}（{basis}）'
        if position.get('to_stop_pct') is not None:
            stop_text += f"· 距止损 {_percent(position['to_stop_pct'])}"
    text = f"持仓 {_quantity(position['quantity'])} 股 · 成本 {_money(position['avg_cost'])} · {stop_text}"
    return {'kind': 'position', 'text': text, 'link': '#review/trades', 'concepts': ['review.position', 'plan.stop']}


def _chain_item(chain: dict) -> dict:
    review = chain.get('latest_review')
    if review:
        last = (f"最近复查：{OUTCOME_TEXT.get(review['outcome'], review['outcome'])}"
                f"（{DECIDED_BY_TEXT.get(review.get('decided_by'), review.get('decided_by') or '-')}，"
                f"{_beijing(review.get('created_at'))}）")
    else:
        last = '尚未复查'
    text = (f"Agent 第 {chain['version_no']} 版 · {MODE_TEXT.get(chain.get('mode'), chain.get('mode') or '-')} · "
            f"入场 {_money(chain['entry_low'])}–{_money(chain['entry_high'])} · 止损 {_money(chain['stop'])} · "
            f"T1 {_money(chain['target1'])} · {last}")
    return {'kind': 'agent_plan', 'text': text, 'link': f"#plan/{chain['head_plan_id']}",
            'concepts': ['agent.version_chain', 'review.chain_state']}


def _trigger_item(candidates: list[dict]) -> dict:
    named = '、'.join(f"{labels.RULE_TEXT.get(c['rule_id'], c['rule_id'])}（{labels.ACTION_TEXT.get(c['action'], c['action'])}）"
                      for c in candidates)
    actions = {c['action'] for c in candidates}
    text = f'今天触发 {named}' + (CONFLICT_NOTE if {'buy', 'sell'} <= actions else '')
    rules = [f"rule.{c['rule_id']}" for c in candidates if c['rule_id'] in labels.RULE_TEXT]
    return {'kind': 'trigger', 'text': text, 'link': '#today',
            'concepts': ['system.decision_unit', *dict.fromkeys(rules)]}


def _earnings_item(earnings: dict | None, session: date) -> dict | None:
    if not earnings or earnings.get('status') != 'known' or earnings.get('earnings_date') is None:
        return None
    day = earnings['earnings_date']
    if day < session:
        return None
    count = sessions_until(day, session)
    if count > EARNINGS_WITHIN_SESSIONS:
        return None
    return {'kind': 'earnings', 'text': f'{count} 个交易日后发布财报（{day.isoformat()}）', 'link': None,
            'concepts': ['plan.earnings']}


def focus(*, position: dict | None, chains: list[dict], candidates_today: list[dict], earnings: dict | None,
          session: date) -> list[dict]:
    """"今天该关注什么" (spec §9.2): position, running agent plans, today's triggers, near earnings; else one line.

    ``position``: ``{quantity, avg_cost, stop, plan_id, to_stop_pct}`` (stop / plan_id None without a plan);
    ``chains``: entry / holding chains ``{version_no, mode, head_plan_id, entry_low, entry_high, stop, target1,
    latest_review}``; ``candidates_today``: the candidates of the latest closed session;
    ``earnings``: the latest ``earnings_dates`` row."""
    items: list[dict] = []
    if position is not None:
        items.append(_position_item(position))
    items.extend(_chain_item(chain) for chain in chains)
    if candidates_today:
        items.append(_trigger_item(candidates_today))
    soon = _earnings_item(earnings, session)
    if soon is not None:
        items.append(soon)
    return items or [{'kind': 'none', 'text': NONE_TEXT, 'link': None, 'concepts': []}]


def key_data(bars: list[dict], spy_bars: list[dict], *, as_of: date) -> dict:
    """The Agent tools' indicator snapshot at the latest close (D14) with the concept of every value."""
    return {'as_of': as_of.isoformat(), 'values': tools.indicators(bars, spy_bars),
            'concepts': dict(reasoning.TOOL_CONCEPTS['get_indicators']['fields'])}


def context_view(*, earnings: dict | None, regime: dict | None, sector_etf: str | None, session: date) -> dict:
    """The background block: ``{earnings, regime, sector}``, each None when there is nothing to show."""
    earnings_view = None
    if earnings is not None:
        day = earnings.get('earnings_date')
        known = earnings.get('status') == 'known' and day is not None
        earnings_view = {'date': day.isoformat() if day else None, 'status': earnings.get('status'),
                         'sessions_until': sessions_until(day, session) if known and day >= session else None}
    regime_view = None
    if regime is not None:
        regime_view = {'label': regime.get('label'), 'session': regime['session'].isoformat()}
    sector_view = None
    if sector_etf:
        snap = (regime or {}).get('sectors', {}).get(sector_etf) or {}
        sector_view = {'etf': sector_etf, 'state': snap.get('state'), 'rs20': snap.get('rs20'),
                       'rs60': snap.get('rs60')}
    return {'earnings': earnings_view, 'regime': regime_view, 'sector': sector_view}
