from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Callable

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{doc}"
Getter = Callable[..., tuple[dict[str, Any] | None, dict[str, Any]]]


def _download_document(url: str, dest: Path, *, headers: dict[str, str]) -> Path:
    import requests

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


class SecEdgarDownloader:
    def __init__(self, *, getter: Getter | None = None, cache_dir: Path | None = None):
        if getter is None:
            from investment_assistant.data import http

            getter = http.get_json
        self._get = getter
        self._cache_dir = Path(cache_dir) if cache_dir else None

    def _headers(self, ua: str) -> dict[str, str]:
        return {"User-Agent": ua}

    def _resolve_cik(self, ticker: str, ua: str) -> str | None:
        data: dict[str, Any] | None = None
        cache = (self._cache_dir / "company_tickers.json") if self._cache_dir else None
        if cache and cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
        else:
            data, status = self._get(COMPANY_TICKERS_URL, headers=self._headers(ua))
            if status["ok"] and data and cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(data), encoding="utf-8")
        if not data:
            return None
        target = ticker.strip().upper()
        for entry in data.values():
            if str(entry.get("ticker", "")).upper() == target:
                return f"{int(entry['cik_str']):010d}"
        return None

    def download_filings_batch(
        self, ticker: str, form_types: list[str], since_date: date, output_base: Path
    ) -> list[Path]:
        ua = os.environ.get("SEC_USER_AGENT")
        if not ua:
            return []  # 优雅降级：无 UA 不下载
        cik = self._resolve_cik(ticker, ua)
        if not cik:
            return []
        payload, status = self._get(SUBMISSIONS_URL.format(cik=cik), headers=self._headers(ua))
        if not status["ok"] or not payload:
            return []
        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accns = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        target_day = since_date.isoformat()
        out: list[Path] = []
        for i, form in enumerate(forms):
            if form not in form_types or str(dates[i]) != target_day:
                continue
            accession = accns[i]
            doc = docs[i] if i < len(docs) and docs[i] else f"{accession}.txt"
            dest = Path(output_base) / ticker.upper() / form / f"{accession}-{Path(doc).name}"
            url = ARCHIVE_DOC_URL.format(
                cik_int=int(cik), accession_nodash=accession.replace("-", ""), doc=doc
            )
            out.append(_download_document(url, dest, headers=self._headers(ua)))
        return out
