from __future__ import annotations

import math
import os
from collections import Counter
from datetime import date, datetime
from typing import Any, Callable, Iterator

from investment_assistant.data.calendar import add_trading_days, is_trading_day
from investment_assistant.data.provenance import SCORE_CALCULATION_VERSION, SIGNAL_CALCULATION_VERSION
from investment_assistant.research.event_study import Event

RowSource = Callable[[], list[dict[str, Any]]]
SCORE_STRATEGY = "trend_relative_strength"

# Source contracts, not backtest-selected parameter values. Keep old identifiers
# explicit so callers never mistake an unimplemented/suspended event for n=0.
EVENT_DEFINITIONS = {
    "ma_reclaim": {"indicator": "SMA", "period": 20,
                   "definition": "close_cross_above_sma20", "not_equivalent_to": "21EMA"},
    "score_high": {"definition": "strategy_score_gte", "threshold": 70, "strategy": SCORE_STRATEGY},
}
UNAVAILABLE_KINDS = {
    "rs_strong": (
        "relative_strength_spy is a 20-session return difference in decimal units; "
        "legacy rs_strong=1.2 has unconfirmed units/intent (1.2 decimal = 120 percentage points). "
        "Definition suspended pending confirmation; no conversion or optimized threshold is assumed"
    ),
    "eps_beat": "point-in-time EPS actual/consensus source is not implemented",
    "eps_miss": "point-in-time EPS actual/consensus source is not implemented",
    "vcp": "VCP event definition/source is not implemented",
    "vcp_breakout": "VCP event definition/source is not implemented",
}


class EventSourceError(RuntimeError):
    """A failed read is not an empty sample. Never carry DB/SQL exception text."""

    def __init__(self, source: str, code: str):
        self.source = source
        self.code = code
        super().__init__(f"event source {source} unavailable ({code})")

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "code": self.code, "message": str(self)}

    @property
    def source_quality(self) -> dict[str, Any]:
        return {"source": self.source, "status": "unavailable", "rows_read": None, "error_code": self.code}


class EventCollection(list[Event]):
    """List-compatible events with source evidence, including zero-event batches.

    Exclusion counts are row counts with one primary reason per row. They are
    separate from the engine's event/horizon outcome skips. An unversioned source
    is never upgraded to trusted just because its numeric values look plausible.
    """

    def __init__(self, source: str, rows_read: int):
        super().__init__()
        self.source = source
        self.rows_read = rows_read
        self.rows_in_window = 0
        self.rows_eligible = 0
        self.out_of_window = 0
        self.excluded: Counter[str] = Counter()

    @property
    def source_quality(self) -> dict[str, Any]:
        excluded_count = sum(self.excluded.values())
        if excluded_count:
            status = "partial" if self.rows_eligible else "excluded"
        else:
            status = "ok" if self.rows_eligible else "empty"
        return {
            "source": self.source, "status": status, "rows_read": self.rows_read,
            "rows_in_window": self.rows_in_window, "out_of_window": self.out_of_window,
            "rows_eligible": self.rows_eligible, "events_emitted": len(self),
            "excluded_count": excluded_count, "excluded_by_reason": dict(self.excluded),
            "signal_calculation_version": SIGNAL_CALCULATION_VERSION,
            **({"score_calculation_version": SCORE_CALCULATION_VERSION, "strategy": SCORE_STRATEGY}
               if self.source == "strategy_scores" else {}),
        }


def require_available_kind(kind: str) -> None:
    if kind not in EVENT_DEFINITIONS:
        reason = UNAVAILABLE_KINDS.get(kind, "unknown event definition")
        raise ValueError(f"{kind} unavailable: {reason}")


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


def _ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or "").strip().upper()


def _window_rows(
    rows: list[dict[str, Any]], date_key: str, result: EventCollection,
    *, asof: date | None, since: date | None,
) -> Iterator[tuple[dict[str, Any], date, str]]:
    for row in rows:
        d = _as_date(row.get(date_key))
        if d is not None and not _in_window(d, asof=asof, since=since):
            result.out_of_window += 1
            continue
        result.rows_in_window += 1
        if d is None:
            result.excluded[f"{date_key}_missing"] += 1
        elif not _ticker(row):
            result.excluded["ticker_missing"] += 1
        else:
            yield row, d, _ticker(row)


def _snapshot_rejection(row: dict[str, Any], expected: date | None, *, prefix: str = "") -> str | None:
    signal_date = _as_date(row.get(f"{prefix}signal_date"))
    price_date = _as_date(row.get(f"{prefix}price_date"))
    if signal_date is None:
        return f"{prefix}signal_date_missing"
    if signal_date != expected:
        return f"{prefix}signal_date_mismatch"
    if not is_trading_day(signal_date):
        return f"non_trading_{prefix}signal_date"
    if price_date is None:
        return f"{prefix}price_date_missing"
    if price_date != signal_date:
        return f"{prefix}price_date_mismatch"
    if row.get(f"{prefix}calculation_version") != SIGNAL_CALCULATION_VERSION:
        return f"{prefix}calculation_version_mismatch"
    if row.get(f"{prefix}error") is not None:
        return "snapshot_error" if prefix == "snapshot_" else f"{prefix}snapshot_error"
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def events_from_snapshots(
    rows: list[dict[str, Any]],
    *,
    asof: date | None = None,
    since: date | None = None,
    rs_strong: float | None = None,
) -> EventCollection:
    """SMA20 cross between trusted, adjacent NYSE sessions; RS stays suspended."""
    if rs_strong is not None:
        require_available_kind("rs_strong")
    events = EventCollection("ticker_signal_snapshots", len(rows))
    keys = Counter((_ticker(row), _as_date(row.get("signal_date"))) for row in rows)
    for row, d, ticker in _window_rows(rows, "signal_date", events, asof=asof, since=since):
        previous = _as_date(row.get("prev_signal_date"))
        reason = _snapshot_rejection(row, d) or _snapshot_rejection(row, previous, prefix="prev_")
        if not reason and previous != add_trading_days(d, -1):
            reason = "non_adjacent_sessions"
        if not reason and keys[(ticker, d)] > 1:
            reason = "duplicate_snapshot_key"
        values = [_number(row.get(k)) for k in ("close", "ma20", "prev_close", "prev_ma20")]
        if not reason and any(v is None or v <= 0 for v in values):
            reason = "invalid_indicator"
        if reason:
            events.excluded[reason] += 1
            continue
        events.rows_eligible += 1
        close, ma20, prev_close, prev_ma20 = values
        if prev_close <= prev_ma20 and close > ma20:
            events.append(Event(ticker, d, "ma_reclaim", dict(EVENT_DEFINITIONS["ma_reclaim"])))
    return events


def events_from_scores(
    rows: list[dict[str, Any]],
    *,
    asof: date | None = None,
    since: date | None = None,
    score_high: int = 70,
) -> EventCollection:
    events = EventCollection("strategy_scores", len(rows))
    keys = Counter((_ticker(row), _as_date(row.get("score_date")))
                   for row in rows if row.get("strategy") == SCORE_STRATEGY)
    for row, d, ticker in _window_rows(rows, "score_date", events, asof=asof, since=since):
        reason = None
        if row.get("strategy") != SCORE_STRATEGY:
            reason = "strategy_mismatch"
        elif row.get("calculation_version") != SCORE_CALCULATION_VERSION:
            reason = "score_calculation_version_mismatch"
        elif keys[(ticker, d)] > 1:
            reason = "duplicate_score_key"
        else:
            reason = _snapshot_rejection(row, d, prefix="snapshot_")
        score = _number(row.get("score"))
        if not reason and score is None:
            reason = "invalid_score"
        if reason:
            events.excluded[reason] += 1
            continue
        events.rows_eligible += 1
        if score >= score_high:
            events.append(Event(ticker, d, "score_high", {"score": score, "strategy": SCORE_STRATEGY}))
    return events


def _default_snapshot_source() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        raise EventSourceError("ticker_signal_snapshots", "database_unconfigured")
    try:
        from investment_assistant.db import connect
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                # Do not filter failed/legacy rows before lag: that could bridge
                # an unavailable session and manufacture a cross.
                cur.execute(
                    """
                    SELECT ticker, signal_date, price_date, calculation_version, error, close, ma20,
                           lag(signal_date) OVER w AS prev_signal_date,
                           lag(price_date) OVER w AS prev_price_date,
                           lag(calculation_version) OVER w AS prev_calculation_version,
                           lag(error) OVER w AS prev_error,
                           lag(close) OVER w AS prev_close,
                           lag(ma20) OVER w AS prev_ma20
                    FROM ticker_signal_snapshots
                    WINDOW w AS (PARTITION BY ticker ORDER BY signal_date)
                    ORDER BY signal_date
                    """
                )
                rows = cur.fetchall()
        keys = ["ticker", "signal_date", "price_date", "calculation_version", "error", "close", "ma20",
                "prev_signal_date", "prev_price_date", "prev_calculation_version", "prev_error",
                "prev_close", "prev_ma20"]
        return [dict(zip(keys, row, strict=True)) for row in rows]
    except Exception:
        raise EventSourceError("ticker_signal_snapshots", "source_read_failed") from None


def _default_score_source() -> list[dict[str, Any]]:
    database_url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not database_url:
        raise EventSourceError("strategy_scores", "database_unconfigured")
    try:
        from investment_assistant.db import connect
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                # LEFT JOIN retains missing/legacy evidence for quality counts.
                cur.execute(
                    """
                    SELECT s.ticker, s.score_date, s.strategy, s.score, s.calculation_version,
                           snap.signal_date AS snapshot_signal_date, snap.price_date AS snapshot_price_date,
                           snap.calculation_version AS snapshot_calculation_version, snap.error AS snapshot_error
                    FROM strategy_scores s
                    LEFT JOIN ticker_signal_snapshots snap
                      ON snap.ticker = s.ticker AND snap.signal_date = s.score_date
                    WHERE s.strategy = %s
                    ORDER BY s.score_date
                    """, (SCORE_STRATEGY,),
                )
                rows = cur.fetchall()
        keys = ["ticker", "score_date", "strategy", "score", "calculation_version", "snapshot_signal_date",
                "snapshot_price_date", "snapshot_calculation_version", "snapshot_error"]
        return [dict(zip(keys, row, strict=True)) for row in rows]
    except Exception:
        raise EventSourceError("strategy_scores", "source_read_failed") from None


def collect_events(
    kind: str,
    *,
    asof: date | None = None,
    since: date | None = None,
    config: Any = None,
    snapshot_source: RowSource | None = None,
    score_source: RowSource | None = None,
) -> EventCollection:
    require_available_kind(kind)
    # `config` stays compatible; the unapproved legacy RS threshold is not used.
    source = "ticker_signal_snapshots" if kind == "ma_reclaim" else "strategy_scores"
    reader = (snapshot_source or _default_snapshot_source) if kind == "ma_reclaim" else (score_source or _default_score_source)
    try:
        rows = reader()
    except EventSourceError:
        raise
    except Exception:
        raise EventSourceError(source, "source_read_failed") from None
    if kind == "ma_reclaim":
        return events_from_snapshots(rows, asof=asof, since=since)
    return events_from_scores(rows, asof=asof, since=since,
                              score_high=EVENT_DEFINITIONS["score_high"]["threshold"])
