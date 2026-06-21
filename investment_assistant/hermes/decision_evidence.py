from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable

from investment_assistant.hermes.deepseek_client import request_json_completion

_STATE_LABELS = {"offense": "进攻", "cautious": "谨慎", "defense": "防守"}


def build_decision_evidence(
    *,
    macro: dict[str, Any],
    ticker_signals: list[dict[str, Any]],
    strategy_scores: list[dict[str, Any]],
    use_llm: bool = False,
    model: str = "deepseek-v4-pro",
    llm_client: Callable[..., dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Aggregate decision evidence from macro, ticker trend and strategy score artifacts.

    The deterministic payload is the reliable baseline. Optional LLM enhancement
    can refine the narrative without changing this core evidence contract.
    """
    macro_state = str(macro.get("macro_state") or macro.get("state") or "unknown")
    market_context = _market_context(macro, macro_state)
    ticker_focus = _ticker_focus(ticker_signals)
    strategy_evidence = _strategy_evidence(strategy_scores)
    result = {
        "source": "hermes.decision_evidence",
        "agent_role": "decision_evidence_builder",
        "stage": "DecisionSupport",
        "artifact_type": "DecisionEvidence",
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": _summary(macro_state, ticker_focus, strategy_evidence),
        "market_context": market_context,
        "ticker_focus": ticker_focus,
        "strategy_evidence": strategy_evidence,
        "risk_questions": _risk_questions(macro_state, ticker_focus, strategy_evidence),
        "next_actions": _next_actions(macro_state, ticker_focus, strategy_evidence),
        "llm": {"provider": "deepseek", "mode": "optional", "used": False, "model": model, "error": None},
        "llm_interpretation": None,
    }
    if use_llm:
        return _attach_llm_interpretation(result, model=model, llm_client=llm_client)
    return result


def _attach_llm_interpretation(
    result: dict[str, Any],
    *,
    model: str,
    llm_client: Callable[..., dict[str, Any] | None] | None,
) -> dict[str, Any]:
    client = llm_client or request_json_completion
    llm_payload = client(system_prompt=_DECISION_EVIDENCE_LLM_SYSTEM_PROMPT, user_payload=_llm_user_payload(result), model=model)
    if not llm_payload:
        result["llm"] = {"provider": "deepseek", "mode": "fallback", "used": False, "model": model, "error": "DeepSeek 未配置或调用失败，已保留规则版决策依据。"}
        result["llm_interpretation"] = None
        return result

    interpretation = _normalize_llm_payload(llm_payload)
    result["llm"] = {"provider": "deepseek", "mode": "enabled", "used": True, "model": model, "error": None}
    result["llm_interpretation"] = interpretation
    for key in ["summary", "risk_questions", "next_actions"]:
        if interpretation.get(key):
            result[key] = interpretation[key]
    return result


_DECISION_EVIDENCE_LLM_SYSTEM_PROMPT = """你是 Hermes 投资助手中的决策依据聚合器，承接 Research、Viewpoint 和 Plan 前的人工决策支持阶段。
你只基于输入的宏观状态、watchlist 趋势和策略评分生成可追溯解释，不做自动交易指令，不承诺收益。
必须输出严格 JSON，字段为：summary:string, risk_questions:string[], next_actions:string[]。
所有内容使用中文，并清楚区分证据、风险和下一步人工动作。
"""


def _llm_user_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "enhance_decision_evidence",
        "stage": result.get("stage"),
        "artifact_type": result.get("artifact_type"),
        "summary": result.get("summary"),
        "market_context": result.get("market_context"),
        "ticker_focus": result.get("ticker_focus"),
        "strategy_evidence": result.get("strategy_evidence"),
        "risk_questions": result.get("risk_questions"),
        "next_actions": result.get("next_actions"),
        "required_output_schema": {
            "summary": "string",
            "risk_questions": ["string"],
            "next_actions": ["string"],
        },
    }


def _normalize_llm_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(payload.get("summary", "")).strip(),
        "risk_questions": _string_list(payload.get("risk_questions")),
        "next_actions": _string_list(payload.get("next_actions")),
    }


def _market_context(macro: dict[str, Any], macro_state: str) -> dict[str, Any]:
    return {
        "macro_state": macro_state,
        "stance_label": macro.get("stance_label") or _STATE_LABELS.get(macro_state, "未知"),
        "judgement": macro.get("judgement"),
        "summary": str(macro.get("summary") or "暂无宏观摘要。"),
        "source": macro.get("source"),
        "window": macro.get("window"),
        "sample_size": macro.get("sample_size"),
        "metrics": macro.get("metrics") or {},
    }


def _ticker_focus(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_ticker_signal(row) for row in rows if row.get("ticker")]
    priority = {"high": 0, "medium": 1, "low": 2}
    normalized.sort(key=lambda row: (priority.get(str(row.get("attention_level")), 3), str(row.get("ticker"))))
    return normalized[:20]


def _normalize_ticker_signal(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": str(row.get("ticker", "")).upper(),
        "signal_date": _string_or_none(row.get("signal_date")),
        "trend_state": str(row.get("trend_state") or "unknown"),
        "attention_level": str(row.get("attention_level") or "low"),
        "trigger_reason": _string_list(row.get("trigger_reason")),
        "relative_strength_spy": _number(row.get("relative_strength_spy")),
        "relative_strength_qqq": _number(row.get("relative_strength_qqq")),
        "volume_ratio": _number(row.get("volume_ratio")),
    }


def _strategy_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_strategy_score(row) for row in rows if row.get("ticker")]
    normalized.sort(key=lambda row: (-float(row.get("score") or 0), str(row.get("ticker"))))
    return normalized[:20]


def _normalize_strategy_score(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": str(row.get("ticker", "")).upper(),
        "score_date": _string_or_none(row.get("score_date")),
        "strategy": str(row.get("strategy") or "unknown"),
        "score": _number(row.get("score")) or 0,
        "evidence": _string_list(row.get("evidence")),
        "limits": _string_list(row.get("limits")),
        "run_id": row.get("run_id"),
    }


def _summary(macro_state: str, ticker_focus: list[dict[str, Any]], strategy_evidence: list[dict[str, Any]]) -> str:
    stance = _STATE_LABELS.get(macro_state, "未知")
    top = strategy_evidence[0] if strategy_evidence else None
    if top:
        return f"宏观状态为{stance}；当前重点标的 {len(ticker_focus)} 个，最高策略评分为 {top['ticker']} {top['score']:.0f} 分。"
    return f"宏观状态为{stance}；当前重点标的 {len(ticker_focus)} 个，暂无策略评分可作为确认信号。"


def _risk_questions(macro_state: str, ticker_focus: list[dict[str, Any]], strategy_evidence: list[dict[str, Any]]) -> list[str]:
    questions = ["当前结论是否被最新宏观状态、标的趋势和策略评分同时支持？"]
    if macro_state == "offense":
        questions.append("进攻环境下是否仍存在 VIX 抬升、假突破或个股相对强度回落？")
    elif macro_state == "defense":
        questions.append("防守环境下是否应降低新开仓优先级，只保留观察和风控动作？")
    else:
        questions.append("谨慎环境下是否需要等待宏观或个股趋势给出更一致的确认？")
    if not ticker_focus:
        questions.append("watchlist 是否缺少最新趋势扫描，导致无法判断标的优先级？")
    if not strategy_evidence:
        questions.append("是否需要先运行策略评分，避免只凭宏观或单一价格信号判断？")
    return questions


def _next_actions(macro_state: str, ticker_focus: list[dict[str, Any]], strategy_evidence: list[dict[str, Any]]) -> list[str]:
    actions = []
    if not ticker_focus:
        actions.append("先运行 watchlist 趋势扫描，补齐标的级趋势输入。")
    if not strategy_evidence:
        actions.append("运行策略评分，将趋势信号转化为可排序的候选优先级。")
    if strategy_evidence:
        top = strategy_evidence[0]
        actions.append(f"优先复核 {top['ticker']} 的评分证据和限制项，再决定是否进入人工研究。")
    if macro_state == "defense":
        actions.append("保持防守约束，所有候选只进入观察或减仓复核，不自动升级为买入。")
    else:
        actions.append("把高关注标的与高评分标的交叉，形成下一轮人工研究清单。")
    return actions


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
