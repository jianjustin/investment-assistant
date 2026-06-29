from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import _harness


def test_run_task_success(monkeypatch):
    recorded = []
    sent = []
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **k: sent.append(a))
    out = _harness.run_task("metrics", lambda: {"n": 1}, config=AssistantConfig())
    assert out["status"] == "success"
    assert out["task"] == "metrics" and out["run_id"].startswith("metrics-")
    assert recorded[0]["status"] == "success" and recorded[0]["summary"] == {"n": 1}
    assert sent and sent[0][0] == "metrics"


def test_run_task_captures_exception(monkeypatch):
    recorded = []
    monkeypatch.setattr(_harness, "_record", lambda **kw: recorded.append(kw))
    monkeypatch.setattr(_harness, "dispatch", lambda *a, **k: None)

    def boom():
        raise RuntimeError("kaboom")

    out = _harness.run_task("filings", boom, config=AssistantConfig())
    assert out["status"] == "error"
    assert "kaboom" in out["summary"]["error"]
    assert recorded[0]["status"] == "error"
