from datetime import date

from investment_assistant.notify.message import Notification, NotifyField
from investment_assistant.workbench.regime import LABEL_TEXT

MAX_FIELD = 1024
MAX_MESSAGE = 6000
ACTIONS = {'buy': '买入', 'sell': '卖出', 'watch': '观察'}
SOURCE_NAMES = {'bars': '日线', 'news': '资讯', 'earnings': '财报日期', 'sec': 'SEC', 'etf_bars': 'ETF 日线',
                'fred': 'FRED', 'regime': '区制', 'budget': '耗时'}
_SECTOR_STATE = {'strong': '强', 'weak': '弱', 'mixed': '分化'}


def _fred_missing_text(market: dict) -> str:
    """Why no FRED value is shown: no key, a failed fetch, or simply no stored rows."""
    status = list(((market.get('inputs') or {}).get('macro_status') or {}).values())
    if status and all(s == 'not_configured' for s in status):
        return 'FRED 未配置'
    if 'error' in status:
        return 'FRED 采集失败（见异常段）'
    return 'FRED 无数据'


def _market_environment(market: dict | None) -> str:
    """One line block for the overview market field; absent snapshot or FRED says so plainly."""
    if not market:
        return '市场环境未生成'
    breadth = market.get('breadth') or {}
    lines = []
    label = LABEL_TEXT.get(market.get('label'))
    head = (f"区制 {label} · 站上 MA50 {breadth['pct_50']:.1%} · MA200 {breadth['pct_200']:.1%}"
            f" · 新高 {breadth.get('new_highs', 0)} / 新低 {breadth.get('new_lows', 0)}"
            if label is not None and breadth.get('pct_50') is not None and breadth.get('pct_200') is not None
            else f"区制 {label or '未知'}")
    lines.append(head)
    sectors = market.get('sectors') or {}
    if sectors:
        parts = []
        for etf, view in sectors.items():
            if view is None:
                parts.append(f"{etf} 数据不足")
            else:
                parts.append(f"{etf} {view['rs20']:+.1%} {_SECTOR_STATE.get(view.get('state'), '数据不足')}")
        lines.append(' · '.join(parts))
    macro = market.get('macro') or {}
    if not any(view is not None for view in macro.values()):
        lines.append(_fred_missing_text(market))
    else:
        hy, curve = macro.get('BAMLH0A0HYM2'), macro.get('T10Y2Y')
        parts = []
        for name, view in (('HY OAS', hy), ('2s10s', curve)):
            if view is None:
                parts.append(f'{name} 无数据')
            else:
                # JSONB round-trips the FRED Decimals as strings; format numerically either way.
                change = f"{float(view['change']):+}" if view.get('change') is not None else '无变化'
                parts.append(f"{name} {view['value']}（20 期 {change}）")
        lines.append(' · '.join(parts))
    return '\n'.join(lines)


def _clip_field(fields: list[NotifyField], name: str, value: str) -> None:
    if len(value) > MAX_FIELD:
        value = value[:MAX_FIELD - 1] + '…'
    fields.append(NotifyField(name, value))


def _fit_message(title: str, fields: list[NotifyField], footer: str) -> Notification:
    """Drop whole fields until the message fits Discord's 6000 chars; note what was dropped."""
    dropped = 0
    while fields and (len(title) + sum(len(f.name) + len(f.value) for f in fields) + len(footer)) > MAX_MESSAGE:
        fields.pop()
        dropped += 1
    if dropped:
        fields.append(NotifyField('溢出', f'其余 {dropped} 条见系统'))
    return Notification(title=title, color=5198940, fields=fields, footer=footer)


def date_label_for(start: date | None, end: date | None) -> str:
    if start is None:
        return date.today().isoformat()
    if end is None or end == start:
        return start.isoformat()
    return f"{start.isoformat()} ~ {end.isoformat()}"


def _footer() -> str:
    return f"earning-agent • {date.today().isoformat()}"


def metrics_summary(summary: dict, *, date_label: str | None = None) -> Notification:
    label = date_label or date.today().isoformat()
    days = summary.get("days")
    if days:
        rows = "\n".join(
            f"• {d.get('date')} — " + (f"❌ {d.get('error')}" if d.get("error")
                                       else str(d.get("market_status", "?")).upper())
            for d in days[:15]
        ) or "无"
        fields = [NotifyField(f"回补 ({len(days)} 天)", rows)]
    else:
        status = str(summary.get("market_status", "?")).upper()
        vix = summary.get("vix")
        tickers = summary.get("tickers", [])
        rows = "\n".join(f"• **{t.get('ticker')}** — {t.get('trend_state', '?')}" for t in tickers[:10]) or "无"
        fields = [
            NotifyField("市场环境", f"{status} | VIX {vix}"),
            NotifyField(f"关注列表 ({len(tickers)})", rows),
        ]
    return Notification(title=f"🗓 每日指标 · {label}", color=3447003, fields=fields, footer=_footer())


def filings_digest(summary: dict, *, date_label: str | None = None) -> Notification:
    label = date_label or date.today().isoformat()
    filings = summary.get("filings", [])
    rows = "\n".join(
        f"• **{f.get('ticker')}** {f.get('form')} — {f.get('filing_date') or f.get('filed_at', '')}"
        for f in filings[:15]
    ) or "该日期无新财报"
    fields = [NotifyField(f"新提交 ({summary.get('downloaded_count', 0)})", rows)]
    return Notification(title=f"📄 财报 · {label}", color=15844367, fields=fields, footer=_footer())


def scores_summary(summary: dict, *, date_label: str | None = None) -> Notification:
    label = date_label or date.today().isoformat()
    days = summary.get("days")
    if days:
        listing = "\n".join(
            f"• {d.get('date')} — " + (f"❌ {d.get('error')}" if d.get("error")
                                       else f"{d.get('count', 0)} 条评分")
            for d in days[:15]
        ) or "无"
        fields = [NotifyField(f"回补 ({len(days)} 天)", listing)]
    else:
        rows = summary.get("rows", [])
        listing = "\n".join(f"• **{r.get('ticker')}** — {r.get('score')}" for r in rows[:10]) or "无评分"
        fields = [NotifyField(f"评分 ({len(rows)})", listing)]
    return Notification(title=f"📈 策略评分 · {label}", color=10070709, fields=fields, footer=_footer())


def workbench_digest(digest: dict) -> list[Notification]:
    """Overview, new plans, holdings, pending/errors: one message each (design §7.2)."""
    session = digest.get('session', '')
    overview = digest.get('overview', {})
    lines = [f"交易日 {session}", f"新计划 {overview.get('new_plans', 0)} · 持仓 {overview.get('holdings', 0)}",
             f"待处理 {overview.get('pending', 0)} · 异常 {overview.get('errors', 0)}"]
    if overview.get('extended_plans'):
        lines.append(f"扩展池新计划 {overview['extended_plans']} 份（不推送）")
    if overview.get('core_empty'):
        lines.append('核心池为空，只推送持仓')
    if overview.get('last_push_failed'):
        lines.append('⚠️ 上次推送失败，请核对')
    overview_fields = [NotifyField('概览', '\n'.join(lines)),
                       NotifyField('市场环境', _market_environment(overview.get('market')))]
    overview_msg = _fit_message(f"📊 工作台 · {session}", overview_fields, _footer())

    fields: list[NotifyField] = []
    plans = digest.get('plans') or []
    if not plans:
        _clip_field(fields, '新计划', '今日无新计划')
    for p in plans:
        sizing = '缺资金快照，无法计算' if p.get('sizing_status') == 'no_equity' else (
            f"{p.get('shares')} 股 · 风险 {p.get('risk_amount')}")
        funding = f"资金日 {p['snapshot_as_of']}" if p.get('snapshot_as_of') else None
        notes = '；'.join([*(f"提示 {w}" for w in p.get('warnings', [])),
                           *(f"作废 {r}" for r in p.get('invalid_reasons', []))])
        head = f"动作 {ACTIONS.get(p.get('action'), p.get('action'))} · {'、'.join(p.get('rule_ids') or [])} · {p.get('plan_version')}"
        sector = p.get('sector')
        sector_text = (f"行业 {sector['etf']} {_SECTOR_STATE.get(sector.get('state'), '数据不足')}"
                       if sector else '行业 未映射')
        context = f"区制 {LABEL_TEXT.get(p.get('regime_label'), '未知')} · 下次财报 {p.get('next_earnings') or '未知'} · {sector_text}"
        _clip_field(fields, p['ticker'], '；'.join(filter(None, [
            head,
            context,
            f"区间 {p['entry_low']}–{p['entry_high']} · 止损 {p['stop']} · T1 {p['target1']}",
            f"仓位 {sizing}", funding, f"有效期 至 {p['valid_until']}", notes, p.get('evidence', ''),
            p.get('brief_summary') or '', p.get('contra') or '', p.get('url', '')])) or '—')
    plans_msg = _fit_message(f"🆕 新计划 · {session}", fields, _footer())

    fields = []
    for h in digest.get('holdings') or []:
        stop_line = f"止损 {h.get('stop')}（{h.get('mode')}）" if h.get('stop') is not None else '无计划持仓（position_drawdown）'
        t1 = '已触 T1' if h.get('t1_reached') else '未触 T1'
        pct = ''
        if h.get('to_stop_pct') is not None:
            pct = f"距止损 {h['to_stop_pct']:+.1%} · 距 T1 {h.get('to_target_pct', 0):+.1%}"
        eve = '⚠️ 下一交易日为财报日' if h.get('earnings_eve') else ''
        alerts = ''
        if 'plan_stop' in (h.get('plan_alerts') or []):
            alerts = '⚠️ 今日触发 plan_stop，请核对券商止损单是否已成交'
        elif 'plan_target' in (h.get('plan_alerts') or []):
            alerts = '今日触发 plan_target（卖出一半）'
        _clip_field(fields, h['ticker'], '；'.join(filter(None, [
            f"{h.get('quantity')} 股 @ {h.get('avg_cost')}", stop_line, t1, pct, eve, alerts])) or '—')
    holdings_msg = _fit_message(f"💼 持仓 · {session}", fields, _footer())

    fields = []
    pending = digest.get('pending') or {}
    undecided = pending.get('undecided') or []
    _clip_field(fields, f"未决定单元 ({len(undecided)})",
                '\n'.join(undecided) or '无')
    expiring = pending.get('expiring') or []
    _clip_field(fields, f"即将过期计划 ({len(expiring)})",
                '\n'.join(f"{e['ticker']} 至 {e['valid_until']}" for e in expiring) or '无')
    errors = digest.get('errors') or []
    _clip_field(fields, f"异常 ({len(errors)})", '\n'.join(errors) or '无')
    for source, items in (digest.get('errors_by_source') or {}).items():
        if items:
            _clip_field(fields, SOURCE_NAMES.get(source, source), '\n'.join(str(i) for i in items))
    pending_msg = _fit_message(f"⏳ 待处理与异常 · {session}", fields, _footer())
    return [overview_msg, plans_msg, holdings_msg, pending_msg]


def workbench_closed(ny_date) -> list[Notification]:
    return [Notification(title=f"🛌 纽约休市，未运行 · {ny_date.isoformat()}", color=9807270,
                         fields=[], footer=_footer())]
