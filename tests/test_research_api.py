from investment_assistant.api import routes  # noqa: F401  触发路由注册
from investment_assistant.api.router import dispatch
from investment_assistant.services import research


def test_kinds_endpoint():
    resp = dispatch("GET", "/api/research/event-study/kinds", None)
    assert resp is not None
    assert "rs_strong" in resp.payload["kinds"]


def test_event_study_endpoint_passes_params(monkeypatch):
    seen = {}

    def fake_view(kind, *, since=None, asof=None):
        seen.update({"kind": kind, "since": since, "asof": asof})
        return {"result": {"kind": kind}, "degraded": False, "source": "computed"}

    monkeypatch.setattr(research, "event_study_view", fake_view)
    resp = dispatch("GET", "/api/research/event-study?kind=rs_strong&since=2022-01-01", None)
    assert resp is not None
    assert seen["kind"] == "rs_strong"
    assert str(seen["since"]) == "2022-01-01"
    assert resp.payload["result"]["kind"] == "rs_strong"


def test_event_study_endpoint_requires_kind():
    resp = dispatch("GET", "/api/research/event-study", None)
    assert resp is not None
    assert resp.status == 400
