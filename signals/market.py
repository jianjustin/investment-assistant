from dataclasses import dataclass
from data.price import get_price_history


@dataclass
class MarketCondition:
    status: str          # "green" | "yellow" | "red"
    vix: float
    spy_above_200ma: bool


def get_market_condition() -> MarketCondition:
    """Compute current broad market environment using SPY 200MA and VIX."""
    spy_df = get_price_history("SPY", days=300)
    vix_df = get_price_history("^VIX", days=5)

    spy_close = spy_df["Close"].iloc[-1]
    ma200 = spy_df["Close"].tail(200).mean()
    spy_above_200ma = bool(spy_close > ma200)

    vix = float(vix_df["Close"].iloc[-1])

    if vix > 30:
        status = "red"
    elif not spy_above_200ma or vix > 20:
        status = "yellow"
    else:
        status = "green"

    return MarketCondition(status=status, vix=vix, spy_above_200ma=spy_above_200ma)
