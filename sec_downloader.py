"""
SEC EDGAR 下载器
负责：Ticker → CIK 映射、查找最新 8-K、下载 Exhibit 99.1（财报新闻稿）
"""

import requests
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
CIK_LOOKUP_URL = "https://www.sec.gov/files/company_tickers.json"


class SECDownloader:
    def __init__(self, user_agent: str):
        """
        user_agent 格式：'名字 邮箱'，EDGAR 要求必填，否则限速。
        """
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            # 注意：不设置 Host，让 requests 按目标 URL 自动填充
        })
        self._cik_map: dict[str, str] = {}  # ticker → CIK (10位，补零)

    # ── CIK 查找 ──────────────────────────────────────────────────────────

    def _load_cik_map(self) -> None:
        """从 SEC 官方 JSON 加载全量 ticker→CIK 映射（约 12,000 家公司）。"""
        if self._cik_map:
            return
        logger.info("Loading CIK map from SEC...")
        headers = {"User-Agent": self.session.headers["User-Agent"]}
        resp = requests.get(CIK_LOOKUP_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        for entry in raw.values():
            ticker = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if ticker:
                self._cik_map[ticker] = cik
        logger.info(f"CIK map loaded: {len(self._cik_map)} tickers")

    def get_cik(self, ticker: str) -> Optional[str]:
        """返回 ticker 对应的 10 位补零 CIK，找不到返回 None。"""
        self._load_cik_map()
        cik = self._cik_map.get(ticker.upper())
        if not cik:
            logger.warning(f"CIK not found for: {ticker}")
        return cik

    # ── 8-K 查找 ─────────────────────────────────────────────────────────

    def get_recent_filings(self, cik: str, form_type: str = "8-K", limit: int = 10) -> list[dict]:
        """
        从 EDGAR submissions API 取最近 limit 份指定表单的 filings。
        返回：[{form, date, accession, primaryDocument}, ...]
        """
        url = f"{EDGAR_SUBMISSIONS}/CIK{cik}.json"
        # submissions 端点在 data.sec.gov，需重置 Host 头
        headers = {"User-Agent": self.session.headers["User-Agent"]}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        results = []
        for i, form in enumerate(forms):
            if form == form_type and len(results) < limit:
                results.append({
                    "form": form,
                    "date": dates[i] if i < len(dates) else "",
                    "accession": accessions[i] if i < len(accessions) else "",
                    "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
                })
        return results

    # ── 文件下载 ──────────────────────────────────────────────────────────

    def _get_filing_index(self, cik: str, accession: str) -> list[dict]:
        """
        获取 filing 内所有文件列表。
        路径使用公司注册 CIK（registrant），非报送方 CIK。
        先试 -index.json，再试 -index.htm（解析 HTML 表格）。
        返回：[{name, type, description, path}, ...]
        """
        acc_nodash = accession.replace("-", "")
        reg_cik = int(cik)  # 去掉前导零

        # 1. 尝试 JSON index（不总存在）
        json_url = (
            f"https://www.sec.gov/Archives/edgar/data/{reg_cik}"
            f"/{acc_nodash}/{accession}-index.json"
        )
        try:
            resp = self.session.get(json_url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                docs = data.get("documents", [])
                if docs:
                    logger.info(f"Got filing index (JSON) for {accession}")
                    return docs
        except Exception:
            pass

        # 2. 回退：解析 -index.htm
        htm_url = (
            f"https://www.sec.gov/Archives/edgar/data/{reg_cik}"
            f"/{acc_nodash}/{accession}-index.htm"
        )
        try:
            resp = self.session.get(htm_url, timeout=30)
            if resp.status_code == 200:
                return self._parse_index_htm(resp.text)
        except Exception:
            pass

        logger.warning(f"Could not fetch filing index for {accession} (tried JSON + HTM)")
        return []

    @staticmethod
    def _parse_index_htm(html: str) -> list[dict]:
        """从 EDGAR index.htm 的 <table> 中提取文件列表。"""
        from html.parser import HTMLParser

        class _Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_table = False
                self.rows: list[list[str]] = []
                self._row: list[str] = []
                self._cell = ""
                self._in_cell = False

            def handle_starttag(self, tag, attrs):
                attrs_d = dict(attrs)
                if tag == "table":
                    self.in_table = True
                if self.in_table and tag in ("td", "th"):
                    self._in_cell = True
                    self._cell = ""
                    # capture href if present
                    if tag == "td" and "href" in attrs_d:
                        self._cell = attrs_d["href"]

            def handle_endtag(self, tag):
                if self.in_table and tag in ("td", "th"):
                    self._row.append(self._cell.strip())
                    self._in_cell = False
                elif self.in_table and tag == "tr":
                    if self._row:
                        self.rows.append(self._row)
                    self._row = []
                elif tag == "table":
                    self.in_table = False

            def handle_data(self, data):
                if self._in_cell and not self._cell:
                    self._cell += data

        parser = _Parser()
        parser.feed(html)
        docs = []
        for row in parser.rows:
            if len(row) >= 3:
                # 典型列顺序：序号, 描述, 文件名, 类型, 大小
                name = row[2] if len(row) > 2 else ""
                desc = row[1] if len(row) > 1 else ""
                dtype = row[3] if len(row) > 3 else ""
                if name and not name.lower().startswith("document"):
                    docs.append({"name": name, "description": desc, "type": dtype})
        return docs

    def _pick_best_document(self, documents: list[dict]) -> Optional[dict]:
        """
        优先级：Exhibit 99.1（财报新闻稿）> 8-K 主文件 > 第一个 HTML。
        """
        # 1. 优先找 Exhibit 99.1
        for doc in documents:
            desc = (doc.get("description") or "").lower()
            doc_type = (doc.get("type") or "").lower()
            name = (doc.get("name") or "").lower().replace("-", "").replace("_", "")
            if "99.1" in desc or "ex99" in name or "exhibit99" in name or "99.1" in doc_type:
                return doc

        # 2. 主要 8-K 文档（htm/html）
        for doc in documents:
            if (doc.get("type") or "").upper() == "8-K":
                return doc

        # 3. 兜底：第一个 HTML
        for doc in documents:
            name = (doc.get("name") or "").lower()
            if name.endswith((".htm", ".html")):
                return doc

        return None

    def download_exhibit(
        self,
        cik: str,
        accession: str,
        output_dir: Path,
        primary_document: str = "",
    ) -> Optional[Path]:
        """
        下载指定 filing 的最佳文档（优先 Exhibit 99.1），保存到 output_dir。
        primary_document: submissions API 返回的主文件名，index 失败时作为兜底。
        返回保存路径，失败返回 None。
        """
        # EDGAR 存档路径使用注册方（registrant）CIK，即公司自身 CIK
        reg_cik = int(cik)  # 去掉前导零
        acc_nodash = accession.replace("-", "")

        # ── 尝试读取 index，从中找 Exhibit 99.1 ──────────────────────────
        documents = self._get_filing_index(cik, accession)
        doc_name = ""

        if documents:
            doc = self._pick_best_document(documents)
            if doc:
                doc_name = doc.get("name", "")

        # ── 兜底：直接用 submissions API 的 primaryDocument ───────────────
        if not doc_name:
            if primary_document:
                logger.info(f"Index unavailable for {accession}, using primaryDocument: {primary_document}")
                doc_name = primary_document
            else:
                logger.warning(f"No document found for {accession}")
                return None

        doc_url = f"{SEC_ARCHIVES}/{reg_cik}/{acc_nodash}/{doc_name}"
        ext = Path(doc_name).suffix or ".htm"
        output_path = output_dir / f"{accession}{ext}"

        try:
            time.sleep(0.1)  # EDGAR 礼貌性限速
            resp = self.session.get(doc_url, timeout=60)
            resp.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(resp.content)
            logger.info(f"Downloaded: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Download failed ({doc_url}): {e}")
            return None

    # ── 高级接口 ──────────────────────────────────────────────────────────

    def get_latest_8k_for_earnings(
        self,
        ticker: str,
        earnings_date: str,
        output_base: Path,
    ) -> Optional[Path]:
        """
        查找并下载指定标的在财报日期前后最近的 8-K Exhibit 99.1。
        earnings_date: "YYYY-MM-DD"
        output_base: 存储根目录，实际路径为 output_base/TICKER/
        """
        cik = self.get_cik(ticker)
        if not cik:
            return None

        filings = self.get_recent_filings(cik, form_type="8-K", limit=15)
        if not filings:
            logger.warning(f"No 8-K filings found for {ticker} (CIK {cik})")
            return None

        # 找距 earnings_date 最近（优先当天或之后）的 8-K
        after = [f for f in filings if f["date"] >= earnings_date]
        target = after[0] if after else filings[0]

        logger.info(
            f"{ticker}: using 8-K dated {target['date']} "
            f"(accession {target['accession']})"
        )

        ticker_dir = output_base / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)
        return self.download_exhibit(
            cik,
            target["accession"],
            ticker_dir,
            primary_document=target.get("primaryDocument", ""),
        )
