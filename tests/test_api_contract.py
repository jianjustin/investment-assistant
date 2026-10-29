"""Pin API routing and no-DB fallback behaviour before layering refactor."""
import pytest


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)


def test_unknown_api_get_returns_404(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.json() == {"error": "not found"}


def test_status_get_route_resolves(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"database", "filings", "system"}


def test_operations_registry_shape(client):
    resp = client.get("/api/operations")
    assert resp.status_code == 200
    ids = {op["id"] for op in resp.json()["operations"]}
    assert ids == {"sync_filings", "health_check"}


def test_watchlist_get_falls_back_to_config_without_db(client):
    resp = client.get("/api/watchlist")
    assert resp.json()["count"] >= 1
    assert all(row["source"] == "config" for row in resp.json()["rows"])


def test_data_routes_without_db(client):
    resp = client.get("/api/data/families")
    assert resp.status_code == 503
    assert "数据库未配置" in resp.json()["error"]


def test_delete_route_resolves(monkeypatch, client):
    import investment_assistant.services.watchlist as watchlist_svc
    monkeypatch.setattr(watchlist_svc, "delete_watchlist_item", lambda ticker: {"ticker": ticker, "deleted": True})
    resp = client.delete("/api/watchlist/NVDA")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "NVDA", "deleted": True}
    resp_nope = client.delete("/api/nope")
    assert resp_nope.status_code == 404


DERIVATION_PATHS = {
    "/api/workbench/plans/{plan_id}/derivation",
    "/api/workbench/units/{ticker}/{signal_date}/derivation",
    "/api/workbench/stage-runs",
}


def test_derivation_and_stage_runs_routes_in_openapi(client):
    spec = client.get("/openapi.json").json()
    assert DERIVATION_PATHS <= set(spec["paths"])
    for path in DERIVATION_PATHS:
        assert set(spec["paths"][path].keys()) == {"get"}          # 全部是只读 GET


def test_plan_derivation_response_top_level_keys(client, monkeypatch):
    from investment_assistant.workbench import derivation_view
    use_case = {"derivation_version": "derivation-1", "plan": {"id": "p1"}, "trigger": [],
                "inputs": {}, "steps": [], "checks": [], "consistency": {"status": "consistent"},
                "evidence": "evidence", "trigger_note": "note", "run": {"ready": True}}
    monkeypatch.setattr(derivation_view, "plan_derivation", lambda plan_id: dict(use_case))
    resp = client.get("/api/workbench/plans/6f1d1c1e-6666-4444-8888-000000000001/derivation")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"derivation_version", "plan", "trigger", "inputs", "steps",
                                       "checks", "consistency", "evidence", "run"}


TIMELINE_ROUTES = {
    "/api/workbench/chains": {"get"},
    "/api/workbench/chains/{ticker}/{signal_date}": {"get"},
    "/api/workbench/plan-reviews": {"get"},
    "/api/workbench/chains/{ticker}/{signal_date}/recheck": {"post"},
    "/api/workbench/user-inputs": {"get", "post"},
}


def test_plan_timeline_routes_in_openapi(client):
    spec = client.get("/openapi.json").json()
    for path, methods in TIMELINE_ROUTES.items():
        assert path in spec["paths"], path
        assert set(spec["paths"][path].keys()) == methods, path


def test_chain_view_response_top_level_keys(client, monkeypatch):
    from investment_assistant.workbench import plan_review
    use_case = {"ticker": "SYNTH", "signal_date": "2026-09-01", "session": "2026-09-02",
                "state": {"state": "entry", "mode": "entry", "basis": "未决定"},
                "head_plan_id": "p1", "version_no": 0, "latest_review": None,
                "versions": [], "reviews": [], "inputs": []}
    monkeypatch.setattr(plan_review, "chain_view", lambda ticker, signal_date, *, now: dict(use_case))
    resp = client.get("/api/workbench/chains/SYNTH/2026-09-01")
    assert resp.status_code == 200
    body = resp.json()
    assert {"state", "versions", "reviews", "inputs"} <= set(body)
    assert set(body) == set(use_case)


def test_timeline_routes_without_db_are_503(client):
    assert client.get("/api/workbench/chains/SYNTH/2026-09-01").status_code == 503
    assert client.get("/api/workbench/chains?ticker=SYNTH").status_code == 503
    assert client.get("/api/workbench/plan-reviews?session=2026-09-02").status_code == 503
    assert client.get("/api/workbench/user-inputs?ticker=SYNTH").status_code == 503
    assert client.post("/api/workbench/chains/SYNTH/2026-09-01/recheck").status_code == 503


def test_ticker_chains_response_shape(client, monkeypatch):
    from investment_assistant.workbench import plan_review
    use_case = {"ticker": "SYNTH", "chains": [{"signal_date": "2026-09-01", "state": "entry", "mode": "entry",
                                               "version_no": 1, "head_plan_id": "p1", "latest_review": None}]}
    monkeypatch.setattr(plan_review, "ticker_chains", lambda ticker, *, now: use_case)
    body = client.get("/api/workbench/chains?ticker=SYNTH").json()
    assert set(body) == {"ticker", "chains"}
    assert set(body["chains"][0]) == {"signal_date", "state", "mode", "version_no", "head_plan_id", "latest_review"}


KNOWLEDGE_PATHS = {
    "/api/knowledge/concepts",
    "/api/knowledge/concepts/{ref}",
    "/api/knowledge/principles",
}


def test_knowledge_routes_in_openapi_and_read_only(client):
    spec = client.get("/openapi.json").json()
    assert KNOWLEDGE_PATHS <= set(spec["paths"])
    for path in KNOWLEDGE_PATHS:
        assert set(spec["paths"][path].keys()) == {"get"}


def test_knowledge_routes_work_without_db(client):
    assert client.get("/api/knowledge/concepts").status_code == 200      # real docs/knowledge (may be empty)


UNDERSTANDING_PATHS = {
    "/api/workbench/run-overview",
    "/api/workbench/agent-runs/{run_id}/reasoning",
}


def test_run_overview_and_reasoning_routes_in_openapi_and_read_only(client):
    spec = client.get("/openapi.json").json()
    assert UNDERSTANDING_PATHS <= set(spec["paths"])
    for path in UNDERSTANDING_PATHS:
        assert set(spec["paths"][path].keys()) == {"get"}


def test_run_overview_and_reasoning_without_db_are_503(client):
    assert client.get("/api/workbench/run-overview?session=2026-10-27").status_code == 503
    assert client.get(
        "/api/workbench/agent-runs/6f1d1c1e-6666-4444-8888-000000000001/reasoning").status_code == 503


# --- v2.7 growth loop (spec §12): every new path and its methods, error bodies and the 503 text ---

GROWTH_ROUTES = {
    "/api/workbench/review-cards": {"get"},
    "/api/workbench/review-cards/{card_id}": {"get"},
    "/api/workbench/review-cards/{card_id}/verdict": {"post"},
    "/api/workbench/review-cards/{card_id}/redraft": {"post"},
    "/api/workbench/my-knowledge": {"get", "post"},
    "/api/workbench/my-knowledge/{knowledge_id}": {"get"},
    "/api/workbench/my-knowledge/{knowledge_id}/versions": {"post"},
    "/api/workbench/my-knowledge/{knowledge_id}/status": {"post"},
    "/api/workbench/my-knowledge/{knowledge_id}/performance": {"get"},
    "/api/workbench/my-knowledge-drafts": {"get"},
    "/api/workbench/my-knowledge-drafts/{draft_id}/verdict": {"post"},
    "/api/workbench/discussions": {"get", "post"},
    "/api/workbench/discussions/{discussion_id}": {"get"},
    "/api/workbench/discussions/{discussion_id}/turns": {"post"},
}


def test_growth_routes_in_openapi(client):
    spec = client.get("/openapi.json").json()
    for path, methods in GROWTH_ROUTES.items():
        assert path in spec["paths"], path
        assert set(spec["paths"][path].keys()) == methods, path


def test_growth_turn_route_answers_202(client):
    spec = client.get("/openapi.json").json()
    assert "202" in spec["paths"]["/api/workbench/discussions/{discussion_id}/turns"]["post"]["responses"]


GROWTH_WITHOUT_DB = [
    ("get", "/api/workbench/review-cards"),
    ("get", "/api/workbench/review-cards/1"),
    ("post", "/api/workbench/review-cards/1/verdict"),
    ("post", "/api/workbench/review-cards/1/redraft"),
    ("get", "/api/workbench/my-knowledge"),
    ("post", "/api/workbench/my-knowledge"),
    ("get", "/api/workbench/my-knowledge/1"),
    ("post", "/api/workbench/my-knowledge/1/versions"),
    ("post", "/api/workbench/my-knowledge/1/status"),
    ("get", "/api/workbench/my-knowledge/1/performance"),
    ("get", "/api/workbench/my-knowledge-drafts"),
    ("post", "/api/workbench/my-knowledge-drafts/1/verdict"),
    ("get", "/api/workbench/discussions?card_id=1"),
    ("get", "/api/workbench/discussions/1"),
]

BODIES = {
    "/api/workbench/review-cards/1/verdict": {"request_id": "6f1d1c1e-6666-4444-8888-000000000001", "note": "",
                                             "lessons": []},
    "/api/workbench/my-knowledge": {"request_id": "6f1d1c1e-6666-4444-8888-000000000001", "title": "t", "body": "b",
                                    "scope": "s", "counter_examples": "", "concepts": [], "tickers": ["NVDA"]},
    "/api/workbench/my-knowledge/1/versions": {"request_id": "6f1d1c1e-6666-4444-8888-000000000001",
                                               "base_version": 1, "title": "t", "body": "b", "scope": "s",
                                               "tickers": ["NVDA"]},
    "/api/workbench/my-knowledge/1/status": {"request_id": "6f1d1c1e-6666-4444-8888-000000000001",
                                             "status": "archived", "reason": ""},
    "/api/workbench/my-knowledge-drafts/1/verdict": {"request_id": "6f1d1c1e-6666-4444-8888-000000000001",
                                                     "action": "dismiss"},
}


def test_growth_routes_without_db_are_503(client):
    for method, path in GROWTH_WITHOUT_DB:
        resp = getattr(client, method)(path, **({"json": BODIES[path]} if method == "post" and path in BODIES else {}))
        assert resp.status_code == 503, path
        assert "数据库未配置" in resp.json()["error"], path
    post = client.post("/api/workbench/discussions",
                       json={"request_id": "6f1d1c1e-6666-4444-8888-000000000001",
                             "context": {"kind": "card", "card_id": 1}})
    assert post.status_code == 503
    turn = client.post("/api/workbench/discussions/1/turns",
                       json={"request_id": "6f1d1c1e-6666-4444-8888-000000000001", "body": "问"})
    assert turn.status_code == 503


def test_growth_response_shapes_stay_stable(client, monkeypatch):
    from investment_assistant.workbench import discussion, my_knowledge, retro_cards
    monkeypatch.setattr(retro_cards, "list_view", lambda **kw: {"cards": [], "counts": {}})
    monkeypatch.setattr(retro_cards, "card_view", lambda card_id, *, now: {
        "card": {}, "facts": {}, "status": "to_review", "drafts": [], "lesson_drafts": [], "verdict": None,
        "discipline_now": {}, "discussions": []})
    monkeypatch.setattr(my_knowledge, "list_view", lambda **kw: {"items": []})
    monkeypatch.setattr(my_knowledge, "item_view", lambda knowledge_id, *, version=None: {
        "item": {}, "versions": [], "status_history": [], "citations": [], "current": {}})
    monkeypatch.setattr(my_knowledge, "drafts_view", lambda *, open_only: {"drafts": []})
    monkeypatch.setattr(discussion, "list_for", lambda **kw: [])
    monkeypatch.setattr(discussion, "view", lambda discussion_id: {
        "id": discussion_id, "context_kind": "plan", "ticker": "NVDA", "signal_date": "2026-10-20", "plan_id": "p",
        "card_id": None, "created_at": "x", "context": {}, "turns": []})
    assert set(client.get("/api/workbench/review-cards").json()) == {"cards", "counts"}
    assert set(client.get("/api/workbench/review-cards/1").json()) == {
        "card", "facts", "status", "drafts", "lesson_drafts", "verdict", "discipline_now", "discussions"}
    assert set(client.get("/api/workbench/my-knowledge").json()) == {"items"}
    assert set(client.get("/api/workbench/my-knowledge/1").json()) == {
        "item", "versions", "status_history", "citations", "current"}
    assert set(client.get("/api/workbench/my-knowledge-drafts").json()) == {"drafts"}
    assert client.get("/api/workbench/discussions?card_id=1").json() == {"discussions": []}
    assert set(client.get("/api/workbench/discussions/5").json()) == {
        "id", "context_kind", "ticker", "signal_date", "plan_id", "card_id", "created_at", "context", "turns"}
