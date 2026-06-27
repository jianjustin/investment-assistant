from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, date, datetime
from typing import Any

from investment_assistant.db import connect
from investment_assistant.strategies.trend_relative_strength import score_trend_relative_strength


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
                           source_snapshot_id, run_id, created_at, updated_at
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
        "source_snapshot_id", "run_id", "created_at", "updated_at",
    ]
    return [dict(zip(keys, row)) for row in rows]


def strategy_input_snapshots() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    try:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (ticker)
                           id, ticker, signal_date, trend_state, attention_level,
                           trigger_reason, relative_strength_spy, relative_strength_qqq,
                           volume_ratio, run_id, created_at, updated_at
                    FROM ticker_signal_snapshots
                    WHERE error IS NULL
                    ORDER BY ticker ASC, signal_date DESC, updated_at DESC
                    """
                )
                rows = cur.fetchall()
    except Exception:
        return []
    keys = [
        "id", "ticker", "signal_date", "trend_state", "attention_level",
        "trigger_reason", "relative_strength_spy", "relative_strength_qqq",
        "volume_ratio", "run_id", "created_at", "updated_at",
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


def run_strategy_score_scan(payload: dict[str, Any]) -> dict[str, Any]:
    snapshots = strategy_input_snapshots()
    market = latest_strategy_market_context()
    now = datetime.now(UTC)
    run_id = f"manual-strategy-scores-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for snapshot in snapshots:
        try:
            score = score_trend_relative_strength(snapshot, market)
            score_date = snapshot.get("signal_date") or date.today()
            if isinstance(score_date, date):
                score_date = score_date.isoformat()
            score.update({
                "score_date": str(score_date),
                "source_snapshot_id": snapshot.get("id"),
                "run_id": run_id,
            })
            rows.append(score)
        except Exception as exc:
            failures.append({"ticker": snapshot.get("ticker"), "error": str(exc)})
    _persist_strategy_scores(rows)
    return {
        "run_id": run_id,
        "mode": str(payload.get("mode") or "manual"),
        "rows": rows,
        "count": len(rows),
        "failures": failures,
    }


def _persist_strategy_scores(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    database_url = os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            for row in rows:
                payload = dict(row)
                payload["evidence"] = json.dumps(payload.get("evidence") or [], ensure_ascii=False)
                payload["limits"] = json.dumps(payload.get("limits") or [], ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO strategy_scores (
                      ticker, score_date, strategy, score, evidence, limits,
                      source_snapshot_id, run_id
                    ) VALUES (
                      %(ticker)s, %(score_date)s, %(strategy)s, %(score)s,
                      %(evidence)s::jsonb, %(limits)s::jsonb,
                      %(source_snapshot_id)s, %(run_id)s
                    )
                    ON CONFLICT (ticker, score_date, strategy) DO UPDATE SET
                      score = EXCLUDED.score,
                      evidence = EXCLUDED.evidence,
                      limits = EXCLUDED.limits,
                      source_snapshot_id = EXCLUDED.source_snapshot_id,
                      run_id = EXCLUDED.run_id,
                      updated_at = now()
                    """,
                    payload,
                )
        conn.commit()
