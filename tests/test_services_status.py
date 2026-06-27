from unittest.mock import patch
from investment_assistant.services import status as status_svc


def test_operation_registry_ids():
    ids = {op["id"] for op in status_svc.operation_registry()}
    assert ids == {"fetch_market_signals", "sync_filings", "health_check"}


def test_system_status_uses_systemctl(monkeypatch):
    with patch("investment_assistant.services.status.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "active"
        out = status_svc.system_status()
    assert out["postgres_service"]["ok"] is True


def test_database_status_without_url(monkeypatch):
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    assert status_svc.database_status()["ok"] is False
