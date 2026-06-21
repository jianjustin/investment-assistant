from __future__ import annotations

from typing import Any


def classify_ticker_trend(
    *,
    ticker: str,
    close: float,
    ma20: float,
    ma50: float,
    ma200: float,
    volume_ratio: float,
    relative_strength_spy: float,
    relative_strength_qqq: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    if close > ma20 > ma50 > ma200:
        reasons.append("above_ma_stack")
    if volume_ratio >= 1.5:
        reasons.append("volume_expansion")
    if relative_strength_spy > 0:
        reasons.append("outperform_spy")
    if relative_strength_qqq > 0:
        reasons.append("outperform_qqq")

    if "above_ma_stack" in reasons and ("outperform_spy" in reasons or "outperform_qqq" in reasons):
        trend_state = "uptrend"
    elif close < ma50 < ma200:
        trend_state = "downtrend"
    elif volume_ratio >= 2:
        trend_state = "volatile"
    else:
        trend_state = "base"

    attention_level = "high" if len(reasons) >= 3 else "medium" if reasons else "low"
    return {"ticker": ticker.upper(), "trend_state": trend_state, "attention_level": attention_level, "trigger_reason": reasons}
