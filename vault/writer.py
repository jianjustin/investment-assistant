"""
Vault Writer
负责：将财报分析结果写入 Obsidian Vault，更新 watchlist 状态
"""

import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class VaultWriter:
    def __init__(self, vault_path: str):
        self.vault = Path(vault_path)
        self.earnings_dir = self.vault / "04-知识" / "投资" / "财报分析"
        self.earnings_dir.mkdir(parents=True, exist_ok=True)
        self.watchlist_status = self.vault / "03-领域" / "投资" / "watchlist-状态.md"

    # ── 财报分析笔记 ──────────────────────────────────────────────────────

    def write_earnings_note(
        self,
        ticker: str,
        earnings_date: str,
        analysis: dict,
        raw_data: dict,
        doc_path: Optional[Path] = None,
    ) -> Path:
        """
        将 Claude 分析结果 + 原始数据写成 Obsidian Markdown 笔记。
        analysis 字段：headline, highlights(list), risks(list),
                       direction, target_price_range, confidence, confidence_reason
        raw_data 字段：actual_eps, estimated_eps, eps_surprise_pct,
                       actual_revenue, estimated_revenue, revenue_surprise_pct,
                       yoy_revenue_growth, next_guidance
        """
        date_compact = earnings_date.replace("-", "")
        quarter = self._infer_quarter(earnings_date)
        headline = analysis.get("headline", "（待分析）")
        direction = analysis.get("direction", "观望")
        target = analysis.get("target_price_range", "待观察")
        confidence = analysis.get("confidence", "?")
        conf_reason = analysis.get("confidence_reason", "")

        highlights = analysis.get("highlights", [])
        risks = analysis.get("risks", [])

        actual_eps = raw_data.get("actual_eps", "N/A")
        est_eps = raw_data.get("estimated_eps", "N/A")
        eps_diff = raw_data.get("eps_surprise_pct", "N/A")
        actual_rev = raw_data.get("actual_revenue", "N/A")
        est_rev = raw_data.get("estimated_revenue", "N/A")
        rev_diff = raw_data.get("revenue_surprise_pct", "N/A")
        yoy = raw_data.get("yoy_revenue_growth", "N/A")
        guidance = raw_data.get("next_guidance", "暂无")

        # 文件名
        note_name = f"{ticker}-{date_compact}-财报分析.md"
        note_path = self.earnings_dir / note_name

        # 来源行
        source_lines = [f"- FMP 数据：财报日期 {earnings_date}"]
        if doc_path:
            rel = self._vault_relative(doc_path)
            source_lines.append(f"- SEC 8-K 原文：[[{rel}]]")

        highlights_md = "\n".join(
            f"{i+1}. {h}" for i, h in enumerate(highlights)
        ) if highlights else "（待分析）"

        risks_md = "\n".join(
            f"{i+1}. {r}" for i, r in enumerate(risks)
        ) if risks else "（待分析）"

        content = f"""---
title: {ticker} {quarter} 财报分析 — {headline}
tags: [财报, {ticker}, {quarter}]
created: {date.today().isoformat()}
---

# {ticker} {quarter} 财报分析 — {headline}

> AI 推断，待用户验证。

## 核心数字

| 指标 | 实际 | 预期 | 差异 |
|---|---|---|---|
| EPS | {actual_eps} | {est_eps} | {eps_diff} |
| 营收 | {actual_rev} | {est_rev} | {rev_diff} |
| 同比增速 | {yoy} | — | — |

## 管理层指引

{guidance}

## 亮点

{highlights_md}

## 风险点

{risks_md}

## 交易建议

- **方向**：{direction}
- **目标价**：{target}
- **置信度**：{confidence}/5
- **原因**：{conf_reason}

## 来源

{chr(10).join(source_lines)}
"""

        note_path.write_text(content, encoding="utf-8")
        logger.info(f"Vault note written: {note_path}")
        return note_path

    # ── watchlist 状态更新 ────────────────────────────────────────────────

    def update_watchlist_status(
        self,
        ticker: str,
        direction: str,
        earnings_date: str,
        note_path: Path,
    ) -> None:
        """
        更新（或创建）03-领域/投资/watchlist-状态.md 中对应行的状态。
        """
        self.watchlist_status.parent.mkdir(parents=True, exist_ok=True)
        note_link = f"[[04-知识/投资/财报分析/{note_path.name}]]"
        new_row = f"| {ticker} | {direction} | {earnings_date} | {note_link} |"

        if not self.watchlist_status.exists():
            self._create_watchlist_status(ticker, direction, earnings_date, note_link)
            return

        content = self.watchlist_status.read_text(encoding="utf-8")

        # 如果该 ticker 行已存在，替换
        pattern = re.compile(rf"^\| {re.escape(ticker)} \|.*$", re.MULTILINE)
        if pattern.search(content):
            updated = pattern.sub(new_row, content)
        else:
            # 追加到表格末尾（找到最后一个表格行）
            lines = content.splitlines()
            insert_idx = len(lines)
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].startswith("|"):
                    insert_idx = i + 1
                    break
            lines.insert(insert_idx, new_row)
            updated = "\n".join(lines)

        self.watchlist_status.write_text(updated, encoding="utf-8")
        logger.info(f"watchlist-状态.md updated for {ticker}: {direction}")

    def _create_watchlist_status(
        self, ticker: str, direction: str, earnings_date: str, note_link: str
    ) -> None:
        content = f"""---
title: Watchlist 状态
tags: [watchlist, 投资, 交易Agent]
created: {date.today().isoformat()}
---

# Watchlist 状态

由 `earnings_monitor.py` 自动维护，每次财报后更新。

| 标的 | 当前方向 | 最后财报日 | 最后分析 |
|---|---|---|---|
| {ticker} | {direction} | {earnings_date} | {note_link} |
"""
        self.watchlist_status.write_text(content, encoding="utf-8")
        logger.info(f"Created watchlist-状态.md")

    # ── 工具方法 ──────────────────────────────────────────────────────────

    def _vault_relative(self, path: Path) -> str:
        """将绝对路径转为相对 Vault 的路径（用于 Obsidian 双链）。"""
        try:
            return str(path.relative_to(self.vault))
        except ValueError:
            return str(path)

    @staticmethod
    def _infer_quarter(date_str: str) -> str:
        """从财报日期推断财季（如 2026Q1）。"""
        try:
            y, m, _ = date_str.split("-")
            q = (int(m) - 1) // 3 + 1
            return f"{y}Q{q}"
        except Exception:
            return "未知季度"
