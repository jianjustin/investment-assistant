"""News metadata from yfinance and SEC 8-K listings. Links are stored, bodies never fetched."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

NewsFetcher = Callable[[str], list]


def _yfinance_fetcher(ticker: str) -> list:
    import yfinance as yf

    return yf.Ticker(ticker).get_news(count=20)


def fetch_yfinance(ticker: str, *, fetcher: NewsFetcher | None = None) -> list:
    return (fetcher or _yfinance_fetcher)(ticker.upper())


def _url(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get('url')
    return value if isinstance(value, str) and value.startswith(('http://', 'https://')) else None


def _published(content: dict) -> datetime | None:
    raw = content.get('pubDate')
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else None
    epoch = content.get('providerPublishTime')
    if isinstance(epoch, (int, float)) and epoch > 0:
        return datetime.fromtimestamp(epoch, UTC)
    return None


def normalize_yfinance(raw: list) -> tuple[list[dict[str, Any]], int]:
    """Accept both the current ``{'content': {...}}`` shape and the legacy flat shape."""
    items: list[dict[str, Any]] = []
    skipped = 0
    for entry in raw:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        content = entry.get('content') if isinstance(entry.get('content'), dict) else entry
        title = content.get('title')
        url = _url(content.get('canonicalUrl')) or _url(content.get('clickThroughUrl')) or _url(content.get('link'))
        if not isinstance(title, str) or not title.strip() or not url:
            skipped += 1
            continue
        provider = content.get('provider')
        publisher = provider.get('displayName') if isinstance(provider, dict) else content.get('publisher')
        items.append({'source': 'yfinance', 'title': title.strip(), 'url': url,
                      'publisher': publisher if isinstance(publisher, str) else None,
                      'published_at': _published(content)})
    return items, skipped


def filing_news(metas: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[str]]]:
    """8-K listings from the SEC monitor's discover() as (news item, tickers)."""
    out = []
    for meta in metas:
        if meta.get('form') != '8-K' or not _url(meta.get('edgar_url')):
            continue
        items = meta.get('items')
        title = f"{meta['ticker']} 8-K" + (f" (Items {', '.join(items)})" if items else '')
        accepted = meta.get('accepted_at')
        out.append(({'source': 'sec_8k', 'title': title, 'url': meta['edgar_url'], 'publisher': 'SEC EDGAR',
                     'published_at': datetime.fromisoformat(accepted) if accepted else None}, [meta['ticker']]))
    return out
