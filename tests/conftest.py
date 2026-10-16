import pytest
from fastapi.testclient import TestClient

from investment_assistant.api.app import create_app


@pytest.fixture(autouse=True)
def isolate_unit_tests_from_local_database(monkeypatch):
    """Individual DB tests opt in explicitly; a local .env must not make mocks use production."""
    monkeypatch.delenv('INVESTMENT_ASSISTANT_DATABASE_URL', raising=False)
    monkeypatch.setenv('SCHEDULER_ENABLED', '0')


@pytest.fixture()
def client():
    return TestClient(create_app())
