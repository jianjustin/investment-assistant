"""Pure synthetic Yahoo fixtures: never consult a real archive, network or DB."""
from __future__ import annotations

import builtins
import copy
import hashlib
import json
import os
import socket
import sqlite3
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from investment_assistant.data.calendar import add_trading_days
from scripts import review_phase0_archives as review

START = date(2024, 1, 2)


def sessions(n=225):
    return [add_trading_days(START, i) for i in range(n)]


def chart(symbol="NVDA", *, closes=None, dates=None, adjusted=None):
    dates = dates if dates is not None else sessions()
    closes = closes if closes is not None else [100.0] * len(dates)
    stamps = [int(datetime.combine(d, time(9, 30), ZoneInfo("America/New_York")).timestamp()) for d in dates]
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "currency": "USD", "exchangeTimezoneName": "America/New_York",
                 "instrumentType": "ETF" if symbol in ("SPY", "QQQ") else "EQUITY",
                 "dataGranularity": "1d", "regularMarketTime": stamps[-1] + 23400},
        "timestamp": stamps,
        "indicators": {"quote": [{"open": closes, "close": closes, "high": closes,
                                    "low": closes, "volume": [100] * len(closes)}],
                       "adjclose": [{"adjclose": adjusted if adjusted is not None else closes}]},
    }]}}


def archive(root, payload):
    raw = json.dumps(payload, allow_nan=True).encode()
    path = root / (hashlib.sha256(raw).hexdigest() + ".raw")
    path.write_bytes(raw)
    return path


def crossing_closes(n=225):
    return [100.0] * 200 + [110.0 + i for i in range(n - 200)]


@pytest.fixture
def universe(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for symbol in review.STOCKS + review.BENCHMARKS:
        archive(raw, chart(symbol, closes=crossing_closes() if symbol in review.STOCKS else None))
    return raw


def test_review_only_stocks_and_unknown_regime_and_all_gates_hold(universe):
    report = review.build_review(universe, asof=sessions()[-1])
    ma = report["ma_reclaim"]
    assert ma["events_reconstructed"] == 8
    assert {e["ticker"] for e in ma["events"]} == set(review.STOCKS)
    assert not {"SPY", "QQQ"}.intersection(e["ticker"] for e in ma["events"])
    assert set(ma["by_regime"]) == {"unknown"}
    assert set(ma["horizons"]) == {"5", "10", "20"}
    assert all(s["n"] == 8 for s in ma["horizons"].values())
    for horizon, stats in ma["horizons"].items():
        expected = (110.0 + int(horizon)) / 110.0 - 1
        assert stats["mean_excess"] == pytest.approx(expected)
        assert stats["ci95"] == pytest.approx([expected, expected])
        assert stats["hit_rate"] == 1.0
        assert stats["skip_counts"] == {}
    assert all(g["decision"] == "HOLD" for g in report["formal_gate"].values())
    for kind in ("rs_strong", "score_high", "eps_acceleration", "vcp_breakout"):
        assert report["formal_gate"][kind]["n"] is None
    assert ma["dependence"]["5"]["same_day_event_pairs"] == 28
    assert ma["dependence"]["5"]["same_day_dates"] == 1


def test_no_network_db_production_sources_tasks_or_services(universe, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline review attempted external I/O")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    import psycopg
    monkeypatch.setattr(psycopg, "connect", forbidden)
    real_import = builtins.__import__
    forbidden_modules = ("investment_assistant.data.price", "investment_assistant.db",
                         "investment_assistant.research.event_sources", "investment_assistant.tasks",
                         "investment_assistant.services", "investment_assistant.market.service")

    def guarded_import(name, *args, **kwargs):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_modules):
            raise AssertionError("forbidden production dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert review.build_review(universe, asof=sessions()[-1])["ma_reclaim"]["horizons"]["5"]["n"] == 8


def test_hash_mismatch_aborts_instead_of_trusting_export(tmp_path):
    path = archive(tmp_path, chart())
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(review.ArchiveValidationError, match="hash_mismatch"):
        review.read_archives(tmp_path, asof=sessions()[-1])


@pytest.mark.parametrize("mode", ["duplicate", "reverse", "zero", "negative", "nan", "inf", "null",
                                  "unequal_arrays", "wrong_type", "wrong_timezone", "intraday", "non_session"])
def test_reject_invalid_raw_fields_without_silent_repair(tmp_path, mode):
    payload = chart()
    r = payload["chart"]["result"][0]
    if mode == "duplicate":
        r["timestamp"][20] = r["timestamp"][19]
    elif mode == "reverse":
        r["timestamp"][20], r["timestamp"][19] = r["timestamp"][19], r["timestamp"][20]
    elif mode in ("zero", "negative", "nan", "inf", "null"):
        r["indicators"]["adjclose"][0]["adjclose"][10] = {
            "zero": 0, "negative": -1, "nan": float("nan"), "inf": float("inf"), "null": None,
        }[mode]
    elif mode == "unequal_arrays":
        r["timestamp"].pop()
    elif mode == "wrong_type":
        r["meta"]["instrumentType"] = "ETF"
    elif mode == "wrong_timezone":
        r["meta"]["exchangeTimezoneName"] = "Asia/Shanghai"
    elif mode == "intraday":
        r["meta"]["dataGranularity"] = "1h"
    else:
        r["timestamp"][0] = int(datetime(2024, 1, 1, 14, 30, tzinfo=UTC).timestamp())
    archive(tmp_path, payload)
    with pytest.raises(review.ArchiveValidationError):
        review.read_archives(tmp_path, asof=sessions()[-1])


def test_future_bars_are_censored_and_cannot_mature_outcomes(universe):
    cutoff = sessions()[204]
    report = review.build_review(universe, asof=cutoff)
    assert report["ma_reclaim"]["events_reconstructed"] == 8
    for source in report["sources"].values():
        assert source["retained_rows"] == 205
        assert source["future_rows_excluded"] == 20
        assert source["through"] == cutoff.isoformat()
    for stats in report["ma_reclaim"]["horizons"].values():
        assert stats["n"] == 0
        assert stats["mean_excess"] is None
        assert stats["ci95"] is None
        assert stats["skip_counts"] == {"horizon_not_mature": 8}
    selected, _ = review.read_archives(universe, asof=cutoff)
    fetch = review.local_price_fetcher(selected, asof=cutoff)
    assert fetch("NVDA", sessions()[205], days=10).empty
    assert fetch("NVDA", sessions()[199], days=10).index[-1].date() == sessions()[199]


def test_missing_exact_endpoint_never_uses_prior_or_future_bar(universe):
    for p in universe.glob("*.raw"):
        payload = json.loads(p.read_bytes())
        if payload["chart"]["result"][0]["meta"]["symbol"] == "NVDA":
            p.unlink()
            dates = sessions()
            closes = crossing_closes()
            del dates[205]
            del closes[205]
            archive(universe, chart("NVDA", dates=dates, closes=closes))
            break
    report = review.build_review(universe, asof=sessions()[-1])
    h = report["ma_reclaim"]["horizons"]
    assert h["5"]["n"] == 7
    assert h["5"]["skip_counts"] == {"missing_exact_session_price": 1}
    assert h["10"]["n"] == h["20"]["n"] == 8


def test_sma20_is_not_ema21_and_uses_adjusted_close(tmp_path):
    adjusted = [100.0] * 201
    adjusted[197] = 200.0
    adjusted[200] = 106.0
    archive(tmp_path, chart(closes=[300.0] * 201, adjusted=adjusted, dates=sessions(201)))
    selected, _ = review.read_archives(tmp_path, asof=sessions(201)[-1])
    events, summary = review.reconstruct_ma_reclaim(selected)
    assert [ev.date for ev in events] == [sessions(201)[-1]]
    assert events[0].meta["sma20"] == pytest.approx(105.3)
    assert events[0].meta["close"] == 106.0
    assert pd.Series(adjusted).ewm(span=21, adjust=False).mean().iloc[-1] > adjusted[-1]
    assert summary["NVDA"]["scanner_eligible_rows"] == 2


@pytest.mark.parametrize("n,expected", [(199, 0), (200, 0), (201, 1)])
def test_both_crossing_snapshots_require_200_bar_warmup(tmp_path, n, expected):
    archive(tmp_path, chart(closes=[100.0] * (n - 1) + [110.0], dates=sessions(n)))
    selected, _ = review.read_archives(tmp_path, asof=sessions(n)[-1])
    events, summary = review.reconstruct_ma_reclaim(selected)
    assert len(events) == expected
    assert summary["NVDA"]["scanner_eligible_rows"] == max(n - 199, 0)


def test_missing_previous_nyse_session_cannot_create_reclaim(tmp_path):
    dates = sessions(202)
    closes = [100.0] * 201 + [110.0]
    del dates[200]
    del closes[200]
    archive(tmp_path, chart(dates=dates, closes=closes))
    selected, _ = review.read_archives(tmp_path, asof=sessions(202)[-1])
    events, summary = review.reconstruct_ma_reclaim(selected)
    assert events == []
    assert summary["NVDA"]["session_gap_resets"] == 1


def test_version_selection_is_deterministic_not_mtime_or_field_blending(tmp_path):
    first = chart()
    second = copy.deepcopy(first)
    second["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][0] += 0.00001
    a, b = archive(tmp_path, first), archive(tmp_path, second)
    chosen1, _ = review.read_archives(tmp_path, asof=sessions()[-1])
    os.utime(a, (1, 1))
    os.utime(b, (2_000_000_000, 2_000_000_000))
    chosen2, _ = review.read_archives(tmp_path, asof=sessions()[-1])
    assert chosen1["NVDA"].sha256 == chosen2["NVDA"].sha256 == min(a.stem, b.stem)
    assert chosen1["NVDA"].bars == chosen2["NVDA"].bars
    # Wider usable history wins before the deterministic content hash tiebreak.
    longer = archive(tmp_path, chart(dates=sessions(226)))
    chosen3, _ = review.read_archives(tmp_path, asof=sessions(226)[-1])
    assert chosen3["NVDA"].sha256 == longer.stem


def test_missing_archive_is_unavailable_not_zero_samples(tmp_path):
    archive(tmp_path, chart())
    with pytest.raises(review.ArchiveValidationError, match="missing_required_symbols"):
        review.build_review(tmp_path, asof=sessions()[-1])


def test_discovery_ignores_unselected_ticker_and_html(tmp_path):
    archive(tmp_path, chart("NOT_A_WATCHLIST_STOCK"))
    raw = b"<html>opaque non-chart archive</html>"
    (tmp_path / (hashlib.sha256(raw).hexdigest() + ".raw")).write_bytes(raw)
    chosen, inventory = review.read_archives(tmp_path, asof=sessions()[-1])
    assert chosen == {}
    assert inventory["files_hash_verified"] == 2
    assert inventory["chart_files_ignored_unselected_symbol"] == 1
    assert inventory["non_chart_files"] == 1


def test_report_reproducible_sanitized_and_source_inputs_unchanged(universe):
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in universe.iterdir()}
    a = review.build_review(universe, asof=sessions()[-1])
    b = review.build_review(universe, asof=sessions()[-1])
    assert a == b
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in universe.iterdir()} == before
    text = json.dumps(a, allow_nan=False)
    assert str(universe) not in text
    assert "generated_at" not in text
    for source in a["sources"].values():
        assert not Path(source["source_path"]).is_absolute()
        assert ".." not in Path(source["source_path"]).parts
        data = (universe / source["source_path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == source["sha256"]


def test_cli_stdout_default_and_refuses_output_in_raw_root(universe, capsys):
    args = ["--raw-root", str(universe), "--asof", sessions()[-1].isoformat()]
    before = set(universe.iterdir())
    assert review.main(args) == 0
    assert json.loads(capsys.readouterr().out)["asof"] == sessions()[-1].isoformat()
    assert set(universe.iterdir()) == before
    assert review.main(args + ["--output", str(universe / "report.json")]) == 2
    captured = capsys.readouterr()
    assert str(universe) not in captured.err
    assert set(universe.iterdir()) == before


def test_cli_output_is_explicit_and_does_not_overwrite(universe, tmp_path, capsys):
    output = tmp_path / "review.json"
    args = ["--raw-root", str(universe), "--asof", sessions()[-1].isoformat(), "--output", str(output)]
    assert review.main(args) == 0
    original = output.read_bytes()
    assert review.main(args) == 2
    assert output.read_bytes() == original
    capsys.readouterr()
