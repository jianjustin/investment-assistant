from datetime import date

from investment_assistant.services import research


def test_available_kinds_lists_known():
    out = research.available_kinds()
    assert "rs_strong" in out["kinds"]
    assert "score_high" in out["kinds"]


def test_event_study_view_degraded_without_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    monkeypatch.setattr(research, "collect_events", lambda kind, **kw: [])
    out = research.event_study_view("rs_strong")
    assert out["degraded"] is True
    assert out["source"] == "computed"
    assert out["result"]["n"] == 0


def test_event_study_view_reads_cache(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(research, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(research.db, "get_event_study",
                        lambda conn, *, kind, params_hash: {"result": {"kind": kind, "n": 42}})
    out = research.event_study_view("rs_strong")
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
    out = research.event_study_view("rs_strong")
    assert out["source"] == "computed"
    assert saved.get("kind") == "rs_strong"  # 回填缓存被调用


class _FakeResult:
    def __init__(self, kind):
        self.kind = kind

    def to_dict(self):
        return {"kind": self.kind, "n": 1, "horizons": {}, "by_regime": {}, "caveats": []}
