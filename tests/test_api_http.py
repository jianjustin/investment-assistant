from investment_assistant.api.http import ApiResponse, parse_int, parse_csv, parse_payload_bool, json_body


def test_parse_int_clamps():
    assert parse_int("999", default=10, minimum=1, maximum=100) == 100
    assert parse_int(None, default=10, minimum=1, maximum=100) == 10
    assert parse_int("abc", default=7, minimum=1, maximum=100) == 7


def test_parse_csv_upper():
    assert parse_csv("nvda, mu ,") == ["NVDA", "MU"]


def test_parse_payload_bool():
    assert parse_payload_bool("yes", default=False) is True
    assert parse_payload_bool(None, default=True) is True


def test_json_body_roundtrip():
    body, ctype = json_body({"a": 1}, 200)
    assert b'"a": 1' in body and ctype.startswith("application/json")


def test_api_response_default_status():
    assert ApiResponse({"ok": True}).status == 200
