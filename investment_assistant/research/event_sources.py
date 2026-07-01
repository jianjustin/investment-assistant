from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Callable

from investment_assistant.research.event_study import Event

RowSource = Callable[[], list[dict[str, Any]]]


def _in_window(d: date, *, asof: date | None, since: date | None) -> bool:
    if asof is not None and d > asof:
        return False
    if since is not None and d < since:
        return False
    return True


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def events_from_snapshots(
    rows: list[dict[str, Any]],
    *,
    asof: date | None = None,
    since: date | None = None,
    rs_strong: float = 1.2,
) -> list[Event]:
    events: list[Event] = []
    for row in rows:
        d = _as_date(row.get("signal_date"))
        if d is None or not _in_window(d, asof=asof, since=since):
            continue
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        reasons = row.get("trigger_reason") or []
        rs = row.get("relative_strength_spy")
        if rs is not None and float(rs) >= rs_strong and "outperform_spy" in reasons:
            events.append(Event(ticker, d, "rs_strong", {"rs_spy": float(rs)}))
        close, ma20 = row.get("close"), row.get("ma20")
        prev_close, prev_ma20 = row.get("prev_close"), row.get("prev_ma20")
        if None not in (close, ma20, prev_close, prev_ma20):
            crossed_up = float(prev_close) <= float(prev_ma20) and float(close) > float(ma20)
            if crossed_up:
                events.append(Event(ticker, d, "ma_reclaim", {"approx": "ma20_for_21ema"}))
    return events


def events_from_scores(
    rows: list[dict[str, Any]],
    *,
    asof: date | None = None,
    since: date | None = None,
    score_high: int = 70,
) -> list[Event]:
    events: list[Event] = []
    for row in rows:
        d = _as_date(row.get("score_date"))
        if d is None or not _in_window(d, asof=asof, since=since):
            continue
        ticker = str(row.get("ticker", "")).upper()
        score = row.get("score")
        if ticker and score is not None and int(score) >= score_high:
            events.append(Event(ticker, d, "score_high", {"score": int(score)}))
    return events


def _default_snapshot_source() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    from investment_assistant.db import connect
    try:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ticker, signal_date, close, ma20,
                           relative_strength_spy, trigger_reason,
                           lag(close) OVER w AS prev_close,
                           lag(ma20) OVER w AS prev_ma20
                    FROM ticker_signal_snapshots
                    WHERE error IS NULL
                    WINDOW w AS (PARTITION BY ticker ORDER BY signal_date)
                    ORDER BY signal_date
                    """
                )
                rows = cur.fetchall()
    except Exception:
        return []
    keys = ["ticker", "signal_date", "close", "ma20", "relative_strength_spy",
            "trigger_reason", "prev_close", "prev_ma20"]
    return [dict(zip(keys, row)) for row in rows]


def _default_score_source() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        return []
    from investment_assistant.db import connect
    try:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ticker, score_date, score FROM strategy_scores ORDER BY score_date")
                rows = cur.fetchall()
    except Exception:
        return []
    return [dict(zip(["ticker", "score_date", "score"], row)) for row in rows]


def collect_events(
    kind: str,
    *,
    asof: date | None = None,
    since: date | None = None,
    config: Any = None,
    snapshot_source: RowSource | None = None,
    score_source: RowSource | None = None,
) -> list[Event]:
    rs_strong = 1.2
    score_high = 70
    if config is not None:
        rs_strong = float(getattr(config.strategy, "rs_strong", rs_strong))
    snap_src = snapshot_source or _default_snapshot_source
    score_src = score_source or _default_score_source

    events: list[Event] = []
    if kind in ("rs_strong", "ma_reclaim"):
        events += events_from_snapshots(snap_src(), asof=asof, since=since, rs_strong=rs_strong)
    if kind == "score_high":
        events += events_from_scores(score_src(), asof=asof, since=since, score_high=score_high)
    return [e for e in events if e.kind == kind]
