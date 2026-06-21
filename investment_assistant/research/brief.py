from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def build_research_brief(*, ticker: str, thesis: str, evidence: list[str]) -> dict[str, Any]:
    """Build a minimal ResearchBrief artifact for manual research review."""
    normalized_ticker = ticker.strip().upper()
    normalized_evidence = _string_list(evidence)
    return {
        "artifact_type": "ResearchBrief",
        "stage": "Research",
        "source": "research.brief",
        "generated_at": datetime.now(UTC).isoformat(),
        "ticker": normalized_ticker,
        "thesis": thesis.strip(),
        "evidence": normalized_evidence,
        "core_drivers": _core_drivers(normalized_evidence),
        "macro_sensitivities": ["宏观状态变化可能改变研究优先级。"],
        "valuation_sensitivities": ["估值敏感性需要在后续深度研究中补充。"],
        "catalysts": ["等待可验证催化剂或事件驱动信号。"],
        "invalidations": ["核心证据失效或宏观环境转为防守时，需要重新评估。"],
        "next_action": "进入人工深度研究；补充基本面、估值和反方证据。",
    }


def _core_drivers(evidence: list[str]) -> list[str]:
    if not evidence:
        return ["暂无明确驱动，需要先补充证据。"]
    return [f"证据驱动：{item}" for item in evidence[:5]]


def _string_list(value: list[str]) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()]
