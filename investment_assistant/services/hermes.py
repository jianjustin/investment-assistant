from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from investment_assistant.api.http import first, parse_csv, parse_int, parse_payload_bool, parse_payload_watchlist
from investment_assistant.config import load_config
from investment_assistant.hermes.decision_evidence import build_decision_evidence
from investment_assistant.hermes.macro_analyst import analyze_macro_environment
from investment_assistant.hermes.run_log import append_run


def hermes_macro_analysis(query: dict[str, list[str]]) -> dict[str, Any]:
    from investment_assistant.services.market import market_signal_rows
    from investment_assistant.services.watchlist import current_watchlist
    window = parse_int(first(query, "window"), default=30, minimum=5, maximum=90)
    rows = market_signal_rows({"limit": [str(window)]})
    watchlist = parse_csv(first(query, "watchlist"))
    if not watchlist:
        watchlist = current_watchlist()
    return analyze_macro_environment(rows, window=window, watchlist=watchlist)


def run_hermes_macro_llm_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    from investment_assistant.services.market import market_signal_rows
    from investment_assistant.services.watchlist import current_watchlist
    config = load_config()
    window = parse_int(str(payload.get("window")) if payload.get("window") is not None else None, default=30, minimum=5, maximum=90)
    model = str(payload.get("model") or config.model_default or "deepseek-v4-pro")
    watchlist = parse_payload_watchlist(payload.get("watchlist")) or current_watchlist()
    rows = market_signal_rows({"limit": [str(window)]})
    run_id = f"macro-llm-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    analysis = analyze_macro_environment(rows, window=window, watchlist=watchlist, use_llm=True, model=model)
    record = {
        "type": "hermes_macro_llm_analysis",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "window": window,
        "model": model,
        "watchlist": watchlist,
        "macro_state": analysis.get("macro_state"),
        "stance_label": analysis.get("stance_label"),
        "llm": analysis.get("llm"),
        "summary": analysis.get("summary"),
    }
    append_run(record)
    return {"run_id": run_id, "analysis": analysis}


def run_decision_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    from investment_assistant.services.market import market_signal_rows
    from investment_assistant.services.tickers import ticker_trend_rows
    from investment_assistant.services.strategies import strategy_score_rows
    config = load_config()
    window = parse_int(str(payload.get("window")) if payload.get("window") is not None else None, default=30, minimum=5, maximum=90)
    model = str(payload.get("model") or config.model_default or "deepseek-v4-pro")
    use_llm = parse_payload_bool(payload.get("use_llm"), default=True)
    run_id = f"decision-evidence-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    macro = hermes_macro_analysis({"window": [str(window)]})
    ticker_signals = ticker_trend_rows()
    scores = strategy_score_rows()
    evidence = build_decision_evidence(
        macro=macro,
        ticker_signals=ticker_signals,
        strategy_scores=scores,
        use_llm=use_llm,
        model=model,
    )
    record = {
        "type": "hermes_decision_evidence",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "window": window,
        "model": model,
        "use_llm": use_llm,
        "macro_state": evidence.get("market_context", {}).get("macro_state"),
        "ticker_count": len(evidence.get("ticker_focus") or []),
        "strategy_score_count": len(evidence.get("strategy_evidence") or []),
        "llm": evidence.get("llm"),
        "summary": evidence.get("summary"),
    }
    append_run(record)
    return {"run_id": run_id, "decision_evidence": evidence}
