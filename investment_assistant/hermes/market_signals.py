from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def interpret_market_signals(rows: list[dict[str, Any]], *, window: int = 30) -> dict[str, Any]:
    """Build a deterministic Hermes interpretation for recent market signals.

    This is intentionally rule-based for now so the dashboard can call Hermes
    without depending on an external LLM provider. The output shape is stable and
    can later be backed by a model-generated narrative.
    """
    normalized = [_normalize_row(row) for row in rows]
    sample_size = len(normalized)
    counts = Counter(row["market_status"] for row in normalized if row.get("market_status"))
    latest = normalized[0] if normalized else {}
    total = max(sample_size, 1)
    green_ratio = counts.get("green", 0) / total
    red_ratio = counts.get("red", 0) / total
    above_ma_ratio = _ratio(row.get("spy_above_200ma") is True for row in normalized)
    avg_vix = _average(row.get("vix_close") for row in normalized)

    judgement = _judge(latest.get("market_status"), green_ratio, red_ratio, above_ma_ratio, avg_vix)
    title, summary = _narrative(judgement, sample_size, latest.get("market_status"), avg_vix)

    return {
        "source": "hermes.market_signals",
        "window": window,
        "sample_size": sample_size,
        "generated_at": datetime.now(UTC).isoformat(),
        "judgement": judgement,
        "title": title,
        "summary": summary,
        "metrics": {
            "green_ratio": green_ratio,
            "red_ratio": red_ratio,
            "above_ma_ratio": above_ma_ratio,
            "avg_vix": avg_vix,
            "status_counts": {"green": counts.get("green", 0), "yellow": counts.get("yellow", 0), "red": counts.get("red", 0)},
            "latest_status": latest.get("market_status", "unknown"),
        },
        "sections": [
            {
                "title": "过去一个月市场结构",
                "items": [
                    f"最近 {sample_size} 条信号中，绿色占比 {green_ratio:.0%}，红色占比 {red_ratio:.0%}。",
                    f"SPY 位于 200MA 上方的样本占比 {above_ma_ratio:.0%}。",
                    f"VIX 平均值 {avg_vix:.1f}，最新状态为 {latest.get('market_status', 'unknown')}。",
                ] if sample_size else ["暂无可解读的市场信号样本。"],
            }
        ],
        "actions": _actions(judgement, sample_size),
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_date": str(row.get("signal_date", "")),
        "market_status": str(row.get("market_status", "unknown")).lower(),
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
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def _ratio(values) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for value in items if value) / len(items)


def _judge(latest_status: str | None, green_ratio: float, red_ratio: float, above_ma_ratio: float, avg_vix: float) -> str:
    if latest_status == "red" or red_ratio >= 0.3 or avg_vix >= 25:
        return "risk_off"
    if latest_status == "green" and green_ratio >= 0.6 and above_ma_ratio >= 0.6:
        return "risk_on"
    return "neutral"


def _narrative(judgement: str, sample_size: int, latest_status: str | None, avg_vix: float) -> tuple[str, str]:
    if sample_size == 0:
        return "样本不足", "Hermes 需要先拉取最近一个月市场信号，再生成解读。"
    if judgement == "risk_on":
        return "市场环境偏积极", f"最近样本支持正常观察候选机会；最新状态为 {latest_status}，平均 VIX 约 {avg_vix:.1f}。"
    if judgement == "risk_off":
        return "市场风险偏高", f"最近样本出现较高风险信号；最新状态为 {latest_status}，平均 VIX 约 {avg_vix:.1f}。"
    return "市场环境中性", f"最近样本方向不够一致；最新状态为 {latest_status}，平均 VIX 约 {avg_vix:.1f}。"


def _actions(judgement: str, sample_size: int) -> list[str]:
    if sample_size == 0:
        return ["在“手动拉取”中回补最近一个月市场信号。"]
    if judgement == "risk_on":
        return ["允许继续筛选 watchlist 机会。", "优先寻找基本面和技术面共振的标的。", "维持单笔风险上限。"]
    if judgement == "risk_off":
        return ["暂停新增高波动仓位。", "复核已有持仓风险暴露。", "等待红色信号收敛或 SPY 重新站稳均线。"]
    return ["保持观察，不急于放大仓位。", "等待连续绿色信号或 VIX 回落确认。", "继续补齐个股层面的财报与技术信号。"]
