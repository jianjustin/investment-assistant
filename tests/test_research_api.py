from investment_assistant.services import research


def test_kinds_endpoint(client):
    resp = client.get("/api/research/event-study/kinds")
    assert resp is not None
    assert "rs_strong" in resp.json()["kinds"]


def test_event_study_endpoint_passes_params(monkeypatch, client):
    seen = {}

    def fake_view(kind, *, since=None, asof=None):
        seen.update({"kind": kind, "since": since, "asof": asof})
        return {"result": {"kind": kind}, "degraded": False, "source": "computed"}

    monkeypatch.setattr(research, "event_study_view", fake_view)
    resp = client.get("/api/research/event-study?kind=rs_strong&since=2022-01-01")
    assert resp is not None
    assert seen["kind"] == "rs_strong"
    assert str(seen["since"]) == "2022-01-01"
    assert resp.json()["result"]["kind"] == "rs_strong"


def test_event_study_endpoint_requires_kind(client):
    resp = client.get("/api/research/event-study")
    assert resp is not None
    assert resp.status_code == 400
