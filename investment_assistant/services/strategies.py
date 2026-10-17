from __future__ import annotations

import json
import math
import os
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from investment_assistant.data.calendar import is_trading_day
from investment_assistant.data.provenance import SCORE_CALCULATION_VERSION, SIGNAL_CALCULATION_VERSION
from investment_assistant.db import connect
from investment_assistant.strategies.trend_relative_strength import score_trend_relative_strength
from investment_assistant.tickers.trend import validate_signal_date


def strategy_score_rows() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    try:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ticker, score_date, strategy, score, evidence, limits,
                           source_snapshot_id, run_id, created_at, updated_at, calculation_version
                    FROM strategy_scores
                    ORDER BY score_date DESC, score DESC, ticker ASC
                    LIMIT 100
                    """
                )
                rows = cur.fetchall()
    except Exception:
        return []
    keys = [
        "ticker", "score_date", "strategy", "score", "evidence", "limits",
        "source_snapshot_id", "run_id", "created_at", "updated_at", "calculation_version",
    ]
    return [dict(zip(keys, row)) for row in rows]


def strategy_input_snapshots(signal_date: date | None = None) -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    # Keep failed/legacy snapshots: do not silently fall back to an older success.
    where = "WHERE TRUE"
    params: dict[str, Any] = {}
    if signal_date is not None:
        where += " AND signal_date = %(signal_date)s"
        params["signal_date"] = signal_date
    # A DB/schema failure is not an empty successful query.
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (ticker)
                       id, ticker, signal_date, trend_state, attention_level,
                       trigger_reason, relative_strength_spy, relative_strength_qqq,
                       volume_ratio, run_id, created_at, updated_at, error,
                       price_date, calculation_version
                FROM ticker_signal_snapshots
                {where}
                ORDER BY ticker ASC, signal_date DESC, updated_at DESC
                """,
                params,
            )
            rows = cur.fetchall()
    keys = [
        "id", "ticker", "signal_date", "trend_state", "attention_level",
        "trigger_reason", "relative_strength_spy", "relative_strength_qqq",
        "volume_ratio", "run_id", "created_at", "updated_at", "error",
        "price_date", "calculation_version",
    ]
    return [dict(zip(keys, row)) for row in rows]


def latest_strategy_market_context() -> dict[str, Any]:
    from investment_assistant.services.hermes import hermes_macro_analysis
    analysis = hermes_macro_analysis({"window": ["30"]})
    return {
        "macro_state": analysis.get("macro_state"),
        "judgement": analysis.get("judgement"),
        "stance_label": analysis.get("stance_label"),
    }


def _input_date(value: Any) -> date:
    # Unknown/malformed dates are not permission to substitute today's date.
    if isinstance(value, datetime):
        raise ValueError("Expected a session date, not an undelimited timestamp")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Missing or invalid input signal_date: {value!r}") from exc


def _validate_market_row(row: dict[str, Any], day: date) -> None:
    validate_signal_date(day)
    if row.get("market_status") not in {"green", "yellow", "red"}:
        raise ValueError(f"Invalid market status for {day}")
    if not isinstance(row.get("spy_above_200ma"), bool):
        raise ValueError(f"Missing SPY trend input for {day}")
    for key in ("spy_close", "spy_ma200", "vix_close"):
        value = row.get(key)
        if value is None or not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"Missing or invalid {key} for {day}")
    details = row.get("details") or {}
    if not isinstance(details, dict):
        raise ValueError(f"Invalid macro bar metadata for {day}")
    for key in ("spy_latest_index", "vix_latest_index"):
        try:
            bar_date = datetime.fromisoformat(str(details.get(key))).date()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unknown macro bar date: {key} for {day}") from exc
        if bar_date != day:
            raise ValueError(f"Macro bar date mismatch: {key}={bar_date}, signal_date={day}")


def historical_strategy_market_context(signal_date: date) -> dict[str, Any]:
    """Dated reconstruction, not archived point-in-time data vintages.

    The target session must be valid. Unverifiable earlier rows are quarantined
    in memory only, with reasons and actual 30-session coverage disclosed. Never
    repair/relabel persisted rows or substitute earlier inputs for the target.
    """
    from investment_assistant.hermes.macro_analyst import analyze_macro_environment
    from investment_assistant.services.market import market_signal_rows

    validate_signal_date(signal_date)
    expected: set[date] = set()
    day = signal_date
    while len(expected) < 30:
        if is_trading_day(day):
            expected.add(day)
        day -= timedelta(days=1)
    rows = market_signal_rows({"to": [signal_date.isoformat()], "limit": ["30"]})
    dated: list[tuple[date, dict[str, Any]]] = []
    excluded: list[dict[str, Any]] = []
    parsed: list[tuple[date, dict[str, Any]]] = []
    for row in rows:
        try:
            day = _input_date(row.get("signal_date"))
        except ValueError as exc:
            excluded.append({"signal_date": str(row.get("signal_date")), "reason": str(exc)})
            continue
        if day > signal_date:
            raise ValueError(f"Future macro input {day} after {signal_date}")
        parsed.append((day, row))
    counts = Counter(day for day, _ in parsed)
    for day, row in parsed:
        try:
            if counts[day] != 1:
                raise ValueError(f"Duplicate macro session date: {day}")
            _validate_market_row(row, day)
            if day not in expected:
                raise ValueError("Outside the requested 30-session window")
        except (TypeError, ValueError) as exc:
            if day == signal_date:
                raise ValueError(f"Invalid target market context for {signal_date}: {exc}") from exc
            excluded.append({"signal_date": day.isoformat(), "reason": str(exc)})
            continue
        dated.append((day, row))
    dated.sort(key=lambda item: item[0], reverse=True)
    if not dated or dated[0][0] != signal_date:
        raise ValueError(f"Missing historical market context for {signal_date}")
    missing = sorted(expected - {day for day, _ in dated})
    analysis = analyze_macro_environment([row for _, row in dated], window=30, use_llm=False)
    return {
        "signal_date": signal_date,
        "macro_state": analysis["macro_state"],
        "judgement": analysis["judgement"],
        "stance_label": analysis["stance_label"],
        "sample_size": len(dated),
        "excluded_rows": excluded,
        "coverage": {
            "required_sessions": 30,
            "valid_sessions": len(dated),
            "coverage_ratio": len(dated) / 30,
            "complete_30_sessions": not missing,
            "missing_dates": [day.isoformat() for day in missing],
            "examined_rows": len(rows),
            "excluded_count": len(excluded),
        },
    }


def run_strategy_score_scan(payload: dict[str, Any]) -> dict[str, Any]:
    raw_date = payload.get("date")
    target_date = date.fromisoformat(str(raw_date)) if raw_date else None
    snapshots = strategy_input_snapshots(signal_date=target_date)
    now = datetime.now(UTC)
    run_id = f"manual-strategy-scores-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    contexts: dict[date, dict[str, Any]] = {}
    actual_dates: set[date] = set()
    if not snapshots:
        failures.append({"date": str(target_date) if target_date else None,
                         "stage": "strategy_input", "error": "No ticker snapshots available"})
    for snapshot in snapshots:
        try:
            score_date = _input_date(snapshot.get("signal_date"))
            actual_dates.add(score_date)
            validate_signal_date(score_date, now)
            if target_date is not None and score_date != target_date:
                raise ValueError(f"Snapshot date {score_date} does not match requested {target_date}")
            if snapshot.get("error"):
                raise ValueError(f"Ticker snapshot failed: {snapshot['error']}")
            if snapshot.get("calculation_version") != SIGNAL_CALCULATION_VERSION:
                raise ValueError("Unverifiable snapshot provenance: missing or unsupported calculation_version")
            if snapshot.get("price_date") is None or _input_date(snapshot["price_date"]) != score_date:
                raise ValueError("Unverifiable snapshot provenance: price_date must match signal_date")
            if type(snapshot.get("id")) is not int or snapshot["id"] <= 0:
                raise ValueError("Snapshot provenance requires a valid source_snapshot_id")
            if (not snapshot.get("ticker")
                    or snapshot.get("trend_state") not in {"uptrend", "downtrend", "volatile", "base"}
                    or not isinstance(snapshot.get("trigger_reason"), list)):
                raise ValueError("Missing or invalid ticker snapshot inputs")
            if score_date not in contexts:
                contexts[score_date] = historical_strategy_market_context(score_date)
            market = contexts[score_date]
            if _input_date(market.get("signal_date")) != score_date:
                raise ValueError("Macro context date does not match snapshot date")
            if market.get("macro_state") not in {"offense", "defense", "cautious"}:
                raise ValueError("Missing or invalid macro state")
            score = score_trend_relative_strength(snapshot, market)
            score["limits"].append(
                f"macro as-of {score_date}; dated reconstruction, not archived point-in-time vintages"
            )
            coverage = market.get("coverage") or {}
            score["limits"].append(
                f"macro coverage {coverage.get('valid_sessions', 0)}/30 sessions; "
                + ("complete" if coverage.get("complete_30_sessions") else "incomplete 30-session coverage")
            )
            if market.get("excluded_rows"):
                score["limits"].append("excluded macro inputs: " + json.dumps(market["excluded_rows"], ensure_ascii=False))
            score.update({
                "score_date": score_date.isoformat(),
                "source_snapshot_id": snapshot["id"],
                "calculation_version": SCORE_CALCULATION_VERSION,
                "run_id": run_id,
            })
            rows.append(score)
        except Exception as exc:
            failures.append({"ticker": snapshot.get("ticker"),
                             "date": str(snapshot.get("signal_date") or target_date or ""),
                             "stage": "strategy_score", "error": str(exc)})
    persistence = _persist_strategy_scores(rows)
    return {
        "run_id": run_id,
        "mode": str(payload.get("mode") or "manual"),
        "rows": rows,
        # Legacy count remains the computation count, never the insert count.
        "count": len(rows),
        "computed_count": len(rows),
        "selected_count": len(snapshots),
        "actual_dates": [day.isoformat() for day in sorted(actual_dates)],
        "scored_dates": sorted({row["score_date"] for row in rows}),
        "market_contexts": {day.isoformat(): context for day, context in contexts.items()},
        "failures": failures,
        **persistence,
    }


def _persist_strategy_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"inserted_count": 0, "skipped_count": 0, "skipped": []}
    if not rows:
        return result
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            for row in rows:
                payload = dict(row)
                if (payload.get("calculation_version") != SCORE_CALCULATION_VERSION
                        or type(payload.get("source_snapshot_id")) is not int
                        or payload["source_snapshot_id"] <= 0):
                    raise ValueError("Score provenance requires the current version and valid source_snapshot_id")
                payload["evidence"] = json.dumps(payload.get("evidence") or [], ensure_ascii=False)
                payload["limits"] = json.dumps(payload.get("limits") or [], ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO strategy_scores (
                      ticker, score_date, strategy, score, evidence, limits,
                      source_snapshot_id, run_id, calculation_version
                    ) VALUES (
                      %(ticker)s, %(score_date)s, %(strategy)s, %(score)s,
                      %(evidence)s::jsonb, %(limits)s::jsonb,
                      %(source_snapshot_id)s, %(run_id)s, %(calculation_version)s
                    )
                    ON CONFLICT (ticker, score_date, strategy) DO NOTHING
                    RETURNING id
                    """,
                    payload,
                )
                if cur.fetchone() is not None:
                    result["inserted_count"] += 1
                else:
                    result["skipped_count"] += 1
                    result["skipped"].append({"ticker": payload["ticker"], "date": str(payload["score_date"]),
                                              "strategy": payload["strategy"], "stage": "strategy_score",
                                              "reason": "existing_record_preserved"})
        conn.commit()
    return result
