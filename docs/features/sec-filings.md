# SEC 采集与监控

任务 `filings` 有两种模式：默认是**下载器**，按配置下载前一天的申报；本机开启了 `sec_monitor`，用的是**监控**模式，负责扫描、归档、提取正文事实并发 Discord 通知。工作台另外在每日批处理里读取 SEC 列表，用来补全财报受理时间（见 [每日计划](daily-plan.md)）。

## 下载器

- 实现：`filings/sec_downloader.py` 的 `SecEdgarDownloader.download_filings_batch(ticker, form_types, start_date, end_date, output_base)`，由 `filings/service.py` 的 `download_configured_filings` 编排。
- 需要 `SEC_USER_AGENT`（`名字 邮箱`），未设置时返回空列表，不发请求。
- CIK 通过 `company_tickers.json` 解析为**注册方** CIK。accession 前缀是报送方（Filing Agent）的 CIK，不能直接用来拼归档路径，否则 RKLB 这类由代理报送的公司会 404。
- 落盘路径：`<output_dir>/<TICKER>/<FORM>/<accession>-<primaryDocument>`，同时写入 `filings` 表。
- 单只股票失败记入 `errors`，不影响其他股票。

## 监控（本机启用）

### 运行规则

- 调度：美东周一至周五 20:30（北京时间次日 08:30，冬令时 09:30）。
- 名单：每轮重读私有的 `SEC观察名单.md`，只采集「采集=是」的 ticker。网页上的关注列表不影响这份名单。
- 窗口：从 `sec_monitor.start_date` 一直扫到执行时的美东当日。每轮都重扫整个窗口，这样失败和休眠期间漏掉的部分也能补上。
- 收集范围：10-Q、10-K，以及主文含 Item 2.02 或索引含 EX-99.1 的 8-K（TSLA 不收 10-K）。符合条件的 8-K 同时保存主文和全部 EX-99.1；其他 8-K 只发一条带来源的索引通知。
- 请求：间隔至少 0.21 秒；HTTP 或网络失败就结束本轮，不持续重试。没有完整跑成功之前，不报告「零命中」。
- 通知：用 Bot 身份（`SEC_DISCORD_BOT_TOKEN`）发到 `sec_monitor.discord_channel_id` 指定的频道，不走设置页的 earnings webhook。遵守 Discord 总开关和 `filings` 任务开关；全局渠道切到邮件时，监控停止发 Discord，也不会改发邮件。

### 归档、去重与投递

- 原文目录用 `filings.output_dir`，正文报告目录用 `FILINGS_REPORT_DIR`；既有报告不覆盖。缺数据库或 `FILINGS_REPORT_DIR` 时告警，不会只生成索引就声称完成。
- 去重读取旧的 `_sec_log.jsonl` 和来源库文件名里的 accession。旧日志损坏时本轮失败，不会把它当成空日志处理。
- 状态目录（`sec_monitor.state_dir`）：`state.json`（每条申报和每条通知的状态、消息 ID）、`monitor.lock`（防止手动和定时同时跑）、`evidence/`（SEC 原始响应，按 SHA-256 命名）。
- 投递：发送前先存状态，收到 Discord 消息 ID 才标 `sent`。被明确拒绝的下一轮重试；超时、没有回执或中断的标 `unknown`，不再自动重发，需要人工核对。
- 运行报告 `job_reports` 记录范围、状态、来源覆盖和 `delivery.receipts`。采集失败或投递未确认时任务记为 `error`。

### 正文提取

- 提取营收、毛利、营业利润、利润率和摊薄 EPS，每项带期间、单位、GAAP/non-GAAP 口径、原文位置、SEC URL 和文件 SHA-256。由金额算出的利润率单独标记并附公式。
- 10-K/10-Q：读 Inline XBRL 的封面期间、合并口径 context 和单位，排除分部数据和比较期，季报不混入年初至今的数字；遇到冲突或不认识的单位不猜数。
- 8-K：支持带季度列标题的财报新闻稿表格，能区分 GAAP 与 non-GAAP；Outlook 表格保留原文。只用 MU 的真实 EX-99.1 验证过。
- 指引、业务进展和风险是按规则筛出的原文摘录，不做语义分析，也不给投资判断。提取不出来时写「未自动提取，待核验」。

## 配置

`config/local.json`（本机私有，不入库）：

```json
{
  "filings": {"forms": ["10-Q", "10-K", "8-K"], "output_dir": "/absolute/path"},
  "sec_monitor": {
    "enabled": true,
    "start_date": "2026-10-01",
    "watchlist_path": "/absolute/path/SEC观察名单.md",
    "legacy_log_path": "/absolute/path/_sec_log.jsonl",
    "state_dir": "/absolute/path/sec-monitor",
    "discord_channel_id": "<频道 ID>"
  }
}
```

改配置后重启服务；名单内容每轮都会重读，改名单不用重启。

## 入口与验证

- 手动运行（会真的发通知，遵守开关和去重）：

  ```bash
  .venv/bin/python -m investment_assistant.tasks.filings
  ```

  ```bash
  .venv/bin/python -m investment_assistant.tasks.filings --from 2026-10-01 --to 2026-10-15
  ```

- 页面：「工具 → 任务中心」运行或暂停 `filings`；「工具 → 运行记录」查看结果；「数据 → 财报」浏览已下载的文件。
- API：`GET /api/filings/records`、`GET /api/filings/records/{id}/download`。
- 验证：同一窗口连续跑两次，第二次新增下载为 0，通知事件和消息 ID 不变，既有报告的 SHA-256 不变。

## 已知限制

- 8-K 新闻稿表格的版式只覆盖了已验证过的样式。
- 本地文件存在，不代表 OneDrive 已完成云端同步。
- 2026-10-16 首次切换时出现过一次 SEC TLS 失败，根因未确认。代码现在能区分证书、TLS、代理、连接重置和超时这几类错误。
