from typing import Any


def score_trend_relative_strength(snapshot: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    score = 0
    evidence: list[str] = []
    limits: list[str] = []
    reasons = set(snapshot.get("trigger_reason", []))

    if snapshot.get("trend_state") == "uptrend":
        score += 30
        evidence.append("uptrend")
    if "above_ma_stack" in reasons:
        score += 20
        evidence.append("above_ma_stack")
    if "outperform_spy" in reasons:
        score += 15
        evidence.append("outperform_spy")
    if "outperform_qqq" in reasons:
        score += 15
        evidence.append("outperform_qqq")
    if "volume_expansion" in reasons:
        score += 10
        evidence.append("volume_expansion")
    if market.get("macro_state") == "offense":
        score += 10
        evidence.append("macro_offense")

    if not evidence:
        limits.append("no positive trend evidence")
    limits.append("strategy score is evidence, not trading instruction")

    return {
        "ticker": snapshot["ticker"],
        "strategy": "trend_relative_strength",
        "score": min(score, 100),
        "evidence": evidence,
        "limits": limits,
    }
