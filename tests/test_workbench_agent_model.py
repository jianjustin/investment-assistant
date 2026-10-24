"""Agent model wiring: env parsing, quota detection, key redaction. No network."""
from investment_assistant.workbench.agent import model


def test_defaults():
    s = model.settings_from_env({})
    assert s.provider == 'zhipu' and s.model == 'glm-5.3'
    assert s.base_url == model.DEFAULT_BASE_URL
    assert s.api_key is None and s.daily_tokens is None and s.config_error is None
    assert model.unavailable_reason(s) == 'not_configured'


def test_off_is_disabled():
    s = model.settings_from_env({'WORKBENCH_AGENT_PROVIDER': 'off'})
    assert s.provider == 'off' and model.unavailable_reason(s) == 'disabled'


def test_daily_tokens_parse():
    s = model.settings_from_env({'ZHIPU_API_KEY': 'sk-x', 'WORKBENCH_AGENT_DAILY_TOKENS': '500000'})
    assert s.daily_tokens == 500000 and model.unavailable_reason(s) is None
    for bad in ('0', 'abc', '-5'):
        s = model.settings_from_env({'ZHIPU_API_KEY': 'sk-x', 'WORKBENCH_AGENT_DAILY_TOKENS': bad})
        assert s.config_error == 'WORKBENCH_AGENT_DAILY_TOKENS 必须是正整数'
        assert s.daily_tokens is None and model.unavailable_reason(s) == 'not_configured'


class FakeAPIError(Exception):
    def __init__(self, status_code, body):
        super().__init__(f'Error code: {status_code} - {body}')
        self.status_code = status_code
        self.body = body


def test_quota_429_classified():
    exc = FakeAPIError(429, {'error': {'code': '1308', 'message': '已达到 5 小时的使用上限'}})
    reason, detail = model.classify_error(exc, None)
    assert reason == 'quota_exhausted' and '1308' in detail
    exc = FakeAPIError(429, {'code': '1113', 'message': 'insufficient balance'})
    reason, _ = model.classify_error(exc, None)
    assert reason == 'quota_exhausted'


def test_other_429_is_model_error():
    exc = FakeAPIError(429, {'error': {'code': '1302', 'message': 'rate limited'}})
    reason, detail = model.classify_error(exc, None)
    assert reason == 'model_error' and '1302' in detail


def test_error_detail_redacts_key():
    exc = FakeAPIError(500, {'error': {'code': '500', 'message': 'boom with sk-secret-key inside'}})
    reason, detail = model.classify_error(exc, 'sk-secret-key')
    assert reason == 'model_error'
    assert 'sk-secret-key' not in detail and '***' in detail
    assert len(detail) <= 300


def test_chat_model_points_at_base_url():
    s = model.settings_from_env({'ZHIPU_API_KEY': 'sk-x', 'WORKBENCH_AGENT_MODEL': 'glm-5.3',
                                 'WORKBENCH_AGENT_BASE_URL': 'https://zhipu.example/v4'})
    m = model.chat_model(s)
    assert m.model_name == 'glm-5.3'
    assert m.openai_api_base == 'https://zhipu.example/v4'
