"""FRED credit and curve spreads (BAMLH0A0HYM2, T10Y2Y).

Observations are append-only: a revision on the same date with a different
value appends a row, reads reconstruct values as of a cutoff. The API key
comes only from the FRED_API_KEY environment variable and never appears in
messages — redacted to *** wherever it could leak.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from investment_assistant.data.http import get_json

FRED_URL = 'https://api.stlouisfed.org/fred/series/observations'
MACRO_SERIES = ('BAMLH0A0HYM2', 'T10Y2Y')
MACRO_LOOKBACK_DAYS = 120
MACRO_CHANGE_OBS = 20


class NotConfigured(RuntimeError):
    """FRED_API_KEY is absent; no request is made and nothing is stored."""


def redact(text: str, secret: str | None) -> str:
    """Replace every occurrence of the secret with ***; empty secrets redact nothing."""
    if secret:
        text = text.replace(secret, '***')
    return text


def _default_fetcher(url: str, *, params: dict) -> tuple[dict | None, dict]:
    return get_json(url, params=params)


def fetch_series(series_id: str, *, start: date, end: date, api_key: str | None,
                 fetcher=None) -> list[dict]:
    """Fetch one series as [{'obs_date', 'value'}], oldest first, '.' values skipped."""
    if not api_key:
        raise NotConfigured('FRED 未配置：缺少环境变量 FRED_API_KEY')
    fetch = fetcher or _default_fetcher
    params = {'series_id': series_id, 'api_key': api_key, 'file_type': 'json',
              'observation_start': start.isoformat(), 'observation_end': end.isoformat()}
    try:
        data, meta = fetch(FRED_URL, params=params)
    except Exception as exc:  # requests exceptions embed the full URL, key included
        raise RuntimeError(redact(str(exc), api_key)) from None
    if not meta.get('ok'):
        raise RuntimeError(redact(f"FRED 请求失败：HTTP {meta.get('status_code')} {meta.get('error')}", api_key))
    if not isinstance(data, dict) or 'observations' not in data:
        raise RuntimeError(redact(f'FRED 响应缺少 observations：{series_id}', api_key))
    rows: list[dict] = []
    for obs in data['observations']:
        raw = obs.get('value')
        if raw in (None, '.'):
            continue
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            continue
        rows.append({'obs_date': date.fromisoformat(obs['date']), 'value': value})
    rows.sort(key=lambda r: r['obs_date'])
    return rows
