"""Strict SEC source used by the migrated monitor (no silent empty-on-error)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from lxml import html

ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as stream:
        os.chmod(temp, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def read_watchlist(path: Path) -> list[str]:
    """Only the current authoritative table's 采集=是 rows are in scope."""
    tickers: list[str] = []
    columns = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if "Ticker" in cells and "采集" in cells:
            columns = (cells.index("Ticker"), cells.index("采集"))
            continue
        if columns and len(cells) > max(columns) and cells[columns[1]] == "是":
            ticker = cells[columns[0]].upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker):
                raise ValueError("SEC观察名单包含无效 ticker")
            if ticker not in tickers:
                tickers.append(ticker)
    if not tickers:
        raise ValueError("SEC观察名单没有有效的采集行；未使用缓存名单")
    return tickers


class EdgarSource:
    def __init__(self, evidence_dir: Path, *, session=None):
        self.evidence_dir = evidence_dir
        self.session = session or requests.Session()
        self.last_request = 0.0
        self.evidence: list[dict] = []

    def get(self, url: str) -> bytes:
        ua = os.environ.get("SEC_USER_AGENT", "")
        if "@" not in ua:
            raise ValueError("SEC_USER_AGENT 缺失或没有联系邮箱")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in {"www.sec.gov", "data.sec.gov"}:
            raise ValueError("拒绝非 SEC 来源 URL")
        time.sleep(max(0.0, 0.21 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        try:
            resp = self.session.get(url, headers={"User-Agent": ua}, timeout=30, allow_redirects=False)
        except requests.RequestException as exc:
            # Classify without logging proxy credentials or a complete request exception.
            detail = str(exc).lower()
            reason = "network_error"
            if "certificate_verify_failed" in detail:
                reason = "certificate_validation_failed"
            elif "unexpected_eof" in detail or "eof occurred" in detail:
                reason = "tls_peer_closed"
            elif "connection reset" in detail:
                reason = "connection_reset"
            elif isinstance(exc, requests.exceptions.ProxyError):
                reason = "proxy_unavailable"
            elif isinstance(exc, requests.Timeout):
                reason = "request_timeout"
            raise RuntimeError(f"SEC 请求失败 ({type(exc).__name__}; {reason}): {url}") from None
        if resp.status_code != 200:
            retry = resp.headers.get("Retry-After", "")
            raise RuntimeError(f"SEC HTTP {resp.status_code}; Retry-After={retry or '无'}: {url}")
        content = resp.content
        if not content:
            raise ValueError(f"SEC 返回空正文: {url}")
        digest = hashlib.sha256(content).hexdigest()
        dest = self.evidence_dir / (digest + ".response")
        if not dest.exists():
            atomic_write(dest, content)
        self.evidence.append({"url": url, "sha256": digest, "path": str(dest)})
        return content

    def json(self, url: str) -> dict:
        try:
            result = json.loads(self.get(url))
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"SEC JSON 无效: {url}") from exc
        if not isinstance(result, dict):
            raise ValueError(f"SEC JSON 结构无效: {url}")
        return result

    @staticmethod
    def rows(payload: dict) -> list[dict]:
        keys = ("form", "filingDate", "accessionNumber", "primaryDocument")
        if any(not isinstance(payload.get(k), list) for k in keys):
            raise ValueError("SEC submissions 缺少必需数组")
        count = len(payload["form"])
        if any(len(payload[k]) != count for k in keys):
            raise ValueError("SEC submissions 数组长度不一致")
        return [{k: payload[k][i] for k in keys} for i in range(count)]

    def discover(self, tickers: list[str], start: str, end: str) -> list[dict]:
        mapping = self.json("https://www.sec.gov/files/company_tickers.json")
        cik_by_ticker = {str(x["ticker"]).upper(): int(x["cik_str"]) for x in mapping.values()}
        results: list[dict] = []
        for ticker in tickers:
            if ticker not in cik_by_ticker:
                raise ValueError(f"SEC 未找到 {ticker} 的 CIK")
            cik = cik_by_ticker[ticker]
            data = self.json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
            filings = data.get("filings")
            if not isinstance(filings, dict) or not isinstance(filings.get("files"), list):
                raise ValueError(f"{ticker} submissions 缺少 filings/files")
            rows = self.rows(filings.get("recent", {}))
            for archive in filings["files"]:
                if not all(isinstance(archive.get(k), str) for k in ("filingFrom", "filingTo", "name")):
                    raise ValueError(f"{ticker} 历史 submissions 索引无效")
                if archive["filingFrom"] <= end and archive["filingTo"] >= start:
                    if not re.fullmatch(r"CIK\d+-submissions-\d+\.json", archive["name"]):
                        raise ValueError("SEC 历史文件名无效")
                    rows.extend(self.rows(self.json("https://data.sec.gov/submissions/" + archive["name"])))
            seen: set[str] = set()
            for row in rows:
                form, accession = row["form"], row["accessionNumber"]
                if form not in {"10-Q", "10-K", "8-K"} or not start <= row["filingDate"] <= end:
                    continue
                if ticker == "TSLA" and form == "10-K":
                    continue
                if accession in seen:
                    continue
                seen.add(accession)
                doc = row["primaryDocument"]
                if not ACCESSION.fullmatch(accession) or not re.fullmatch(r"[A-Za-z0-9_.-]+", doc):
                    raise ValueError("SEC accession/主文文件名无效")
                base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
                results.append({
                    "ticker": ticker, "form": form, "filing_date": row["filingDate"],
                    "accession_number": accession, "primary_document": doc,
                    "edgar_url": base + doc, "index_url": base + accession + "-index.html",
                })
        return sorted(results, key=lambda x: (x["filing_date"], x["ticker"], x["accession_number"]))

    def documents(self, meta: dict) -> tuple[bool, list[tuple[str, bytes]]]:
        primary = self.get(meta["edgar_url"])
        documents = [(meta["primary_document"], primary)]
        if meta["form"] != "8-K":
            return True, documents
        page = html.fromstring(self.get(meta["index_url"]))
        tables = page.xpath('//table[contains(@summary,"Document Format Files")]')
        if not tables:
            raise ValueError("SEC 8-K 文件索引缺少 Document Format Files 表格")
        exhibits: list[str] = []
        for row in tables[0].xpath('.//tr'):
            cells = row.xpath('./td')
            if len(cells) >= 4 and cells[3].text_content().strip().upper() == "EX-99.1":
                links = cells[2].xpath('.//a/@href')
                if not links:
                    raise ValueError("SEC EX-99.1 缺少链接")
                url = urljoin(meta["index_url"], links[0])
                # Inline-XBRL links wrap the actual Archives URL.
                if "/ix?doc=" in url or "/ixviewer/doc/action?doc=" in url:
                    from urllib.parse import parse_qs
                    url = urljoin("https://www.sec.gov", parse_qs(urlparse(url).query)["doc"][0])
                if not url.startswith(meta["edgar_url"].rsplit("/", 1)[0] + "/"):
                    raise ValueError("SEC EX-99.1 链接不在本申报目录")
                exhibits.append(url)
        text = " ".join(html.fromstring(primary).text_content().split())
        selected = bool(re.search(r"\bItem\s*2\s*\.\s*02\b", text, re.IGNORECASE) or exhibits)
        if selected:
            for url in dict.fromkeys(exhibits):
                documents.append((Path(urlparse(url).path).name, self.get(url)))
        return selected, documents
