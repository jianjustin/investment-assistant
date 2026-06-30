# SEC EDGAR 下载器（`sec_downloader.py`）

负责从 SEC EDGAR 拉取美股上市公司的 **8-K 表单及其 Exhibit 99.1**（财报新闻稿）。

模块入口：[investment_assistant/filings/sec_downloader.py](../investment_assistant/filings/sec_downloader.py) 中的 `SecEdgarDownloader` 类。

---

## 工作流程

```
ticker (如 "AAPL")
   │
   ├─ get_cik()              → CIK (10 位补零，如 "0000320193")
   │
   ├─ get_recent_filings()   → 最近 N 份 8-K filings 列表
   │
   └─ download_exhibit()     → 下载该 filing 的最佳文档（优先 Ex 99.1）
                               保存到 output_dir/{accession}.{htm,html,…}
```

`get_latest_8k_for_earnings()` 是上述三步的高级封装，针对"给定一个财报日，下载对应的 8-K"。

---

## 前置条件

EDGAR 要求请求头里带 `User-Agent: <名字> <邮箱>`，否则会被限速或返回 403：

```python
sec = SecEdgarDownloader(user_agent="Your Name your@email.com")
```

在本项目里通过 `.env` 的 `SEC_USER_AGENT` 注入，详见 [getting-started.md](./getting-started.md)。

---

## API 速查

| 方法 | 入参 | 返回 | 说明 |
| --- | --- | --- | --- |
| `get_cik(ticker)` | `str` | `str \| None` | Ticker → 10 位补零 CIK。首次调用会拉取 SEC 全量映射（约 12,000 家公司），后续走内存缓存。 |
| `get_recent_filings(cik, form_type="8-K", limit=10)` | CIK、表单类型、上限 | `list[dict]` | 返回 `[{form, date, accession, primaryDocument}, …]`，按 EDGAR 倒序（最新在前）。 |
| `download_exhibit(cik, accession, output_dir, primary_document="")` | filing 标识 + 落盘目录 | `Path \| None` | 下载该 filing 的最佳文档：优先 Exhibit 99.1，其次 8-K 主文件，再次第一个 HTML。文件名为 `{accession}{ext}`。 |
| `get_latest_8k_for_earnings(ticker, earnings_date, output_base)` | 标的、`YYYY-MM-DD`、根目录 | `Path \| None` | 找距 `earnings_date` 最近（优先当天或之后）的 8-K，下载到 `output_base/TICKER/`。 |

> ⚠️ 关于"5 年财报"：EDGAR `submissions/CIK*.json` 的 `filings.recent` 段大约覆盖**最近 1,000 份**或最近 ~1 年的 filings，5 年 8-K（≈ 20-40 份）通常能全部包含；如不够，需要再去解析 `filings.files[]` 里指向的历史分片 JSON——`SecEdgarDownloader` **暂未实现**这一步，所以下面的示例假定 5 年内的 8-K 都在 `recent` 段里。绝大多数活跃上市公司满足这一条件。

---

## 示例 1：拉取某美股标的过去 5 年的财报

> 目标：下载 AAPL 最近 5 年内所有"带 Exhibit 99.1 的 8-K"（即财报发布日的 8-K）。

```python
# examples/pull_5y_earnings.py
import os
import logging
from pathlib import Path
from datetime import date, timedelta
from dotenv import load_dotenv

from investment_assistant.filings.sec_downloader import SecEdgarDownloader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
load_dotenv()

TICKER = "AAPL"
OUTPUT_DIR = Path("./data/earnings") / TICKER
CUTOFF = (date.today() - timedelta(days=365 * 5)).isoformat()  # 5 年前那天

sec = SecEdgarDownloader(user_agent=os.environ["SEC_USER_AGENT"])

# 1) Ticker → CIK
cik = sec.get_cik(TICKER)
assert cik, f"CIK not found for {TICKER}"

# 2) 拉取近期 8-K（拉多一点确保覆盖 5 年）
#    一家公司每年 4 次财报 + 若干临时披露，limit=80 足够覆盖 5 年。
filings = sec.get_recent_filings(cik, form_type="8-K", limit=80)

# 3) 按日期过滤到 5 年内
recent_5y = [f for f in filings if f["date"] >= CUTOFF]
print(f"{TICKER}: {len(recent_5y)} 8-K filings in the last 5 years")

# 4) 逐份下载（download_exhibit 内部会优先挑 Exhibit 99.1）
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
for f in recent_5y:
    path = sec.download_exhibit(
        cik=cik,
        accession=f["accession"],
        output_dir=OUTPUT_DIR,
        primary_document=f["primaryDocument"],
    )
    print(f"  {f['date']}  {f['accession']}  →  {path}")
```

运行：

```bash
python examples/pull_5y_earnings.py
```

输出示例：

```
AAPL: 23 8-K filings in the last 5 years
  2026-05-01  0000320193-26-000056  →  data/earnings/AAPL/0000320193-26-000056.htm
  2026-01-30  0000320193-26-000013  →  data/earnings/AAPL/0000320193-26-000013.htm
  …
```

> 💡 如果只想要"财报"而非全部 8-K，可在过滤步加一层："下载完成后丢弃文件大小 < 30 KB 的"，或在 `_pick_best_document` 未命中 Exhibit 99.1 时跳过。当前实现是**有就下、没有就拿主文件兜底**。

---

## 示例 2：将拉取的财报下载到指定位置

> 目标：把财报落到自定义目录，例如 Obsidian vault 的附件区。

```python
# examples/download_to_vault.py
import os
from pathlib import Path
from dotenv import load_dotenv

from investment_assistant.filings.sec_downloader import SecEdgarDownloader

load_dotenv()

TICKER = "NVDA"
EARNINGS_DATE = "2026-02-20"

# 任意可写目录都行——脚本会自动 mkdir
TARGET = Path.home() / "Obsidian" / "investment-vault" / "attachments" / "earnings"

sec = SecEdgarDownloader(user_agent=os.environ["SEC_USER_AGENT"])

# 用高级接口：自动选距 EARNINGS_DATE 最近的 8-K，落到 TARGET/NVDA/
path = sec.get_latest_8k_for_earnings(
    ticker=TICKER,
    earnings_date=EARNINGS_DATE,
    output_base=TARGET,
)

print(f"Saved to: {path}")
# → Saved to: /Users/you/Obsidian/investment-vault/attachments/earnings/NVDA/0001045810-26-000023.htm
```

也可以走底层 API 更精细地控制落盘路径：

```python
cik = sec.get_cik("NVDA")
filings = sec.get_recent_filings(cik, form_type="8-K", limit=5)
target = filings[0]  # 最新一份

custom_dir = Path("/tmp/sec-cache/2026-Q4")
path = sec.download_exhibit(
    cik=cik,
    accession=target["accession"],
    output_dir=custom_dir,
    primary_document=target["primaryDocument"],
)
# → /tmp/sec-cache/2026-Q4/0001045810-26-000023.htm
```

落盘命名规则：`{accession}{原文件后缀}`，例如 `0001045810-26-000023.htm`。

---

## 常见问题

**Q: 报 403 Forbidden？**
A: `SEC_USER_AGENT` 没设或格式不对。必须是 `名字 邮箱` 两段，例如 `Jane Doe jane@example.com`。

**Q: CIK 找不到？**
A: 该 ticker 可能是 ADR、OTC、或最近变更过代码。手动到 https://www.sec.gov/cgi-bin/browse-edgar 查证。

**Q: 下载下来不是 Exhibit 99.1，而是 8-K 主文件？**
A: 说明那份 8-K 不是财报披露（可能是高管变动、收购公告等），没有 Ex 99.1 附件，`_pick_best_document` 会兜底取主文件。需要"只要财报"的话，按上文 💡 提示过滤。

**Q: 限速？**
A: EDGAR 公开限制为 10 req/s。`download_exhibit` 内已 `sleep(0.1)`，正常使用不会触限。
