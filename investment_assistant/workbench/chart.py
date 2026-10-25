"""Price chart payload for the instrument view: split-adjusted bars with simple moving averages."""
from __future__ import annotations

from typing import Any

READ_LIMIT = 450
KEEP = 250
WINDOWS = (20, 50, 200)

_BAR_FIELDS = ('price_date', 'open', 'high', 'low', 'close', 'volume')


def build(bars: list[dict[str, Any]], *, keep: int = KEEP) -> dict[str, Any]:
    """Keep the last ``keep`` bars; averages always use the full history handed in, oldest first."""
    closes = [bar['close'] for bar in bars]
    ma = {window: _rolling_mean(closes, window) for window in WINDOWS}
    return {'bars': [{**{field: bar[field] for field in _BAR_FIELDS},
                      **{f'ma{window}': ma[window][i] for window in WINDOWS}}
                     for i, bar in enumerate(bars)][-keep:],
            'adjustment': 'split_only'}


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    total = 0.0
    out: list[float | None] = []
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        out.append(total / window if i >= window - 1 else None)
    return out
