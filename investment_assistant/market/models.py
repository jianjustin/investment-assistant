from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class MarketSignal:
    signal_date: date
    market_status: str
    spy_ticker: str
    spy_close: float
    spy_ma200: float
    spy_above_200ma: bool
    vix_ticker: str
    vix_close: float
    source: str = "yfinance"
    details: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
