from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

_STATE_LABELS = {"offense": "进攻", "cautious": "谨慎", "defense": "防守"}


def analyze_macro_environment(
    rows: list[dict[str, Any]],
    *,
    window: int = 30,
    watchlist: list[str] | None = None,
) -> dict[str, Any]:
    """Build a MacroSnapshot-style analysis for the investment decision pipeline.

    This upgrades the old narrow market-signal interpretation into the Research
    stage's macro analyst output. It remains deterministic so the dashboard is
    reliable without a model key; DeepSeek can later enhance the narrative over
    this same structured payload.
    """
    normalized = [_normalize_row(row) for row in rows]
    watchlist = [item.strip().upper() for item in (watchlist or []) if item.strip()]
    sample_size = len(normalized)
    counts = Counter(row["market_status"] for row in normalized if row.get("market_status"))
    latest = normalized[0] if normalized else {}
    total = max(sample_size, 1)
    green_ratio = counts.get("green", 0) / total
    red_ratio = counts.get("red", 0) / total
    above_200_ratio = _ratio(row.get("spy_above_200ma") is True for row in normalized)
    avg_vix = _average(row.get("vix_close") for row in normalized)

    macro_state = _classify_macro_state(
        latest_status=latest.get("market_status"),
        green_ratio=green_ratio,
        red_ratio=red_ratio,
        above_200_ratio=above_200_ratio,
        avg_vix=avg_vix,
    )
    stance_label = _STATE_LABELS[macro_state]
    title, summary = _narrative(macro_state, latest.get("market_status"), avg_vix, sample_size)
    metrics = _metrics(counts, green_ratio, red_ratio, above_200_ratio, avg_vix, latest)

    return {
        "source": "hermes.macro_analyst",
        "agent_role": "macro_analyst",
        "stage": "Research",
        "artifact_type": "MacroSnapshot",
        "window": window,
        "sample_size": sample_size,
        "generated_at": datetime.now(UTC).isoformat(),
        "macro_state": macro_state,
        "stance_label": stance_label,
        "judgement": _legacy_judgement(macro_state),
        "title": title,
        "summary": summary,
        "macro_snapshot": {
            "stage": "Research",
            "artifact_type": "MacroSnapshot",
            "state": macro_state,
            "stance": stance_label,
            "watchlist": watchlist,
            "metrics": metrics,
        },
        "metrics": {
            "green_ratio": green_ratio,
            "red_ratio": red_ratio,
            "above_ma_ratio": above_200_ratio,
            "avg_vix": avg_vix,
            "latest_status": latest.get("market_status", "unknown"),
            "status_counts": {"green": counts.get("green", 0), "yellow": counts.get("yellow", 0), "red": counts.get("red", 0)},
        },
        "key_changes": _key_changes(macro_state, sample_size, green_ratio, red_ratio, above_200_ratio, avg_vix),
        "growth_implications": _growth_implications(macro_state),
        "watchlist_implications": _watchlist_implications(watchlist, macro_state),
        "next_checks": _next_checks(macro_state),
        "sections": _sections(macro_state, sample_size, green_ratio, red_ratio, above_200_ratio, avg_vix),
        "actions": _actions(macro_state, sample_size),
        "llm": {"provider": "deepseek", "mode": "optional", "used": False},
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_date": str(row.get("signal_date", "")),
        "market_status": str(row.get("market_status", "unknown")).lower(),
        "spy_close": _number(row.get("spy_close")),
        "spy_ma200": _number(row.get("spy_ma200")),
        "spy_above_200ma": row.get("spy_above_200ma"),
        "vix_close": _number(row.get("vix_close")),
    }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _average(values) -> float:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else 0.0


def _ratio(values) -> float:
    items = list(values)
    return sum(1 for value in items if value) / len(items) if items else 0.0


def _classify_macro_state(
    *,
    latest_status: str | None,
    green_ratio: float,
    red_ratio: float,
    above_200_ratio: float,
    avg_vix: float,
) -> str:
    if latest_status == "red" or red_ratio >= 0.3 or avg_vix >= 25 or above_200_ratio < 0.45:
        return "defense"
    if latest_status == "green" and green_ratio >= 0.6 and above_200_ratio >= 0.6 and avg_vix <= 20:
        return "offense"
    return "cautious"


def _legacy_judgement(macro_state: str) -> str:
    if macro_state == "offense":
        return "risk_on"
    if macro_state == "defense":
        return "risk_off"
    return "neutral"


def _narrative(macro_state: str, latest_status: str | None, avg_vix: float, sample_size: int) -> tuple[str, str]:
    if sample_size == 0:
        return "宏观样本不足", "宏观分析师需要先拉取市场信号或接入 MacroSnapshot artifact。"
    if macro_state == "offense":
        return "宏观环境偏进攻", f"最近窗口支持提高研究进攻性；最新市场信号为 {latest_status}，平均 VIX 约 {avg_vix:.1f}。"
    if macro_state == "defense":
        return "宏观环境偏防守", f"最近窗口出现防守约束；最新市场信号为 {latest_status}，平均 VIX 约 {avg_vix:.1f}。"
    return "宏观环境偏谨慎", f"最近窗口方向不够一致；最新市场信号为 {latest_status}，平均 VIX 约 {avg_vix:.1f}。"


def _metrics(counts: Counter, green_ratio: float, red_ratio: float, above_200_ratio: float, avg_vix: float, latest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"key": "market_status_mix", "label": "市场信号分布", "value": {"green": counts.get("green", 0), "yellow": counts.get("yellow", 0), "red": counts.get("red", 0)}, "interpretation": f"绿色占比 {green_ratio:.0%}，红色占比 {red_ratio:.0%}。"},
        {"key": "spy_200ma", "label": "SPY 200MA 趋势过滤", "value": above_200_ratio, "unit": "ratio", "interpretation": f"SPY 高于 200MA 的样本占比 {above_200_ratio:.0%}。"},
        {"key": "vix", "label": "VIX 风险偏好", "value": avg_vix, "unit": "points", "interpretation": f"窗口平均 VIX {avg_vix:.1f}，最新状态 {latest.get('market_status', 'unknown')}。"},
    ]


def _key_changes(macro_state: str, sample_size: int, green_ratio: float, red_ratio: float, above_200_ratio: float, avg_vix: float) -> list[str]:
    if sample_size == 0:
        return ["暂无足够样本判断宏观变化。"]
    changes = [f"最近样本中绿色信号占比 {green_ratio:.0%}，红色信号占比 {red_ratio:.0%}。", f"SPY 200MA 趋势过滤通过率 {above_200_ratio:.0%}。", f"窗口平均 VIX 约 {avg_vix:.1f}。"]
    if macro_state == "defense":
        changes.append("防守触发来自红色信号、VIX 或趋势过滤中的至少一项约束。")
    elif macro_state == "offense":
        changes.append("进攻判断来自绿色信号、低波动和趋势过滤的共振。")
    else:
        changes.append("谨慎判断来自信号不一致或趋势/波动约束未完全解除。")
    return changes


def _growth_implications(macro_state: str) -> list[str]:
    if macro_state == "offense":
        return ["允许继续推进高 beta 成长股研究。", "仍需区分公司 alpha 与 QQQ beta，避免只因指数强势放大仓位。"]
    if macro_state == "defense":
        return ["高估值成长股进入防守复核优先级。", "新增研究可以继续，但执行计划应默认降风险。"]
    return ["适合推进研究简表和回测，不适合无条件扩大仓位。", "等待 VIX、SPY/QQQ 趋势或信用风险出现更清晰方向。"]


def _watchlist_implications(watchlist: list[str], macro_state: str) -> list[str]:
    prefix = ", ".join(watchlist) if watchlist else "当前 watchlist"
    if macro_state == "offense":
        return [f"{prefix}: 可以继续筛选候选机会，但每个标的必须写清宏观敏感变量。", "优先推进 TSLA/NVDA/MU/CRDO 等已有样本，不扩大 watchlist。"]
    if macro_state == "defense":
        return [f"{prefix}: 优先复核失效条件和仓位风险，不急于新增 setup。", "回测结论需要加入市场过滤，避免把 beta 当 alpha。"]
    return [f"{prefix}: 继续研究，但下一动作应落到继续研究/决策挑战/回测 setup 三选一。", "暂不扩大 watchlist，先补齐现有样本的 ResearchBrief。"]


def _next_checks(macro_state: str) -> list[str]:
    checks = ["VIX 是否突破 20 或 25。", "SPY/QQQ 是否跌破 50 日或 200 日均线。", "10 年期美债是否重新上行并压制成长股估值。", "高收益债利差是否快速走阔。"]
    if macro_state == "offense":
        checks.append("进攻状态是否被连续黄色/红色信号破坏。")
    return checks


def _sections(macro_state: str, sample_size: int, green_ratio: float, red_ratio: float, above_200_ratio: float, avg_vix: float) -> list[dict[str, Any]]:
    return [
        {"title": "宏观状态判定", "items": _key_changes(macro_state, sample_size, green_ratio, red_ratio, above_200_ratio, avg_vix)},
        {"title": "对美股成长股的影响", "items": _growth_implications(macro_state)},
    ]


def _actions(macro_state: str, sample_size: int) -> list[str]:
    if sample_size == 0:
        return ["先回补最近一个月市场信号或接入 vts MacroSnapshot。"]
    if macro_state == "offense":
        return ["推进 1-2 个 watchlist 研究简表。", "选择一个带市场过滤的 setup 进入回测候选。", "保持人工闸门，不自动生成交易指令。"]
    if macro_state == "defense":
        return ["暂停新增高 beta 执行计划。", "复核已有观点的失效条件。", "等待风险指标回落后再恢复进攻性研究。"]
    return ["继续研究但不放大仓位。", "优先做决策挑战和回测验证。", "等待宏观状态转向更明确。"]
