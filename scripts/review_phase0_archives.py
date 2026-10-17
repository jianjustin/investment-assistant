"""Read-only Phase 0 exploration of content-addressed, existing Yahoo archives.

Run with Python -I -B. No collectors, services, business DBs or network imports.
The default output is stdout; --output creates a NEW file outside the raw root
and the repository. Historical availability is NOT inferred from file mtimes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Explicit trusted code root, never the archive directory, even under python -I.
sys.dont_write_bytecode = True
_REPO = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(_REPO))

import pandas as pd

from investment_assistant.config import DEFAULT_BACKTEST_HORIZONS
from investment_assistant.data.calendar import add_trading_days, is_trading_day
from investment_assistant.research.event_study import Event, resolve_asof, run_event_study

STOCKS = ("CRDO", "GOOG", "MSFT", "MU", "NVDA", "RKLB", "SNDK", "TSLA")
BENCHMARKS = ("SPY", "QQQ")
DEFAULT_ASOF = date(2026, 10, 15)
_HORIZONS = (5, 10, 20)
_NY = ZoneInfo("America/New_York")
_SELECTION = (
    "For each response symbol select ONE validated archive: most rows dated <= asof, "
    "then latest retained end date, then earliest retained start date, then lexicographically "
    "smallest SHA256 and relative path. Never splice versions or rank by returns, CI or mtime. "
    "This is a deterministic retrospective choice, NOT earliest-known or strict PIT."
)
_WARNINGS = [
    "Exploratory descriptive statistics only; no alpha recommendation and no CI-based retain/drop decision.",
    ("Overlapping holding periods, repeated tickers and same-day cross-stock events are correlated. "
     "The engine's mean +/- 1.96*sample_std/sqrt(n) interval assumes independent observations; "
     "it is NOT dependence-adjusted or a valid formal decision gate here."),
    "Frozen CURRENT eight-stock watchlist introduces selection and survivorship bias; not a historical universe.",
    ("Yahoo current-vintage adjusted Close includes backfilled adjustments, not strict point-in-time data. "
     "SHA256 proves local byte integrity, not vendor authenticity or historical availability."),
    ("Acquisition/first_seen time is unauthenticated. File mtimes are neither read nor used as first_seen. "
     "Response regularMarketTime is a market field, not an archive acquisition timestamp."),
    ("No trading costs, slippage, execution lag, liquidity constraints or implementable portfolio simulation. "
     "Event-close to endpoint-close returns assume a non-executable same-close entry after observing the signal."),
    "All regimes are injected as unknown; no VIX or authenticated historical market state is available.",
    ("MA events are reconstructed, not observed trustworthy historical signal snapshots. "
     "Both adjacent snapshots require 200 consecutive NYSE observations; a gap resets warmup. "
     "Forward returns require exact endpoints, not complete interior paths; interior gaps are disclosed."),
]


class ArchiveValidationError(ValueError):
    """Fixed-code errors only: never echo archive content, credentials or absolute paths."""


@dataclass(frozen=True)
class Bar:
    day: date
    timestamp: int
    raw_index: int
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int

    def fields(self) -> list[Any]:
        return [self.timestamp, self.open, self.high, self.low, self.close, self.adjusted_close, self.volume]


@dataclass(frozen=True)
class ArchiveSeries:
    symbol: str
    sha256: str
    source_path: str  # relative to --raw-root, never an absolute filesystem path
    bars: tuple[Bar, ...]
    evidence: dict[str, Any]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _positive(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ArchiveValidationError("invalid_price")
    out = float(value)
    if not math.isfinite(out) or out <= 0:
        raise ArchiveValidationError("invalid_price")
    return out


def _timestamp(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArchiveValidationError("invalid_timestamp")
    return value


def _parse_chart(result: dict[str, Any], sha: str, relative: str, *, asof: date) -> ArchiveSeries:
    """Validate raw fields before any date filtering or derived-frame construction."""
    try:
        meta = result["meta"]
        symbol = meta["symbol"]
        expected_type = "EQUITY" if symbol in STOCKS else "ETF"
        if (meta["instrumentType"] != expected_type or meta["currency"] != "USD"
                or meta["exchangeTimezoneName"] != "America/New_York" or meta["dataGranularity"] != "1d"):
            raise ArchiveValidationError("incompatible_chart_metadata")
        market_timestamp = _timestamp(meta["regularMarketTime"])
        stamps = result["timestamp"]
        indicators = result["indicators"]
        if len(indicators["quote"]) != 1 or len(indicators["adjclose"]) != 1:
            raise ArchiveValidationError("ambiguous_indicators")
        quote = indicators["quote"][0]
        adjusted = indicators["adjclose"][0]["adjclose"]
        arrays = [quote[k] for k in ("open", "high", "low", "close", "volume")] + [adjusted]
        if (not isinstance(stamps, list) or not stamps
                or any(not isinstance(a, list) or len(a) != len(stamps) for a in arrays)):
            raise ArchiveValidationError("unequal_or_empty_arrays")
        all_bars: list[Bar] = []
        for i, value in enumerate(stamps):
            stamp = _timestamp(value)
            day = datetime.fromtimestamp(stamp, UTC).astimezone(_NY).date()
            if stamp > market_timestamp or not is_trading_day(day):
                raise ArchiveValidationError("invalid_session_timestamp")
            if all_bars and (stamp <= all_bars[-1].timestamp or day <= all_bars[-1].day):
                raise ArchiveValidationError("duplicate_or_unordered_session")
            op, high, low, close = (_positive(quote[k][i]) for k in ("open", "high", "low", "close"))
            adj = _positive(adjusted[i])
            volume = quote["volume"][i]
            if isinstance(volume, bool) or not isinstance(volume, int) or volume < 0:
                raise ArchiveValidationError("invalid_volume")
            if low > min(op, close) or high < max(op, close) or low > high:
                raise ArchiveValidationError("invalid_ohlc")
            all_bars.append(Bar(day, stamp, i, op, high, low, close, adj, volume))
    except ArchiveValidationError:
        raise
    except (KeyError, TypeError, IndexError, ValueError, OverflowError, OSError) as exc:
        raise ArchiveValidationError("invalid_chart_schema") from exc
    retained = tuple(b for b in all_bars if b.day <= asof)
    gaps = [
        {"previous": a.day.isoformat(), "next": b.day.isoformat()}
        for a, b in pairwise(retained) if add_trading_days(a.day, 1) != b.day
    ]
    evidence = {
        "response_symbol": symbol, "instrument_type": expected_type,
        "currency": "USD", "exchange_timezone": "America/New_York", "data_granularity": "1d",
        "regular_market_time_utc": datetime.fromtimestamp(market_timestamp, UTC).isoformat(),
        "acquisition_time_verified": False, "first_seen": None,
        "raw_rows": len(all_bars), "raw_from": all_bars[0].day.isoformat(),
        "raw_through": all_bars[-1].day.isoformat(), "retained_rows": len(retained),
        "from": retained[0].day.isoformat() if retained else None,
        "through": retained[-1].day.isoformat() if retained else None,
        "future_rows_excluded": len(all_bars) - len(retained),
        "session_gaps": gaps,
        "validated_fields": ["timestamp", "quote.open", "quote.high", "quote.low", "quote.close",
                             "adjclose.adjclose", "quote.volume"],
        "fields_hash_encoding": "sha256(JSON compact rows: [timestamp,open,high,low,close,adjusted_close,volume])",
        "raw_fields_sha256": _digest([b.fields() for b in all_bars]),
        "retained_fields_sha256": _digest([b.fields() for b in retained]),
        "price_mapping": "Close := indicators.adjclose[0].adjclose (never quote.close)",
    }
    return ArchiveSeries(symbol, sha, relative, retained, evidence)


def _source(series: ArchiveSeries) -> dict[str, Any]:
    return {"sha256": series.sha256, "source_path": series.source_path, **series.evidence}


def _version_comparison(versions: list[ArchiveSeries]) -> dict[str, Any]:
    maps = [{b.day: b for b in v.bars} for v in versions]
    common = set.intersection(*(set(m) for m in maps))
    adjusted_differences = ohlcv_differences = 0
    max_range = 0.0
    for day in common:
        bars = [m[day] for m in maps]
        adjusted = [b.adjusted_close for b in bars]
        adjusted_differences += len(set(adjusted)) > 1
        ohlcv_differences += len({(b.open, b.high, b.low, b.close, b.volume) for b in bars}) > 1
        max_range = max(max_range, (max(adjusted) - min(adjusted)) / min(adjusted))
    return {"common_dates": len(common), "adjusted_close_differing_dates": adjusted_differences,
            "ohlcv_differing_dates": ohlcv_differences, "max_adjusted_relative_range": max_range}


def read_archives(raw_root: Path, *, asof: date) -> tuple[dict[str, ArchiveSeries], dict[str, Any]]:
    """Discover original chart bodies, check content-address hashes, select single vintages.

    All .raw/.json file hashes must match their 64-hex filename, including opaque
    non-chart archives. Invalid selected-universe charts fail closed, rather than
    silently substituting a different vintage. No derived handoff JSON is trusted.
    """
    raw_root = Path(raw_root).resolve()
    if not raw_root.is_dir():
        raise ArchiveValidationError("raw_root_unavailable")
    files = sorted(p for p in raw_root.rglob("*") if p.suffix in (".raw", ".json"))
    versions: dict[str, list[ArchiveSeries]] = defaultdict(list)
    inventory: dict[str, Any] = {
        "files_hash_verified": 0, "non_chart_files": 0, "chart_files": 0,
        "chart_files_ignored_unselected_symbol": 0, "source_path_base": "raw_root",
        "version_selection": _SELECTION,
    }
    for path in files:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(raw_root):
            raise ArchiveValidationError("unsafe_archive_path")
        if not re.fullmatch(r"[0-9a-f]{64}", path.stem):
            raise ArchiveValidationError("non_content_addressed_filename")
        payload = path.read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        if sha != path.stem:
            raise ArchiveValidationError("hash_mismatch")
        inventory["files_hash_verified"] += 1
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            inventory["non_chart_files"] += 1
            continue
        if not isinstance(body, dict) or "chart" not in body:
            inventory["non_chart_files"] += 1
            continue
        inventory["chart_files"] += 1
        try:
            chart = body["chart"]
            if chart.get("error") is not None or len(chart["result"]) != 1:
                raise ArchiveValidationError("chart_error_or_ambiguous_result")
            result = chart["result"][0]
            symbol = result["meta"]["symbol"]
            if symbol not in STOCKS + BENCHMARKS:
                inventory["chart_files_ignored_unselected_symbol"] += 1
                continue
        except (KeyError, TypeError, AttributeError) as exc:
            raise ArchiveValidationError("invalid_chart_schema") from exc
        versions[symbol].append(_parse_chart(result, sha, path.relative_to(raw_root).as_posix(), asof=asof))
    selected = {}
    summaries = {}
    for symbol, choices in sorted(versions.items()):
        ranked = sorted(choices, key=lambda v: (
            -len(v.bars), -v.bars[-1].day.toordinal() if v.bars else 0,
            v.bars[0].day.toordinal() if v.bars else 0, v.sha256, v.source_path,
        ))
        if ranked[0].bars:
            selected[symbol] = ranked[0]
        summaries[symbol] = {
            "selected_sha256": ranked[0].sha256 if ranked[0].bars else None,
            "versions": [_source(v) for v in ranked], "comparison": _version_comparison(ranked),
        }
    inventory["versions_by_symbol"] = summaries
    return selected, inventory


def reconstruct_ma_reclaim(selected: dict[str, ArchiveSeries]) -> tuple[list[Event], dict[str, Any]]:
    """SMA20 close crossover on two adjacent, individually scanner-eligible sessions."""
    events: list[Event] = []
    summaries = {}
    for symbol in STOCKS:  # benchmarks and any other archived instruments are NEVER events
        if symbol not in selected:
            continue
        series = selected[symbol]
        eligible_rows = transitions = gap_resets = run_length = 0
        first_eligible = None
        values = [b.adjusted_close for b in series.bars]
        for i, bar in enumerate(series.bars):
            if i and add_trading_days(series.bars[i - 1].day, 1) != bar.day:
                run_length = 0
                gap_resets += 1
            run_length += 1
            if run_length >= 200:
                eligible_rows += 1
                first_eligible = first_eligible or bar.day.isoformat()
            # At current row 200 the previous row has only 199 observations. No event.
            if run_length < 201:
                continue
            transitions += 1
            prior = series.bars[i - 1]
            prev_sma = sum(values[i - 20:i]) / 20
            sma = sum(values[i - 19:i + 1]) / 20
            if prior.adjusted_close <= prev_sma and bar.adjusted_close > sma:
                events.append(Event(symbol, bar.day, "ma_reclaim", {
                    "source": "reconstructed_archive_not_PIT", "source_sha256": series.sha256,
                    "raw_index": bar.raw_index, "previous_raw_index": prior.raw_index,
                    "previous_date": prior.day.isoformat(), "close": bar.adjusted_close,
                    "sma20": sma, "previous_close": prior.adjusted_close, "previous_sma20": prev_sma,
                    "current_consecutive_rows": run_length,
                }))
        summaries[symbol] = {
            "scanner_eligible_rows": eligible_rows, "first_scanner_eligible_date": first_eligible,
            "eligible_adjacent_transitions": transitions, "session_gap_resets": gap_resets,
            "events_reconstructed": sum(e.ticker == symbol for e in events),
        }
    return sorted(events, key=lambda e: (e.date, e.ticker)), summaries


def local_price_fetcher(selected: dict[str, ArchiveSeries], *, asof: date):
    """Exact single-date adjusted Close only: never ffill, nearest or future fallback."""
    prices = {symbol: {b.day: b.adjusted_close for b in series.bars if b.day <= asof}
              for symbol, series in selected.items()}

    def fetch(ticker: str, end_date: date, *, days: int = 260, **_: Any) -> pd.DataFrame:
        value = prices.get(ticker, {}).get(end_date) if end_date <= asof else None
        if value is None:
            return pd.DataFrame({"Close": []}, index=pd.DatetimeIndex([]))
        return pd.DataFrame({"Close": [value]}, index=pd.DatetimeIndex([end_date]))

    return fetch


def _dependence(events: list[Event], horizon: int) -> dict[str, int]:
    """Pair counts for admitted samples; overlap is positive intersection of (t0,t1]."""
    same_day = Counter(e.date for e in events)
    overlapping = same_stock = 0
    for i, left in enumerate(events):
        end_left = add_trading_days(left.date, horizon)
        for right in events[i + 1:]:
            if max(left.date, right.date) < min(end_left, add_trading_days(right.date, horizon)):
                overlapping += 1
                same_stock += left.ticker == right.ticker
    return {"unique_event_dates": len(same_day), "unique_tickers": len({e.ticker for e in events}),
            "same_day_dates": sum(n > 1 for n in same_day.values()),
            "same_day_event_pairs": sum(n * (n - 1) // 2 for n in same_day.values()),
            "overlapping_holding_period_pairs": overlapping,
            "same_ticker_overlapping_pairs": same_stock}


def _gates() -> dict[str, Any]:
    return {
        "ma_reclaim": {"decision": "HOLD", "status": "exploratory_reconstruction_only",
                       "reason": "Need trustworthy immutable historical signals, actual regimes and "
                                 "independence-aware sample design before a formal retain/drop gate."},
        "rs_strong": {"decision": "HOLD", "status": "threshold_units_unconfirmed", "n": None,
                      "reason": "Do not invent/retune a threshold. Legacy 1.2 on a decimal excess return "
                                "would mean 120 percentage points, not 1.2% or a 1.2 ratio."},
        "score_high": {"decision": "HOLD", "status": "unavailable_event_source", "n": None,
                       "reason": "No archived VIX/authenticated historical market state or trustworthy "
                                 "immutable strategy scores. Do not manufacture score events."},
        "eps_acceleration": {"decision": "HOLD", "status": "not_implemented", "n": None,
                             "reason": "EPS event source is not implemented for this archive review."},
        "vcp_breakout": {"decision": "HOLD", "status": "not_implemented", "n": None,
                         "reason": "VCP event source is not implemented for this archive review."},
    }


def build_review(raw_root: Path, *, asof: date = DEFAULT_ASOF) -> dict[str, Any]:
    if not is_trading_day(asof) or resolve_asof(asof) != asof:
        raise ArchiveValidationError("asof_not_a_completed_nyse_session")
    if tuple(DEFAULT_BACKTEST_HORIZONS) != _HORIZONS:
        raise ArchiveValidationError("default_horizons_changed_requires_review")
    selected, inventory = read_archives(raw_root, asof=asof)
    if set(STOCKS + BENCHMARKS) - set(selected):
        raise ArchiveValidationError("missing_required_symbols")
    events, coverage = reconstruct_ma_reclaim(selected)
    fetch = local_price_fetcher(selected, asof=asof)
    result = run_event_study(
        events, horizons=_HORIZONS, benchmark="SPY", asof=asof,
        price_fetcher=fetch, regime_fn=lambda _: "unknown", add_trading_days_fn=add_trading_days,
    )
    if result.params["asof"] != asof.isoformat():
        raise ArchiveValidationError("engine_asof_mismatch")
    skipped = result.params.get("skipped", [])
    horizons = {}
    dependence = {}
    for h in _HORIZONS:
        rejected = [s for s in skipped if s.get("horizon") == h or s.get("stage") == "event"]
        identities = {(s["ticker"], s["date"]) for s in rejected}
        admitted = [e for e in events if (e.ticker, e.date.isoformat()) not in identities]
        stats = result.horizons[h].to_dict()
        if len(admitted) != stats["n"]:
            raise ArchiveValidationError("engine_skip_accounting_mismatch")
        # n=0 for a genuinely reconstructed, censored sample is not an unavailable source.
        if stats["n"] == 0:
            for key in ("mean_excess", "median", "hit_rate", "t_stat", "ci95", "std"):
                stats[key] = None
        stats.update({"skip_counts": dict(sorted(Counter(s["error"] for s in rejected).items())),
                      "skipped_events": len(identities), "events_considered": len(events)})
        horizons[str(h)] = stats
        dependence[str(h)] = _dependence(admitted, h)
    sources = {s: _source(v) for s, v in sorted(selected.items())}
    code_files = ["scripts/review_phase0_archives.py", "investment_assistant/config.py",
                  "investment_assistant/data/calendar.py", "investment_assistant/research/event_study.py"]
    return {
        "schema_version": 1, "review_version": "phase0-readonly-archives-v1",
        "asof": asof.isoformat(), "report_date_policy": "No wall-clock timestamp; stable for fixed bytes/code/asof",
        "scope": {"offline": True, "business_data_writes": False, "collection": False,
                  "network": False, "database": False, "notification": False, "deployment": False},
        "universe": {"event_stocks": list(STOCKS), "benchmark": "SPY", "non_event_benchmarks": list(BENCHMARKS),
                     "selection": "frozen_current_watchlist_not_historical_membership"},
        "source_path_base": "raw_root", "sources": sources, "inventory": inventory,
        "code_sha256": {name: hashlib.sha256((_REPO / name).read_bytes()).hexdigest() for name in code_files},
        "ma_reclaim": {
            "status": "exploratory_reconstructed_not_PIT", "definition":
                "previous adjusted Close <= previous SMA20 AND adjusted Close > SMA20; "
                "consecutive NYSE sessions; both snapshots have >=200 consecutive daily bars; not EMA21",
            "events_reconstructed": len(events), "coverage_by_symbol": coverage,
            "events": [{"ticker": e.ticker, "date": e.date.isoformat(), **e.meta} for e in events],
            "horizons": horizons,
            "return_units": "decimal arithmetic stock return minus SPY return; 0.01 = 1 percentage point",
            "ci_method": "unadjusted descriptive mean +/- 1.96 * sample_std(ddof=1) / sqrt(n)",
            "hit_rate_definition": "fraction of strictly positive stock-minus-SPY forward returns",
            "dependence": dependence, "dependence_pair_interval": "positive overlap of (event_date, endpoint_date]",
            "by_regime": {"unknown": horizons} if any(s["n"] for s in horizons.values()) else {},
            "engine_params": result.params, "engine_caveats": result.caveats,
        },
        "formal_gate": _gates(), "warnings": list(_WARNINGS),
        "decision": "HOLD_ALL_SIGNALS_NO_ALPHA_RECOMMENDATION",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=_REPO / ".local/us-research/raw")
    parser.add_argument("--asof", type=date.fromisoformat, default=DEFAULT_ASOF)
    parser.add_argument("--output", type=Path, help="Optional new JSON file outside repository/raw-root; default stdout")
    args = parser.parse_args(argv)
    try:
        if args.output is not None:
            target = args.output.resolve()
            if target.is_relative_to(args.raw_root.resolve()) or target.is_relative_to(_REPO):
                raise ArchiveValidationError("output_must_be_outside_repository_and_raw_root")
        report = build_review(args.raw_root, asof=args.asof)
        text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output is None:
            print(text, end="")
        else:
            # Exclusive creation also prevents a hardlink/symlink from overwriting an input.
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
        return 0
    except ArchiveValidationError as exc:
        print(json.dumps({"error": str(exc), "decision": "HOLD", "result_available": False}), file=sys.stderr)
    except OSError:
        print(json.dumps({"error": "archive_or_output_io_error", "decision": "HOLD", "result_available": False}),
              file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
