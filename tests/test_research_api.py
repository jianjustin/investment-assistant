from investment_assistant.services import research


def test_kinds_endpoint(client):
    resp = client.get("/api/research/event-study/kinds")
    assert resp is not None
    assert "ma_reclaim" in resp.json()["kinds"]
    assert "rs_strong" in resp.json()["unavailable"]


def test_event_study_endpoint_passes_params(monkeypatch, client):
    seen = {}

    def fake_view(kind, *, since=None, asof=None):
        seen.update({"kind": kind, "since": since, "asof": asof})
        return {"result": {"kind": kind}, "degraded": False, "source": "computed"}

    monkeypatch.setattr(research, "event_study_view", fake_view)
    resp = client.get("/api/research/event-study?kind=rs_strong&since=2022-01-01&asof=2024-03-08")
    assert resp is not None
    assert seen["kind"] == "rs_strong"
    assert str(seen["since"]) == "2022-01-01"
    assert str(seen["asof"]) == "2024-03-08"
    assert resp.json()["result"]["kind"] == "rs_strong"


def test_event_study_endpoint_requires_kind(client):
    resp = client.get("/api/research/event-study")
    assert resp is not None
    assert resp.status_code == 400


def test_unavailable_events_return_explicit_error_not_empty_success(client):
    for kind in ("rs_strong", "eps_beat", "eps_miss", "vcp"):
        response = client.get(f"/api/research/event-study?kind={kind}")
        assert response.status_code == 400
        assert "unavailable" in response.json()["error"]


def test_api_asof_limits_real_engine_maturity_with_mock_data(monkeypatch, client):
    from datetime import date
    from investment_assistant.research.event_study import Event
    monkeypatch.setattr(research, "collect_events", lambda *a, **kw: [Event("AAA", date(2024, 3, 1), "score_high")])
    monkeypatch.setattr("investment_assistant.research.event_study._default_regime_fn", lambda d: "green")
    def forbidden(*a, **kw):
        raise AssertionError("immature horizons must not fetch data")
    monkeypatch.setattr("investment_assistant.data.price.get_price_history_asof", forbidden)
    response = client.get("/api/research/event-study?kind=score_high&asof=2024-03-04")
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["params"]["asof"] == "2024-03-04"
    assert all(s["n"] == 0 for s in result["horizons"].values())
    assert {s["error"] for s in result["params"]["skipped"]} == {"horizon_not_mature"}


def test_api_unconfigured_source_is_degraded_without_fake_zero_result(client):
    response = client.get("/api/research/event-study?kind=ma_reclaim&asof=2024-03-08")
    assert response.status_code == 200
    payload = response.json()
    assert payload["degraded"] is True
    assert payload["result"] is None
    assert payload["error"]["code"] == "database_unconfigured"


def test_api_source_and_cache_read_failures_never_expose_sql_or_credentials(monkeypatch, client):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://mock-only")
    def failed(*a, **kw):
        raise RuntimeError("postgres://user:private-secret@host SELECT private_table")
    monkeypatch.setattr(research, "_with_conn", failed)
    monkeypatch.setattr("investment_assistant.db.connect", failed)
    response = client.get("/api/research/event-study?kind=score_high&asof=2024-03-08")
    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["error"]["code"] == "source_read_failed"
    assert "private-secret" not in response.text and "private_table" not in response.text
