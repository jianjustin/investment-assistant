# SEC EDGAR 下载器（`sec_downloader.py`）

从 SEC EDGAR 拉取美股上市公司公告（8-K、10-Q、10-K 等）并落盘。

模块入口：[investment_assistant/filings/sec_downloader.py](../investment_assistant/filings/sec_downloader.py) 中的 `SecEdgarDownloader` 类。

---

## 工作流程

```
ticker (如 "AAPL")
   │
   ├─ _resolve_cik(ticker, ua)   → CIK（10 位补零，如 "0000320193"，内部私有）
   │
   └─ download_filings_batch(ticker, form_types, since_date, output_base)
          → 按 since_date（当天）+ form_types 过滤，下载 primaryDocument
          → 返回落盘文件路径列表 list[Path]
```

`download_filings_batch` 是唯一公开方法。CIK 解析在方法内部完成，调用方无需单独处理。

---

## 前置条件

SEC EDGAR 要求请求头包含 `User-Agent: <名字> <邮箱>`。本项目通过环境变量 `SEC_USER_AGENT` 注入——**无需在构造函数传参**：

```env
# .env
SEC_USER_AGENT=YourName your@email.com
```

**未设置 `SEC_USER_AGENT` 时**，`download_filings_batch` 直接返回空列表（`[]`），静默跳过下载，不抛异常、不发请求。

详见 [getting-started.md](./getting-started.md)。

---

## API 速查

| 方法 | 入参 | 返回 | 说明 |
| --- | --- | --- | --- |
| `SecEdgarDownloader(*, getter=None, cache_dir=None)` | `getter`：可注入的 HTTP 函数（测试用）；`cache_dir`：`company_tickers.json` 缓存目录 | 实例 | 构造函数为 keyword-only 参数；生产环境不需要传任何参数 |
| `download_filings_batch(ticker, form_types, since_date, output_base)` | `ticker: str`；`form_types: list[str]`（如 `["8-K", "10-Q"]`）；`since_date: date`（仅下载该日期当天 filed 的记录）；`output_base: Path` | `list[Path]` | 返回所有成功落盘的文件路径；UA 未设或 CIK 解析失败时返回 `[]` |

落盘路径规则：

```
<output_base>/<TICKER>/<FORM>/<accession>-<primaryDocument>
```

例如：`/srv/filings/AAPL/8-K/0000320193-26-000056-form8-k.htm`

---

## 手动触发入口

```bash
# 下载今日（或 T-1）watchlist 所有公司的配置表单
python -m investment_assistant.tasks.filings
```

该命令通过 `investment_assistant/filings/service.py` 的 `download_configured_filings(...)` 编排，`since_date` 默认为昨日（`date.today() - timedelta(days=1)`），表单类型来自配置文件 `FilingsConfig.forms`。

---

## 示例：下载指定日期的 8-K

```python
from datetime import date
from pathlib import Path
from investment_assistant.filings.sec_downloader import SecEdgarDownloader

# SEC_USER_AGENT 已在环境变量中设置（或通过 .env 加载）
sec = SecEdgarDownloader()

paths = sec.download_filings_batch(
    ticker="AAPL",
    form_types=["8-K"],
    since_date=date(2026, 5, 1),      # 仅下载该日当天 filed 的记录
    output_base=Path("/tmp/sec-cache"),
)

for p in paths:
    print(p)
# 输出示例：/tmp/sec-cache/AAPL/8-K/0000320193-26-000056-form8-k.htm
```

**注意**：`since_date` 过滤的是 EDGAR 记录的 `filingDate`（当天精确匹配），不支持日期范围。如需拉取某时间段内的多份 filing，请循环多个日期调用。

---

## 测试注入（offline mock）

测试中可通过 `getter=` 参数注入 mock，无需真实 HTTP 请求：

```python
def mock_getter(url, *, headers=None):
    if "company_tickers" in url:
        return {"0": {"cik_str": "320193", "ticker": "AAPL"}}, {"ok": True}
    return {"filings": {"recent": {"form": [], "filingDate": [], "accessionNumber": [], "primaryDocument": []}}}, {"ok": True}

sec = SecEdgarDownloader(getter=mock_getter)
paths = sec.download_filings_batch("AAPL", ["8-K"], date.today(), Path("/tmp/test"))
assert paths == []  # 无匹配记录时返回空列表
```

---

## 常见问题

**Q: 下载结果为空列表（`[]`）？**
A: 最常见原因：① `SEC_USER_AGENT` 未设置（静默降级）；② `since_date` 当天该 ticker 无对应表单 filed；③ ticker 无法解析为 CIK（可能是 ADR、OTC 或已更名）。可在 https://www.sec.gov/cgi-bin/browse-edgar 手动核查 CIK。

**Q: CIK 找不到？**
A: 该 ticker 可能是 ADR、OTC 或最近变更了代码。到 https://www.sec.gov/cgi-bin/browse-edgar 查证后手动验证。

**Q: 有访问频率限制吗？**
A: EDGAR 公开限制约 10 req/s。当前实现直接发送 `requests.get`，无内建 sleep；生产批量下载时建议在调用层控制并发频率。
