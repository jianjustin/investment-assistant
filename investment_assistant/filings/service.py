from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from investment_assistant.config import FilingsConfig


class FilingDownloader(Protocol):
    def download_filings_batch(
        self, ticker: str, form_types: list[str], since_date: date, output_base: Path
    ) -> list[Path]:
        ...


def _default_downloader() -> FilingDownloader:
    from investment_assistant.filings.sec_downloader import SecEdgarDownloader

    return SecEdgarDownloader()


def download_configured_filings(
    tickers: list[str],
    cfg: FilingsConfig,
    *,
    downloader: FilingDownloader | None = None,
    since_date: date | None = None,
) -> dict[str, Any]:
    dl = downloader or _default_downloader()
    when = since_date or (date.today() - timedelta(days=1))  # 默认昨日 T-1
    files: list[Path] = []
    errors: dict[str, str] = {}
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        if not ticker:
            continue
        try:
            files.extend(dl.download_filings_batch(ticker, list(cfg.forms), when, cfg.output_dir))
        except Exception as exc:  # 单标的失败不影响其余
            errors[ticker] = str(exc)
    return {"downloaded_count": len(files), "files": files, "errors": errors}
