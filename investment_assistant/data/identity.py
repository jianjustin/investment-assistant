"""US security identity shared by the mainline, the watchlist and us_research."""
from __future__ import annotations

import re


def stock_id(ticker: str) -> str:
    ticker = ticker.strip().upper() if isinstance(ticker, str) else ''
    if not re.fullmatch(r'[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z])?', ticker):
        raise ValueError('Invalid US stock ticker')
    if ticker.endswith(('.SH', '.SZ', '.BJ', '.HK')):
        raise ValueError('Non-US stock identity')
    return f'US:stock:{ticker}'
