from __future__ import annotations

import hashlib
import os
from datetime import date
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.config import load_config
from investment_assistant.db import connect
from investment_assistant.research.event_sources import collect_events
from investment_assistant.research.event_study import run_event_study

KNOWN_KINDS = ["rs_strong", "ma_reclaim", "score_high", "eps_beat", "eps_miss"]


def _has_db() -> bool:
    return bool(os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"))


def _with_conn(fn: Callable[[Any], Any]) -> Any:
    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return fn(conn)


def available_kinds() -> dict[str, Any]:
    return {"kinds": KNOWN_KINDS}


def _params_hash(kind: str, since: date | None, asof: date | None, horizons: tuple[int, ...]) -> str:
    raw = f"{kind}|{since}|{asof}|{horizons}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _compute(kind: str, *, since: date | None, asof: date | None, horizons: tuple[int, ...]) -> dict[str, Any]:
    events = collect_events(kind, since=since, asof=asof, config=load_config())
    result = run_event_study(events, horizons=horizons)
    return result.to_dict()


def event_study_view(
    kind: str,
    *,
    since: date | None = None,
    asof: date | None = None,
) -> dict[str, Any]:
    config = load_config()
    horizons = tuple(getattr(config.backtest, "horizons", [5, 10, 20]))
    params_hash = _params_hash(kind, since, asof, horizons)

    if not _has_db():
        return {
            "result": _compute(kind, since=since, asof=asof, horizons=horizons),
            "degraded": True,
            "source": "computed",
        }

    cached = _with_conn(lambda conn: db.get_event_study(conn, kind=kind, params_hash=params_hash))
    if cached:
        return {"result": cached["result"], "degraded": False, "source": "cache"}

    result = _compute(kind, since=since, asof=asof, horizons=horizons)
    _with_conn(lambda conn: db.upsert_event_study(conn, kind=kind, params_hash=params_hash, result=result))
    return {"result": result, "degraded": False, "source": "computed"}
