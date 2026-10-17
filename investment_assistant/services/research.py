from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import date
from typing import Any, Callable

from investment_assistant import db
from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.db import connect
from investment_assistant.research.event_sources import (
    EVENT_DEFINITIONS,
    UNAVAILABLE_KINDS,
    EventSourceError,
    collect_events,
    require_available_kind,
)
from investment_assistant.research.event_study import (
    SEMANTICS_VERSION, regime_fn_for_config, resolve_asof, run_event_study,
)

KNOWN_KINDS = list(EVENT_DEFINITIONS)


def _has_db() -> bool:
    return bool(os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL"))


def _with_conn(fn: Callable[[Any], Any]) -> Any:
    with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
        return fn(conn)


def available_kinds() -> dict[str, Any]:
    return {"kinds": KNOWN_KINDS, "unavailable": dict(UNAVAILABLE_KINDS),
            "definitions": EVENT_DEFINITIONS}


def _params_hash(
    kind: str, since: date | None, asof: date | None, horizons: tuple[int, ...],
    *, config: AssistantConfig | None = None,
) -> str:
    cfg = config if config is not None else load_config()
    raw = json.dumps({
        "semantics_version": SEMANTICS_VERSION,
        "kind": kind, "since": since.isoformat() if since else None,
        "asof": asof.isoformat() if asof else None, "horizons": list(horizons),
        "definition": EVENT_DEFINITIONS.get(kind),
        "market_regime": asdict(cfg.market),
        "benchmark": "SPY", "min_sample": 30,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _compute(
    kind: str, *, since: date | None, asof: date | None, horizons: tuple[int, ...],
    config: AssistantConfig | None = None,
) -> dict[str, Any]:
    cfg = config if config is not None else load_config()
    cutoff = resolve_asof(asof)
    events = collect_events(kind, since=since, asof=cutoff, config=cfg)
    result = run_event_study(events, horizons=horizons, asof=cutoff,
                             regime_fn=regime_fn_for_config(cfg.market)).to_dict()
    result["kind"] = kind  # An empty supported sample is not an unknown event definition.
    result.setdefault("params", {})["event_definition"] = dict(EVENT_DEFINITIONS[kind])
    result["params"]["market_regime"] = asdict(cfg.market)
    return result


def event_study_view(
    kind: str,
    *,
    since: date | None = None,
    asof: date | None = None,
) -> dict[str, Any]:
    # Validate before reading legacy cache rows; unsupported is never an n=0 success.
    require_available_kind(kind)
    config = load_config()
    horizons = tuple(config.backtest.horizons)
    cutoff = resolve_asof(asof)
    params_hash = _params_hash(kind, since, cutoff, horizons, config=config)

    has_db = _has_db()
    cache_error = None
    if has_db:
        try:
            cached = _with_conn(lambda conn: db.get_event_study(conn, kind=kind, params_hash=params_hash))
        except Exception:
            # Cache availability and source availability are independent. A
            # transient cache failure may still yield a useful computed result.
            cached = None
            cache_error = "cache_read_failed"
        if cached:
            quality = cached["result"].get("params", {}).get("source_quality", {})
            return {"result": cached["result"], "degraded": quality.get("status") in ("excluded", "partial"),
                    "source": "cache"}

    try:
        result = _compute(kind, since=since, asof=cutoff, horizons=horizons, config=config)
    except EventSourceError as exc:
        # No result / no upsert: retry on the next request instead of persisting
        # an outage as a successful n=0 study. Do not expose the underlying SQL.
        return {"result": None, "degraded": True, "source": "unavailable",
                "error": exc.to_dict(), "source_quality": exc.source_quality}

    quality = result.get("params", {}).get("source_quality", {})
    quality_degraded = quality.get("status") in ("excluded", "partial")
    if has_db and not cache_error and not quality_degraded:
        try:
            _with_conn(lambda conn: db.upsert_event_study(conn, kind=kind, params_hash=params_hash, result=result))
        except Exception:
            cache_error = "cache_write_failed"
    return {"result": result, "degraded": not has_db or quality_degraded or bool(cache_error), "source": "computed",
            **({"cache_error": cache_error} if cache_error else {})}
