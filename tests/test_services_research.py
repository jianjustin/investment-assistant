from datetime import date

import pytest

from investment_assistant.services import research


def test_available_kinds_lists_known():
    out = research.available_kinds()
    assert "ma_reclaim" in out["kinds"]
    assert "score_high" in out["kinds"]
    for kind in ("rs_strong", "eps_beat", "eps_miss", "vcp"):
        assert kind not in out["kinds"]
        assert out["unavailable"][kind]


def test_event_study_view_degraded_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    monkeypatch.setattr(research, "collect_events", lambda kind, **kw: [])
    out = research.event_study_view("score_high")
    assert out["degraded"] is True
    assert out["source"] == "computed"
    assert out["result"]["n"] == 0
    assert out["result"]["kind"] == "score_high"


def test_event_study_view_reads_cache(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(research, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(research.db, "get_event_study",
                        lambda conn, *, kind, params_hash: {"result": {"kind": kind, "n": 42}})
    out = research.event_study_view("score_high")
    assert out["degraded"] is False
    assert out["source"] == "cache"
    assert out["result"]["n"] == 42


def test_event_study_view_computes_and_caches_on_miss(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(research, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(research.db, "get_event_study", lambda conn, *, kind, params_hash: None)
    saved = {}
    monkeypatch.setattr(research.db, "upsert_event_study",
                        lambda conn, *, kind, params_hash, result: saved.update(result))
    from investment_assistant.research.event_study import Event
    monkeypatch.setattr(research, "collect_events",
                        lambda kind, **kw: [Event("NVDA", date(2024, 3, 1), kind)])
    monkeypatch.setattr(research, "run_event_study",
                        lambda events, **kw: _FakeResult(events[0].kind))
    out = research.event_study_view("score_high")
    assert out["source"] == "computed"
    assert saved.get("kind") == "score_high"  # 回填缓存被调用


class _FakeResult:
    def __init__(self, kind):
        self.kind = kind

    def to_dict(self):
        return {"kind": self.kind, "n": 1, "horizons": {}, "by_regime": {}, "caveats": []}


def test_compute_passes_same_asof_to_sources_and_engine(monkeypatch):
    seen = {}
    monkeypatch.setattr(research, "collect_events", lambda kind, **kw: seen.update(source=kw) or [])
    monkeypatch.setattr(research, "run_event_study", lambda events, **kw: seen.update(engine=kw) or _FakeResult("score_high"))
    research.event_study_view("score_high", since=date(2023, 1, 1), asof=date(2024, 3, 8))
    assert seen["source"]["asof"] == seen["engine"]["asof"] == date(2024, 3, 8)
    assert seen["engine"]["horizons"] == (5, 10, 20)


def test_cache_hash_versions_semantics_and_market_regime_settings():
    import hashlib
    from dataclasses import replace
    from investment_assistant.config import AssistantConfig
    args = ("score_high", None, date(2024, 3, 8), (5, 10, 20))
    old_hash = hashlib.sha256(f"{args[0]}|{args[1]}|{args[2]}|{args[3]}".encode()).hexdigest()[:16]
    assert research._params_hash(*args) != old_hash
    cfg = AssistantConfig()
    changed = replace(cfg, market=replace(cfg.market, red_vix=99.0))
    assert research._params_hash(*args, config=cfg) != research._params_hash(*args, config=changed)


def test_default_asof_resolved_before_cache_lookup_and_changes_each_session(monkeypatch):
    seen = []
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    monkeypatch.setattr(research, "_with_conn", lambda fn: fn("MOCK"))
    monkeypatch.setattr(research.db, "get_event_study",
                        lambda conn, **kw: seen.append(kw["params_hash"]) or {"result": {}})
    monkeypatch.setattr(research, "resolve_asof", lambda asof: asof or date(2024, 3, 7))
    research.event_study_view("score_high")
    research.event_study_view("score_high", asof=date(2024, 3, 7))
    monkeypatch.setattr(research, "resolve_asof", lambda asof: asof or date(2024, 3, 8))
    research.event_study_view("score_high")
    assert seen[0] == seen[1]
    assert seen[0] != seen[2]


@pytest.mark.parametrize("kind", ["rs_strong", "eps_beat", "eps_miss", "vcp", "unknown"])
def test_unavailable_kind_cannot_be_resurrected_by_old_cache(kind, monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    monkeypatch.setattr(research, "_with_conn", lambda fn: pytest.fail("must not read cache"))
    with pytest.raises(ValueError, match="unavailable"):
        research.event_study_view(kind)


@pytest.mark.parametrize("kind", ["ma_reclaim", "score_high"])
def test_default_source_failure_never_caches_and_recovery_recomputes(monkeypatch, kind):
    from unittest.mock import MagicMock
    from investment_assistant import db
    cache, writes = {}, []
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    monkeypatch.setattr(research, "_with_conn", lambda fn: fn("MOCK"))
    monkeypatch.setattr(db, "get_event_study", lambda conn, **kw: cache.get(kw["params_hash"]))
    def save(conn, **kw):
        writes.append(kw)
        cache[kw["params_hash"]] = {"result": kw["result"]}
    monkeypatch.setattr(db, "upsert_event_study", save)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    reader = MagicMock(side_effect=[RuntimeError("password=secret SQL private_table"), connection])
    monkeypatch.setattr(db, "connect", reader)
    failed = research.event_study_view(kind, asof=date(2024, 3, 8))
    assert failed["degraded"] is True
    assert failed["result"] is None
    assert failed["error"]["code"] == "source_read_failed"
    assert "secret" not in str(failed) and "private_table" not in str(failed)
    assert writes == []
    recovered = research.event_study_view(kind, asof=date(2024, 3, 8))
    assert recovered["degraded"] is False
    assert recovered["source"] == "computed" and recovered["result"]["n"] == 0
    assert recovered["result"]["params"]["source_quality"]["status"] == "empty"
    assert len(writes) == 1
    cached = research.event_study_view(kind, asof=date(2024, 3, 8))
    assert cached["source"] == "cache" and reader.call_count == 2
    assert cached["result"]["params"]["source_quality"] == recovered["result"]["params"]["source_quality"]


def test_unconfigured_default_source_is_unavailable_not_successful_zero():
    out = research.event_study_view("ma_reclaim", asof=date(2024, 3, 8))
    assert out["degraded"] is True
    assert out["result"] is None
    assert out["source_quality"]["status"] == "unavailable"
    assert out["error"]["code"] == "database_unconfigured"


def test_cache_connection_failure_is_sanitized_not_an_api_exception(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    def fail(*a, **kw):
        raise RuntimeError("postgres://private-password SELECT secret_column")
    monkeypatch.setattr(research, "_with_conn", fail)
    monkeypatch.setattr("investment_assistant.db.connect", fail)
    out = research.event_study_view("score_high")
    assert out["degraded"] is True and out["result"] is None
    assert "private-password" not in str(out) and "secret_column" not in str(out)


def test_legacy_only_source_is_excluded_and_not_cached_as_normal_zero(monkeypatch):
    from investment_assistant.research import event_sources
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    monkeypatch.setattr(research, "_with_conn", lambda fn: fn("MOCK"))
    monkeypatch.setattr(research.db, "get_event_study", lambda *a, **kw: None)
    monkeypatch.setattr(research.db, "upsert_event_study", lambda *a, **kw: pytest.fail("excluded is not cacheable"))
    monkeypatch.setattr(event_sources, "_default_snapshot_source", lambda: [
        {"ticker": "AAA", "signal_date": date(2024, 3, 4), "close": 100, "ma20": 99,
         "prev_close": 98, "prev_ma20": 99}
    ])
    out = research.event_study_view("ma_reclaim", asof=date(2024, 3, 8))
    assert out["degraded"] is True
    quality = out["result"]["params"]["source_quality"]
    assert quality["status"] == "excluded" and quality["excluded_count"] == 1
    assert any("来源" in c and "不代表信号无效" in c for c in out["result"]["caveats"])


def test_compute_actual_regime_uses_passed_nondefault_market_not_reloaded_default(monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    import pandas as pd
    from investment_assistant.config import AssistantConfig
    from investment_assistant.research.event_study import Event
    cfg = AssistantConfig()
    cfg = replace(cfg, market=replace(cfg.market, red_vix=99.0))
    seen = []
    monkeypatch.setattr(research, "collect_events", lambda *a, **kw: [Event("AAA", date(2024, 3, 1), "score_high")])
    monkeypatch.setattr("investment_assistant.market.service.compute_market_signal_for_date",
                        lambda market, d: seen.append((market, d)) or SimpleNamespace(market_status="green"))
    monkeypatch.setattr("investment_assistant.config.load_config", lambda: pytest.fail("must use passed config"))
    monkeypatch.setattr("investment_assistant.data.price.get_price_history_asof",
                        lambda ticker, on, **kw: pd.DataFrame({"Close": [100.]}, index=pd.to_datetime([on])))
    result = research._compute("score_high", since=None, asof=date(2024, 3, 8), horizons=(5,), config=cfg)
    assert seen == [(cfg.market, date(2024, 3, 1))]
    assert result["by_regime"]["green"]["5"]["n"] == 1


def test_v3_hash_cannot_reuse_v2_results(monkeypatch):
    args = ("score_high", None, date(2024, 3, 8), (5, 10, 20))
    assert research.SEMANTICS_VERSION.startswith("event-study-v3")
    current = research._params_hash(*args)
    monkeypatch.setattr(research, "SEMANTICS_VERSION", "event-study-v2-exact-session-asof")
    assert research._params_hash(*args) != current
