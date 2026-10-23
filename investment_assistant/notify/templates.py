from datetime import date

from investment_assistant.notify.message import Notification, NotifyField

MAX_FIELD = 1024
MAX_MESSAGE = 6000


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
    if overview.get('last_push_failed'):
        lines.append('⚠️ 上次推送失败，请核对')
    overview_msg = _fit_message(f"📊 工作台 · {session}", [NotifyField('概览', '\n'.join(lines))], _footer())

    fields: list[NotifyField] = []
    plans = digest.get('plans') or []
    if not plans:
        _clip_field(fields, '新计划', '今日无新计划')
    for p in plans:
        sizing = f"{p.get('shares')} 股 · 风险 {p.get('risk_amount')}" if p.get('shares') is not None else '缺资金快照，无法计算'
        if p.get('sizing_status') == 'no_equity':
            sizing = '缺资金快照，无法计算'
        notes = '；'.join([*(f"提示 {w}" for w in p.get('warnings', [])),
                           *(f"作废 {r}" for r in p.get('invalid_reasons', []))])
        summary = p.get('brief_summary') or ''
        _clip_field(fields, p['ticker'], '；'.join(filter(None, [
            f"区间 {p['entry_low']}–{p['entry_high']} · 止损 {p['stop']} · T1 {p['target1']}",
            f"仓位 {sizing}", f"有效期 至 {p['valid_until']}", notes, p.get('evidence', ''),
            summary, p.get('url', '')])) or '—')
    plans_msg = _fit_message(f"🆕 新计划 · {session}", fields, _footer())

    fields = []
    for h in digest.get('holdings') or []:
        stop_line = f"止损 {h.get('stop')}（{h.get('mode')}）" if h.get('stop') is not None else '无计划持仓（position_drawdown）'
        t1 = '已触 T1' if h.get('t1_reached') else '未触 T1'
        pct = ''
        if h.get('to_stop_pct') is not None:
            pct = f"距止损 {h['to_stop_pct']:+.1%} · 距 T1 {h.get('to_target_pct', 0):+.1%}"
        eve = '⚠️ 下一交易日为财报日' if h.get('earnings_eve') else ''
        _clip_field(fields, h['ticker'], '；'.join(filter(None, [
            f"{h.get('quantity')} 股 @ {h.get('avg_cost')}", stop_line, t1, pct, eve])) or '—')
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
    pending_msg = _fit_message(f"⏳ 待处理与异常 · {session}", fields, _footer())
    return [overview_msg, plans_msg, holdings_msg, pending_msg]


def workbench_closed(ny_date) -> list[Notification]:
    return [Notification(title=f"🛌 纽约休市，未运行 · {ny_date.isoformat()}", color=9807270,
                         fields=[], footer=_footer())]
