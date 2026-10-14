from __future__ import annotations

from pathlib import Path


def build_filing_report(meta: dict, raw_text: str) -> str:
    """Metadata report. Unknown financial items stay undisclosed."""
    del raw_text  # 第一版不从正文猜测数字
    ticker = meta["ticker"]
    form = meta["form"]
    filing_date = meta["filing_date"]
    accession = meta["accession_number"]
    path = meta["path"]
    return "\n".join([
        "---",
        "type: filing-report",
        f"ticker: {ticker}",
        f"form: {form}",
        f"filing_date: {filing_date}",
        f"accession: {accession}",
        "---",
        "",
        f"# {ticker} {form} {filing_date}",
        "",
        "本报告只记录已下载文件的索引事实。财务数字未从正文自动提取。",
        "",
        "## 来源",
        "",
        f"- 表格：{form}",
        f"- 申报日期：{filing_date}",
        f"- accession：{accession}",
        f"- 原文：{path}",
        "",
        "## 事实",
        "",
        "- 营收：未披露",
        "- 毛利率：未披露",
        "- 指引：未披露",
        "",
        "## 推断",
        "",
        "无。",
        "",
    ])


def report_path(report_dir: Path, meta: dict) -> Path:
    name = f"{meta['form']}_{meta['filing_date']}_{meta['accession_number']}-整理.md"
    return Path(report_dir) / meta["ticker"] / name


def write_filing_report(report_dir: Path, meta: dict, raw_text: str) -> Path | None:
    dest = report_path(report_dir, meta)
    if dest.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(build_filing_report(meta, raw_text), encoding="utf-8")
    return dest
