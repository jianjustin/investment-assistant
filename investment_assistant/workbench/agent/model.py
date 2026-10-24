"""Agent model wiring: settings, the ChatOpenAI client, quota detection, checkpoints (§4).

The key comes only from the environment and is redacted from every error
detail; a 429 carrying a quota error code stops the agent track for the rest
of the batch, anything else retries in the client and lands as model_error.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import ContextManager, Mapping

from langchain_core.language_models import BaseChatModel

from investment_assistant.workbench.macro import redact

DEFAULT_MODEL = 'glm-5.3'
DEFAULT_BASE_URL = 'https://open.bigmodel.cn/api/coding/paas/v4'
TEMPERATURE = 0.2
REQUEST_TIMEOUT_S = 90
CLIENT_RETRIES = 2
QUOTA_CODES = frozenset({'1113', '1308', '1310'})


@dataclass(frozen=True)
class AgentSettings:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    daily_tokens: int | None
    config_error: str | None


def settings_from_env(env: Mapping[str, str] = os.environ) -> AgentSettings:
    daily_tokens, config_error = None, None
    raw = env.get('WORKBENCH_AGENT_DAILY_TOKENS')
    if raw:
        try:
            parsed = int(raw)
        except ValueError:
            parsed = 0
        if parsed > 0:
            daily_tokens = parsed
        else:
            config_error = 'WORKBENCH_AGENT_DAILY_TOKENS 必须是正整数'
    return AgentSettings(
        provider=env.get('WORKBENCH_AGENT_PROVIDER') or 'zhipu',
        model=env.get('WORKBENCH_AGENT_MODEL') or DEFAULT_MODEL,
        base_url=env.get('WORKBENCH_AGENT_BASE_URL') or DEFAULT_BASE_URL,
        api_key=env.get('ZHIPU_API_KEY') or None,
        daily_tokens=daily_tokens,
        config_error=config_error,
    )


def unavailable_reason(s: AgentSettings) -> str | None:
    if s.provider == 'off':
        return 'disabled'
    if not s.api_key or s.config_error:
        return 'not_configured'
    return None


def chat_model(s: AgentSettings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=s.model, base_url=s.base_url, api_key=s.api_key, temperature=TEMPERATURE,
                      timeout=REQUEST_TIMEOUT_S, max_retries=CLIENT_RETRIES)


def _body_code(exc: BaseException) -> str | None:
    body = getattr(exc, 'body', None)
    if not isinstance(body, dict):
        return None
    error = body.get('error')
    if isinstance(error, dict) and 'code' in error:
        return str(error['code'])
    return str(body['code']) if 'code' in body else None


def classify_error(exc: BaseException, api_key: str | None) -> tuple[str, str]:
    detail = redact(f'{type(exc).__name__}: {exc}', api_key)[:300]
    if getattr(exc, 'status_code', None) == 429 and _body_code(exc) in QUOTA_CODES:
        return 'quota_exhausted', detail
    return 'model_error', detail


@contextmanager
def checkpointer(url: str) -> ContextManager:
    from langgraph.checkpoint.postgres import PostgresSaver
    with PostgresSaver.from_conn_string(url) as saver:
        yield saver


def setup_checkpoints(url: str) -> None:
    with checkpointer(url) as saver:
        saver.setup()
