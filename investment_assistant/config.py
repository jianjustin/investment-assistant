from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .runtime_paths import DEFAULT_CONFIG_PATH, DEFAULT_DRAFT_DIR, DEFAULT_FILINGS_DIR, DEFAULT_VAULT_RO


@dataclass(frozen=True)
class MarketConfig:
    spy_ticker: str = "SPY"
    vix_ticker: str = "^VIX"
    ma_days: int = 200
    history_days: int = 300
    yellow_vix: float = 20.0
    red_vix: float = 30.0


@dataclass(frozen=True)
class FilingsConfig:
    forms: list[str] = field(default_factory=lambda: ["10-Q", "10-K"])
    lookback_years: int = 3
    output_dir: Path = DEFAULT_FILINGS_DIR


@dataclass(frozen=True)
class AssistantConfig:
    watchlist: list[str] = field(default_factory=lambda: ["CRDO", "MU", "RKLB", "NVDA"])
    market: MarketConfig = field(default_factory=MarketConfig)
    filings: FilingsConfig = field(default_factory=FilingsConfig)
    vault_ro: Path = DEFAULT_VAULT_RO
    draft_dir: Path = DEFAULT_DRAFT_DIR
    brief_time_local: str = "08:30"
    max_daily_focus_items: int = 3
    model_default: str = "deepseek-v4-pro"


def load_config(path: str | Path | None = None) -> AssistantConfig:
    """Load investment assistant config with runtime-safe defaults."""
    config_path = _resolve_config_path(path)
    data: dict[str, Any] = {}
    if config_path and config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    return _config_from_dict(data)


def _resolve_config_path(path: str | Path | None) -> Path | None:
    if path is not None:
        return Path(path)
    env_path = os.environ.get("INVESTMENT_ASSISTANT_CONFIG")
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_PATH


def _config_from_dict(data: dict[str, Any]) -> AssistantConfig:
    cfg = AssistantConfig()
    if "watchlist" in data:
        cfg = replace(cfg, watchlist=_normalize_tickers(data["watchlist"]))
    if "market" in data:
        cfg = replace(cfg, market=_market_from_dict(data["market"], cfg.market))
    if "filings" in data:
        cfg = replace(cfg, filings=_filings_from_dict(data["filings"], cfg.filings))
    if "vault_ro" in data:
        cfg = replace(cfg, vault_ro=Path(data["vault_ro"]))
    if "draft_dir" in data:
        cfg = replace(cfg, draft_dir=Path(data["draft_dir"]))
    if "brief_time_local" in data:
        cfg = replace(cfg, brief_time_local=str(data["brief_time_local"]))
    if "max_daily_focus_items" in data:
        cfg = replace(cfg, max_daily_focus_items=int(data["max_daily_focus_items"]))
    if "model_default" in data:
        cfg = replace(cfg, model_default=str(data["model_default"]))
    return cfg


def _market_from_dict(data: dict[str, Any], base: MarketConfig) -> MarketConfig:
    allowed = {
        "spy_ticker": str,
        "vix_ticker": str,
        "ma_days": int,
        "history_days": int,
        "yellow_vix": float,
        "red_vix": float,
    }
    values = {}
    for key, caster in allowed.items():
        if key in data:
            values[key] = caster(data[key])
    return replace(base, **values)


def _filings_from_dict(data: dict[str, Any], base: FilingsConfig) -> FilingsConfig:
    values: dict[str, Any] = {}
    if "forms" in data:
        values["forms"] = _normalize_forms(data["forms"])
    if "lookback_years" in data:
        values["lookback_years"] = int(data["lookback_years"])
    if "output_dir" in data:
        values["output_dir"] = Path(data["output_dir"])
    return replace(base, **values)


def _normalize_tickers(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("watchlist must be a list of ticker symbols")
    tickers = [str(item).strip().upper() for item in raw if str(item).strip()]
    if not tickers:
        raise ValueError("watchlist must not be empty")
    return tickers


def _normalize_forms(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("filings.forms must be a list")
    forms = [str(item).strip().upper() for item in raw if str(item).strip()]
    if not forms:
        raise ValueError("filings.forms must not be empty")
    return forms
