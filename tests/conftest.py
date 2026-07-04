import pytest
from fastapi.testclient import TestClient

from investment_assistant.api.app import create_app


@pytest.fixture()
def client():
    return TestClient(create_app())
