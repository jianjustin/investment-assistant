# earning-agent Phase 2: Layered Architecture + Discord + Technical Signals

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor earning-agent into a 4-layer quantitative pipeline (data → signals → engine → notify) and implement Phase 2: Discord multi-channel notifications, market environment gate (SPY/VIX), and technical signals (VCP/RS/MA Reclaim).

**Architecture:** Layered pipeline where data fetching, signal computation, and notification are separated. Market environment (SPY/VIX) acts as a gate — no individual signals fire when market is "red". Discord webhooks push to three dedicated channels based on signal type. Existing Phase 1 scripts migrate into `data/` and `ops/` without losing functionality.

**Tech Stack:** Python 3.10+, yfinance, requests (Discord webhooks), python-dotenv, pandas, numpy (via yfinance), pytest

---

## System Roadmap

| Phase | Status | Focus |
|-------|--------|-------|
| Phase 1 | ✅ Done | 财报监听: yfinance 检测 + SEC EDGAR + Obsidian |
| **Phase 2** | **🚀 This plan** | 目录重组 + Discord 通知 + 市场门控 + 技术面信号 |
| Phase 3 | 📋 Future | 基本面质量评分 + 决策引擎 + 综合评分 |
| Phase 4 | 📋 Future | 历史回测 + 信号准确率统计 |

## Signal Flow (Phase 2)

```
大盘环境门控 (SPY/VIX) → green/yellow/red
         ↓ (skip all if red)
个股信号并行: RS Score | VCP | MA Reclaim
         ↓ (has_signal=True)
Discord #trade-signals  +  #daily-scan (always)
         ↓
财报事件 (existing) → Discord #earnings-alerts
```

## Target File Structure

```
earnings-agent/
├── scripts/                     ← 小脚本验证目录
│   ├── README.md
│   ├── test_discord.py           (validate Discord webhook)
│   ├── test_market.py            (validate SPY/VIX detection)
│   └── test_vcp.py               (validate technical signals)
├── data/                         ← 数据获取层
│   ├── __init__.py
│   ├── price.py                  (yfinance OHLCV — NEW)
│   ├── earnings.py               (moved from earnings_calendar.py)
│   └── sec.py                    (moved from sec_downloader.py)
├── signals/                      ← 信号计算层
│   ├── __init__.py
│   ├── market.py                 (SPY/VIX 大盘门控 — NEW)
│   └── technicals.py             (VCP/RS/MA Reclaim — NEW)
├── notify/                       ← 通知层
│   ├── __init__.py
│   ├── discord.py                (Discord webhook client — NEW)
│   └── templates.py              (embed message templates — NEW)
├── vault/                        ← Obsidian 输出 (moved)
│   ├── __init__.py
│   └── writer.py                 (moved from vault_writer.py)
├── ops/                          ← 调度入口
│   ├── earnings_monitor.py       (moved + Discord wired)
│   ├── daily_scan.py             (NEW — 21:00 daily scan)
│   └── diagnose.py               (moved from diagnose_edgar.py)
├── tests/
│   ├── test_discord.py
│   ├── test_market.py
│   ├── test_price.py
│   └── test_technicals.py
├── .env                          (add 3 Discord webhook URLs)
└── requirements.txt
```

---

## Task 1: Repo Restructuring

**Files:**
- Create: `data/`, `signals/`, `notify/`, `vault/`, `ops/`, `tests/`, `scripts/` directories
- Create: `data/__init__.py`, `signals/__init__.py`, `notify/__init__.py`, `vault/__init__.py`, `ops/__init__.py`
- Move (copy): `earnings_calendar.py` → `data/earnings.py`
- Move (copy): `sec_downloader.py` → `data/sec.py`
- Move (copy): `vault_writer.py` → `vault/writer.py`
- Move (copy): `earnings_monitor.py` → `ops/earnings_monitor.py`
- Move (copy): `diagnose_edgar.py` → `ops/diagnose.py`

- [ ] **Step 1.1: Create directories and `__init__.py` files**

```bash
mkdir -p data signals notify vault ops tests scripts
touch data/__init__.py signals/__init__.py notify/__init__.py vault/__init__.py ops/__init__.py
```

- [ ] **Step 1.2: Copy existing files to new locations**

```bash
cp earnings_calendar.py data/earnings.py
cp sec_downloader.py data/sec.py
cp vault_writer.py vault/writer.py
cp earnings_monitor.py ops/earnings_monitor.py
cp diagnose_edgar.py ops/diagnose.py
```

- [ ] **Step 1.3: Fix imports in ops/earnings_monitor.py**

Open `ops/earnings_monitor.py`. Lines 16-20 already have `import sys` and `import os`. After line 20, insert the path fix. Then replace lines 42-43:

```python
# After line 20 (import sys / import os block), add:
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Replace lines 42-43:
# from earnings_calendar import scan_watchlist, get_earnings_date_for_ticker
# from sec_downloader import SECDownloader
# With:
from data.earnings import scan_watchlist, get_earnings_date_for_ticker
from data.sec import SECDownloader
```

- [ ] **Step 1.4: Verify ops/earnings_monitor.py still runs**

```bash
cd /Users/chenjianrui/personal-workspaces/earnings-agent
source .venv/bin/activate
python ops/earnings_monitor.py --dry-run
```

Expected output: log lines showing watchlist loaded and scan complete, no errors.

- [ ] **Step 1.5: Create scripts/README.md**

```markdown
# scripts/

Standalone validation scripts for quick testing without running the full pipeline.

| Script | Purpose | Run |
|--------|---------|-----|
| test_discord.py | Verify Discord webhook connectivity | `python scripts/test_discord.py` |
| test_market.py | Verify SPY/VIX market detection | `python scripts/test_market.py` |
| test_vcp.py | Verify technical signal computation | `python scripts/test_vcp.py [TICKER]` |

All scripts can be run from the project root after activating the venv.
```

- [ ] **Step 1.6: Commit**

```bash
git add data/ signals/ notify/ vault/ ops/ tests/ scripts/
git commit -m "refactor: restructure into layered architecture (data/signals/notify/vault/ops)"
```

---

## Task 2: Discord Notification Layer

**Files:**
- Create: `notify/discord.py`
- Create: `notify/templates.py`
- Create: `tests/test_discord.py`
- Create: `scripts/test_discord.py`
- Modify: `.env` (add 3 Discord webhook URLs)

Discord sends to three channels via webhook:
- `#earnings-alerts` — earnings events
- `#trade-signals` — technical signal triggers
- `#daily-scan` — daily scan summary (always fires)

Webhook API: `POST https://discord.com/api/webhooks/{id}/{token}` with JSON body.

- [ ] **Step 2.1: Write failing tests**

Create `tests/test_discord.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from notify.discord import DiscordClient, DiscordChannel


def test_send_earnings_calls_correct_webhook():
    client = DiscordClient(
        earnings_url="https://discord.com/api/webhooks/test/earnings",
        signals_url="https://discord.com/api/webhooks/test/signals",
        daily_url="https://discord.com/api/webhooks/test/daily",
    )
    with patch("notify.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        client.send(DiscordChannel.EARNINGS, {"content": "test"})
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "earnings" in call_url


def test_send_raises_on_non_204():
    client = DiscordClient(
        earnings_url="https://discord.com/api/webhooks/test/earnings",
        signals_url="",
        daily_url="",
    )
    with patch("notify.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")
        with pytest.raises(RuntimeError, match="Discord send failed"):
            client.send(DiscordChannel.EARNINGS, {"content": "test"})


def test_send_signals_calls_signals_webhook():
    client = DiscordClient(
        earnings_url="https://discord.com/api/webhooks/test/earnings",
        signals_url="https://discord.com/api/webhooks/test/signals",
        daily_url="https://discord.com/api/webhooks/test/daily",
    )
    with patch("notify.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        client.send(DiscordChannel.SIGNALS, {"content": "test"})
        call_url = mock_post.call_args[0][0]
        assert "signals" in call_url
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_discord.py -v
```

Expected: `ImportError: No module named 'notify.discord'`

- [ ] **Step 2.3: Implement notify/discord.py**

```python
from enum import Enum
import requests


class DiscordChannel(Enum):
    EARNINGS = "earnings"
    SIGNALS = "signals"
    DAILY = "daily"


class DiscordClient:
    def __init__(self, earnings_url: str, signals_url: str, daily_url: str):
        self._urls = {
            DiscordChannel.EARNINGS: earnings_url,
            DiscordChannel.SIGNALS: signals_url,
            DiscordChannel.DAILY: daily_url,
        }

    def send(self, channel: DiscordChannel, payload: dict) -> None:
        url = self._urls[channel]
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"Discord send failed: {resp.status_code} {resp.text}")

    @classmethod
    def from_env(cls) -> "DiscordClient":
        from dotenv import load_dotenv
        import os
        load_dotenv()
        return cls(
            earnings_url=os.environ["DISCORD_WEBHOOK_EARNINGS"],
            signals_url=os.environ["DISCORD_WEBHOOK_SIGNALS"],
            daily_url=os.environ["DISCORD_WEBHOOK_DAILY"],
        )
```

- [ ] **Step 2.4: Implement notify/templates.py**

```python
from datetime import date


def _footer() -> dict:
    return {"text": f"earning-agent • {date.today().isoformat()}"}


def earnings_alert_embed(
    ticker: str,
    earnings_date: str,
    direction: str,
    eps_beat: str,
    revenue_beat: str,
    guidance: str,
    confidence: int,
    highlights: list[str],
) -> dict:
    color = {
        "Long": 3066993,
        "Short": 15158332,
        "Watch": 16776960,
        "Wait": 9807270,
    }.get(direction, 9807270)
    return {
        "embeds": [{
            "title": f"📊 {ticker} Earnings — {direction}",
            "color": color,
            "fields": [
                {"name": "EPS", "value": eps_beat, "inline": True},
                {"name": "Revenue", "value": revenue_beat, "inline": True},
                {"name": "Guidance", "value": guidance, "inline": True},
                {"name": "Confidence", "value": f"{confidence}/5", "inline": True},
                {"name": "Earnings Date", "value": earnings_date, "inline": True},
                {
                    "name": "Highlights",
                    "value": "\n".join(f"• {h}" for h in highlights[:3]) or "—",
                    "inline": False,
                },
            ],
            "footer": _footer(),
        }]
    }


def signal_alert_embed(
    ticker: str,
    rs_score: float,
    vcp: bool,
    ma_reclaim: bool,
    market_status: str,
) -> dict:
    signals = []
    if vcp:
        signals.append("VCP 收缩形态")
    if ma_reclaim:
        signals.append("MA 穿越")
    if rs_score >= 1.2:
        signals.append(f"RS {rs_score:.2f} 强势")
    return {
        "embeds": [{
            "title": f"📈 {ticker} 技术信号",
            "color": 3447003,
            "fields": [
                {"name": "触发信号", "value": " | ".join(signals) or "无", "inline": False},
                {"name": "RS Score", "value": f"{rs_score:.2f}", "inline": True},
                {"name": "市场环境", "value": market_status.upper(), "inline": True},
            ],
            "footer": _footer(),
        }]
    }


def daily_summary_embed(
    market_status: str,
    vix: float,
    candidates: list[dict],
) -> dict:
    rows = "\n".join(
        f"• **{c['ticker']}** — {', '.join(c['signals'])}"
        for c in candidates[:10]
    ) or "今日无候选"
    return {
        "embeds": [{
            "title": "🗓 每日扫描摘要",
            "color": 10070709,
            "fields": [
                {"name": "市场环境", "value": f"{market_status.upper()} | VIX {vix:.1f}", "inline": False},
                {"name": f"候选股票 ({len(candidates)})", "value": rows, "inline": False},
            ],
            "footer": _footer(),
        }]
    }
```

- [ ] **Step 2.5: Run tests to verify they pass**

```bash
python -m pytest tests/test_discord.py -v
```

Expected: 3 PASSED

- [ ] **Step 2.6: Create scripts/test_discord.py validation script**

```python
#!/usr/bin/env python3
"""Validate Discord webhook connectivity. Run: python scripts/test_discord.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notify.discord import DiscordClient, DiscordChannel
from notify.templates import earnings_alert_embed

client = DiscordClient.from_env()
payload = earnings_alert_embed(
    ticker="TEST",
    earnings_date="2026-05-17",
    direction="Watch",
    eps_beat="$1.00 vs $0.95E (+5.3%)",
    revenue_beat="$10.0B vs $9.8BE (+2.0%)",
    guidance="上调",
    confidence=3,
    highlights=["这是测试消息", "验证 Discord webhook 连接", "可以安全忽略"],
)
client.send(DiscordChannel.EARNINGS, payload)
print("✅ Discord #earnings-alerts 发送成功")
```

- [ ] **Step 2.7: Add Discord webhook URLs to .env**

Add three lines to `.env`:

```
DISCORD_WEBHOOK_EARNINGS=https://discord.com/api/webhooks/<id>/<token>
DISCORD_WEBHOOK_SIGNALS=https://discord.com/api/webhooks/<id>/<token>
DISCORD_WEBHOOK_DAILY=https://discord.com/api/webhooks/<id>/<token>
```

To get webhook URLs: Discord channel settings → Integrations → Webhooks → New Webhook.
Create three webhooks for `#earnings-alerts`, `#trade-signals`, `#daily-scan`.

- [ ] **Step 2.8: Validate end-to-end**

```bash
python scripts/test_discord.py
```

Expected: `✅ Discord #earnings-alerts 发送成功` and a test embed appears in your Discord channel.

- [ ] **Step 2.9: Commit**

```bash
git add notify/ tests/test_discord.py scripts/test_discord.py
git commit -m "feat: add Discord notification layer with multi-channel support"
```

---

## Task 3: Data Layer — price.py

**Files:**
- Create: `data/price.py`
- Create: `tests/test_price.py`

`price.py` provides OHLCV price history. Used by both `signals/market.py` and `signals/technicals.py`.

- [ ] **Step 3.1: Write failing tests**

Create `tests/test_price.py`:

```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from data.price import get_price_history


def test_get_price_history_returns_dataframe():
    mock_df = pd.DataFrame(
        {"Open": [100.0], "High": [105.0], "Low": [99.0], "Close": [103.0], "Volume": [1_000_000]},
        index=pd.to_datetime(["2026-05-16"]),
    )
    with patch("data.price.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = mock_df
        result = get_price_history("AAPL", days=90)
        assert isinstance(result, pd.DataFrame)
        assert "Close" in result.columns
        assert len(result) >= 1


def test_get_price_history_raises_on_empty():
    with patch("data.price.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        with pytest.raises(ValueError, match="No price data"):
            get_price_history("FAKEFAKE", days=90)


def test_get_price_history_returns_correct_columns():
    mock_df = pd.DataFrame(
        {
            "Open": [100.0], "High": [105.0], "Low": [99.0],
            "Close": [103.0], "Volume": [1_000_000],
            "Dividends": [0.0], "Stock Splits": [0.0],
        },
        index=pd.to_datetime(["2026-05-16"]),
    )
    with patch("data.price.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = mock_df
        result = get_price_history("AAPL", days=90)
        assert set(result.columns) == {"Open", "High", "Low", "Close", "Volume"}
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_price.py -v
```

Expected: `ImportError: No module named 'data.price'`

- [ ] **Step 3.3: Implement data/price.py**

```python
import yfinance as yf
import pandas as pd


def get_price_history(ticker: str, days: int = 90) -> pd.DataFrame:
    """Return OHLCV DataFrame for ticker over the last `days` calendar days."""
    df = yf.Ticker(ticker).history(period=f"{days}d")
    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")
    return df[["Open", "High", "Low", "Close", "Volume"]]
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_price.py -v
```

Expected: 3 PASSED

- [ ] **Step 3.5: Commit**

```bash
git add data/price.py tests/test_price.py
git commit -m "feat: add data/price.py OHLCV history fetching"
```

---

## Task 4: Market Environment Gate

**Files:**
- Create: `signals/market.py`
- Create: `tests/test_market.py`
- Create: `scripts/test_market.py`

Output: `MarketCondition(status, vix, spy_above_200ma)`

Status rules:
- `"red"` — VIX > 30 (high fear, avoid all positions)
- `"yellow"` — SPY below 200MA OR VIX 20-30 (caution)
- `"green"` — SPY above 200MA AND VIX < 20 (normal conditions)

- [ ] **Step 4.1: Write failing tests**

Create `tests/test_market.py`:

```python
import pandas as pd
import pytest
from unittest.mock import patch
from signals.market import get_market_condition, MarketCondition


def _spy_df(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1_000_000] * len(closes)},
        index=idx,
    )


def _vix_df(close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": [close], "High": [close], "Low": [close], "Close": [close], "Volume": [0]},
        index=pd.to_datetime(["2026-05-16"]),
    )


def test_green_when_spy_bull_and_low_vix():
    # SPY trending up, well above 200MA; VIX = 15
    spy_closes = [100.0] * 150 + [120.0] * 60
    with patch("signals.market.get_price_history") as mock:
        mock.side_effect = [_spy_df(spy_closes), _vix_df(15.0)]
        cond = get_market_condition()
        assert cond.status == "green"
        assert cond.spy_above_200ma is True
        assert cond.vix == pytest.approx(15.0)


def test_red_when_vix_above_30():
    spy_closes = [100.0] * 150 + [120.0] * 60
    with patch("signals.market.get_price_history") as mock:
        mock.side_effect = [_spy_df(spy_closes), _vix_df(35.0)]
        cond = get_market_condition()
        assert cond.status == "red"


def test_yellow_when_spy_below_200ma():
    # SPY drops below 200MA; VIX = 18 (below 20)
    spy_closes = [120.0] * 150 + [90.0] * 60
    with patch("signals.market.get_price_history") as mock:
        mock.side_effect = [_spy_df(spy_closes), _vix_df(18.0)]
        cond = get_market_condition()
        assert cond.status == "yellow"
        assert cond.spy_above_200ma is False


def test_yellow_when_vix_between_20_and_30():
    spy_closes = [100.0] * 150 + [110.0] * 60
    with patch("signals.market.get_price_history") as mock:
        mock.side_effect = [_spy_df(spy_closes), _vix_df(25.0)]
        cond = get_market_condition()
        assert cond.status == "yellow"
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_market.py -v
```

Expected: `ImportError: No module named 'signals.market'`

- [ ] **Step 4.3: Implement signals/market.py**

```python
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
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_market.py -v
```

Expected: 4 PASSED

- [ ] **Step 4.5: Create scripts/test_market.py**

```python
#!/usr/bin/env python3
"""Validate market condition detection. Run: python scripts/test_market.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals.market import get_market_condition

cond = get_market_condition()
print(f"\n大盘环境:")
print(f"  Status      : {cond.status.upper()}")
print(f"  VIX         : {cond.vix:.1f}")
print(f"  SPY > 200MA : {cond.spy_above_200ma}")
```

- [ ] **Step 4.6: Commit**

```bash
git add signals/market.py tests/test_market.py scripts/test_market.py
git commit -m "feat: add market environment gate (SPY 200MA + VIX) to signals layer"
```

---

## Task 5: Technical Signals (VCP / RS / MA Reclaim)

**Files:**
- Create: `signals/technicals.py`
- Create: `tests/test_technicals.py`
- Create: `scripts/test_vcp.py`

Three signals computed per ticker:

| Signal | Logic | Threshold |
|--------|-------|-----------|
| **RS Score** | ticker 126-day return ÷ SPY 126-day return | ≥ 1.2 = strong |
| **VCP** | recent 20-bar ATR < 70% of 60-bar ATR AND vol_20 < 70% of vol_60 | both conditions must hold |
| **MA Reclaim** | yesterday close < 21-EMA AND today close > 21-EMA | cross from below |

`has_signal` = True if any of: `vcp`, `ma_reclaim`, or `rs_score >= 1.2`.

- [ ] **Step 5.1: Write failing tests**

Create `tests/test_technicals.py`:

```python
import pandas as pd
import pytest
from unittest.mock import patch
from signals.technicals import compute_technicals, TechnicalSignal


def _price_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    vols = volumes or [1_000_000.0] * n
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": vols,
        },
        index=idx,
    )


def test_rs_score_above_1_when_ticker_outperforms_spy():
    # Ticker +30% over 126d, SPY +10%
    ticker_closes = [100.0] * 60 + [130.0] * 70   # 130 bars total
    spy_closes = [400.0] * 60 + [440.0] * 70
    with patch("signals.technicals.get_price_history") as mock:
        mock.side_effect = [_price_df(ticker_closes), _price_df(spy_closes)]
        sig = compute_technicals("NVDA")
        assert sig.rs_score > 1.0


def test_ma_reclaim_detected_when_price_crosses_21ema():
    # 25 bars at 50 to establish EMA, then dip to 45 (yesterday), then 55 (today)
    closes = [50.0] * 25 + [45.0] + [55.0]
    with patch("signals.technicals.get_price_history") as mock:
        mock.side_effect = [
            _price_df(closes),
            _price_df([400.0] * len(closes)),  # SPY flat, for RS
        ]
        sig = compute_technicals("AAPL")
        assert sig.ma_reclaim is True


def test_no_signal_on_flat_price():
    # Flat price with constant volume — no VCP, no MA reclaim, RS ≈ 1.0
    closes = [100.0] * 130
    with patch("signals.technicals.get_price_history") as mock:
        mock.side_effect = [_price_df(closes), _price_df(closes)]
        sig = compute_technicals("FLAT")
        assert sig.vcp is False
        assert sig.ma_reclaim is False
        assert sig.has_signal is False


def test_vcp_detected_when_atr_and_volume_contract():
    # High ATR for first 60 bars, then contracting ATR + volume for last 20
    high_closes = [100.0 + (i % 10) * 2 for i in range(70)]  # volatile
    tight_closes = [110.0 + (i % 2) * 0.5 for i in range(20)]  # tight
    closes = high_closes + tight_closes

    high_vols = [2_000_000.0] * 70
    tight_vols = [500_000.0] * 20
    vols = high_vols + tight_vols

    with patch("signals.technicals.get_price_history") as mock:
        mock.side_effect = [
            _price_df(closes, vols),
            _price_df([400.0] * len(closes)),
        ]
        sig = compute_technicals("VCP_STOCK")
        assert sig.vcp is True
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_technicals.py -v
```

Expected: `ImportError: No module named 'signals.technicals'`

- [ ] **Step 5.3: Implement signals/technicals.py**

```python
from dataclasses import dataclass
import pandas as pd
from data.price import get_price_history


@dataclass
class TechnicalSignal:
    rs_score: float
    vcp: bool
    ma_reclaim: bool

    @property
    def has_signal(self) -> bool:
        return self.vcp or self.ma_reclaim or self.rs_score >= 1.2


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    return pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_technicals(ticker: str) -> TechnicalSignal:
    """Compute RS score, VCP, and MA Reclaim signals for a ticker."""
    df = get_price_history(ticker, days=200)
    spy_df = get_price_history("SPY", days=200)

    # RS Score: 6-month (126 trading day approx) return ratio
    n = min(126, len(df) - 1, len(spy_df) - 1)
    ticker_return = df["Close"].iloc[-1] / df["Close"].iloc[-(n + 1)]
    spy_return = spy_df["Close"].iloc[-1] / spy_df["Close"].iloc[-(n + 1)]
    rs_score = ticker_return / spy_return if spy_return != 0 else 0.0

    # VCP: recent 20-bar ATR < 70% of 60-bar ATR, and recent volume contracting
    tr = _true_range(df)
    atr_20 = tr.tail(20).mean()
    atr_60 = tr.tail(60).mean()
    vol_20 = df["Volume"].tail(20).mean()
    vol_60 = df["Volume"].tail(60).mean()
    vcp = bool((atr_20 < atr_60 * 0.70) and (vol_20 < vol_60 * 0.70))

    # MA Reclaim: yesterday close < 21-EMA, today close > 21-EMA
    ema21 = _ema(df["Close"], 21)
    ma_reclaim = bool(
        df["Close"].iloc[-2] < ema21.iloc[-2]
        and df["Close"].iloc[-1] > ema21.iloc[-1]
    )

    return TechnicalSignal(rs_score=rs_score, vcp=vcp, ma_reclaim=ma_reclaim)
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_technicals.py -v
```

Expected: 4 PASSED

- [ ] **Step 5.5: Create scripts/test_vcp.py**

```python
#!/usr/bin/env python3
"""Validate technical signal computation. Run: python scripts/test_vcp.py [TICKER]"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
from signals.technicals import compute_technicals

print(f"\n{ticker} 技术信号:")
sig = compute_technicals(ticker)
print(f"  RS Score    : {sig.rs_score:.2f}  {'✅ 强势 (≥1.2)' if sig.rs_score >= 1.2 else '—'}")
print(f"  VCP         : {'✅ 收缩形态' if sig.vcp else '—'}")
print(f"  MA Reclaim  : {'✅ 穿越' if sig.ma_reclaim else '—'}")
print(f"  Has Signal  : {'✅ 是' if sig.has_signal else '否'}")
```

- [ ] **Step 5.6: Commit**

```bash
git add signals/technicals.py tests/test_technicals.py scripts/test_vcp.py
git commit -m "feat: add technical signals (RS/VCP/MA-reclaim) to signals layer"
```

---

## Task 6: Daily Scan Orchestrator

**Files:**
- Create: `ops/daily_scan.py`

Cron schedule: `0 21 * * 1-5` (21:00 Beijing, Mon-Fri — post-market for US Eastern time)

Flow:
1. Load watchlist from WATCHLIST_PATH
2. `get_market_condition()` — if "red", skip individual scans
3. For each ticker: `compute_technicals()` — if `has_signal`, push to `#trade-signals`
4. Always push daily summary to `#daily-scan`
5. Write `data/daily_scan.json` for audit trail

- [ ] **Step 6.1: Implement ops/daily_scan.py**

```python
#!/usr/bin/env python3
"""Daily technical scan: market gate → watchlist signals → Discord notifications.
Cron: 0 21 * * 1-5 (21:00 Beijing time, Mon–Fri)
"""
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/daily_scan.log"),
    ],
)
log = logging.getLogger(__name__)


def _load_watchlist(path: str) -> list[str]:
    text = Path(path).read_text()
    tickers, in_block = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if in_block:
            t = line.strip().upper()
            if t and not t.startswith("#"):
                tickers.append(t)
    return tickers


def run() -> None:
    from signals.market import get_market_condition
    from signals.technicals import compute_technicals
    from notify.discord import DiscordClient, DiscordChannel
    from notify.templates import signal_alert_embed, daily_summary_embed

    tickers = _load_watchlist(os.environ["WATCHLIST_PATH"])
    log.info(f"Scanning {len(tickers)} tickers: {tickers}")

    market = get_market_condition()
    log.info(f"Market: {market.status.upper()} | VIX {market.vix:.1f} | SPY>200MA {market.spy_above_200ma}")

    client = DiscordClient.from_env()
    candidates = []

    if market.status == "red":
        log.warning("Market RED — skipping individual scans")
    else:
        for ticker in tickers:
            try:
                sig = compute_technicals(ticker)
                if sig.has_signal:
                    fired = []
                    if sig.vcp:
                        fired.append("VCP")
                    if sig.ma_reclaim:
                        fired.append("MA Reclaim")
                    if sig.rs_score >= 1.2:
                        fired.append(f"RS {sig.rs_score:.2f}")
                    candidates.append({"ticker": ticker, "signals": fired})
                    client.send(
                        DiscordChannel.SIGNALS,
                        signal_alert_embed(ticker, sig.rs_score, sig.vcp, sig.ma_reclaim, market.status),
                    )
                    log.info(f"{ticker}: fired {fired}")
                else:
                    log.info(f"{ticker}: no signal (RS {sig.rs_score:.2f})")
            except Exception as exc:
                log.error(f"{ticker}: error — {exc}")

    client.send(
        DiscordChannel.DAILY,
        daily_summary_embed(market.status, market.vix, candidates),
    )
    log.info(f"Scan complete. {len(candidates)} candidates sent to #trade-signals.")

    Path("data").mkdir(exist_ok=True)
    Path("data/daily_scan.json").write_text(
        json.dumps(
            {"date": date.today().isoformat(), "market": market.status, "candidates": candidates},
            indent=2,
        )
    )


if __name__ == "__main__":
    run()
```

- [ ] **Step 6.2: Test by running**

```bash
python ops/daily_scan.py
```

Expected: log output showing market status + per-ticker scan results + `✅ Scan complete`. Discord `#daily-scan` receives a summary embed.

- [ ] **Step 6.3: Commit**

```bash
git add ops/daily_scan.py
git commit -m "feat: add daily scan orchestrator (market gate + technicals + Discord)"
```

---

## Task 7: Wire Discord into Earnings Monitor

**Files:**
- Modify: `ops/earnings_monitor.py`

After `output_json.write_text(...)` in the `run()` function, push each result to `#earnings-alerts`.

- [ ] **Step 7.1: Add Discord push to ops/earnings_monitor.py**

Locate the block in `run()` that writes `output_json`. Immediately after it, add:

```python
    # Push to Discord #earnings-alerts (non-fatal if Discord unavailable)
    try:
        from notify.discord import DiscordClient, DiscordChannel
        from notify.templates import earnings_alert_embed
        client = DiscordClient.from_env()
        for item in results:
            payload = earnings_alert_embed(
                ticker=item["ticker"],
                earnings_date=item["earnings_date"],
                direction="Watch",
                eps_beat="(pending Claude analysis)",
                revenue_beat="(pending Claude analysis)",
                guidance="(pending Claude analysis)",
                confidence=0,
                highlights=["8-K 已下载，等待 Phase 3 Claude 分析引擎"],
            )
            client.send(DiscordChannel.EARNINGS, payload)
            log.info(f"Discord #earnings-alerts sent for {item['ticker']}")
    except Exception as exc:
        log.warning(f"Discord notification skipped: {exc}")
```

- [ ] **Step 7.2: Verify earnings monitor still runs without Discord env vars**

```bash
python ops/earnings_monitor.py --dry-run
```

Expected: completes without crash (Discord block is wrapped in try/except so missing env vars are non-fatal).

- [ ] **Step 7.3: Commit**

```bash
git add ops/earnings_monitor.py
git commit -m "feat: wire Discord #earnings-alerts into earnings monitor (non-fatal)"
```

---

## Task 8: Run Full Test Suite

- [ ] **Step 8.1: Install pytest if not already installed**

```bash
pip install pytest
```

- [ ] **Step 8.2: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected output:
```
tests/test_discord.py::test_send_earnings_calls_correct_webhook PASSED
tests/test_discord.py::test_send_raises_on_non_204 PASSED
tests/test_discord.py::test_send_signals_calls_signals_webhook PASSED
tests/test_market.py::test_green_when_spy_bull_and_low_vix PASSED
tests/test_market.py::test_red_when_vix_above_30 PASSED
tests/test_market.py::test_yellow_when_spy_below_200ma PASSED
tests/test_market.py::test_yellow_when_vix_between_20_and_30 PASSED
tests/test_price.py::test_get_price_history_returns_dataframe PASSED
tests/test_price.py::test_get_price_history_raises_on_empty PASSED
tests/test_price.py::test_get_price_history_returns_correct_columns PASSED
tests/test_technicals.py::test_rs_score_above_1_when_ticker_outperforms_spy PASSED
tests/test_technicals.py::test_ma_reclaim_detected_when_price_crosses_21ema PASSED
tests/test_technicals.py::test_no_signal_on_flat_price PASSED
tests/test_technicals.py::test_vcp_detected_when_atr_and_volume_contract PASSED

14 passed
```

- [ ] **Step 8.3: Commit final state**

```bash
git add .
git commit -m "test: all 14 unit tests passing for Phase 2"
```

---

## Phase 3 Roadmap (Future Plan)

Phase 3 will be planned in a separate document once Phase 2 is running end-to-end.

| Task | File | Description |
|------|------|-------------|
| 3.1 | `data/financials.py` | 8-quarter EPS/Revenue/Margins via yfinance |
| 3.2 | `signals/fundamentals.py` | EPS acceleration score, ROE trend, FCF margin |
| 3.3 | `engine/scorer.py` | Weighted aggregation: earnings 40% + technicals 35% + fundamentals 25% |
| 3.4 | `engine/claude_client.py` | Structured Claude API call for narrative analysis |
| 3.5 | `engine/prompts.py` | Analysis prompt templates |
| 3.6 | Update `ops/earnings_monitor.py` | Full direction + confidence from engine |
| 3.7 | `data/db.py` | SQLite historical signal accuracy tracking |

## Scheduled Tasks Summary (Phase 2)

| Task | Cron | 北京时间 | 功能 |
|------|------|---------|------|
| `earnings-monitor` | `3 6 * * 1-5` | 06:03 Mon-Fri | 财报检测 + 8-K 下载 + #earnings-alerts |
| `daily-scan` | `0 21 * * 1-5` | 21:00 Mon-Fri | 技术面扫描 + #trade-signals + #daily-scan |
