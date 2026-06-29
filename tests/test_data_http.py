from unittest.mock import MagicMock, patch
from investment_assistant.data import http


def _resp(status_code, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.text = "body"
    return r


def test_get_json_success():
    with patch("investment_assistant.data.http.requests.get", return_value=_resp(200, {"a": 1})):
        payload, status = http.get_json("http://x")
    assert payload == {"a": 1} and status["ok"] is True


def test_get_json_retries_on_500_then_succeeds():
    seq = [_resp(500), _resp(200, {"ok": 1})]
    with patch("investment_assistant.data.http.requests.get", side_effect=seq), \
         patch("investment_assistant.data.http.time.sleep"):
        payload, status = http.get_json("http://x", max_retries=2)
    assert payload == {"ok": 1} and status["ok"] is True


def test_get_json_4xx_fails_fast():
    with patch("investment_assistant.data.http.requests.get", return_value=_resp(404)) as g, \
         patch("investment_assistant.data.http.time.sleep"):
        payload, status = http.get_json("http://x", max_retries=3)
    assert payload is None and status["status_code"] == 404
    assert g.call_count == 1
