# 本地投研工作台接管 SEC 定时采集与 Discord 通知

SEC 监控由当前项目的 `filings` 任务执行，通过已安装的本地 LaunchAgent 随 API 服务运行。OpenClaw 的 SEC 定时任务停用后，采集和发送不需要 OpenClaw 进程。

## 运行规则

- 调度：美东周一至周五 20:30，时区 `America/New_York`。北京时间夏令时为次日 08:30，冬令时为次日 09:30；美国周五对应北京时间周六。
- 每次重新读取正式 `SEC观察名单.md`，只采集表中「采集=是」的 ticker。修改网页关注列表不改变这份 SEC 监控名单。
- 从 `2026-10-01` 起，查到执行时的美东当日，包含两端；读取 submissions 的 recent 及与窗口重叠的历史 files。重复扫描整个窗口以覆盖失败和休眠期间的缺口，不用 ZERO-HIT 推进起点。
- 收集 10-Q、10-K，以及主文包含 Item 2.02 或文件索引含 EX-99.1 的 8-K；TSLA 不收 10-K。符合条件的 8-K 同时保存主文及全部 EX-99.1。其他 8-K 只发送一条带来源的索引通知。
- SEC 请求至少间隔 0.21 秒，保留 User-Agent；HTTP 错误或网络失败结束本轮采集，不持续重试。完整成功前不声称零命中。
- 目标频道为 Discord `investment`，ID `1559080522393587782`。使用现有 Bot 的身份直接调用 Discord API，凭据单独保存在项目 `.env` 的 `SEC_DISCORD_BOT_TOKEN`，文件权限 0600，不在代码或 JSON 配置中存储令牌。
- 遵守通知设置的 Discord 总开关和 `filings` 任务开关。此监控使用固定频道 ID，不使用设置页面的 earnings webhook；切换全局渠道到 email 会停止此监控的 Discord 通知，不会改发邮件。

## 归档与去重

正式原文和报告目录沿用 `config/local.json` 的 `filings.output_dir` 和 `.env` 的 `FILINGS_REPORT_DIR`。不会覆盖既有报告。

监控每次读取旧 `_sec_log.jsonl` 和来源库文件名中的 accession。已知申报不再次下载或推送；旧记录缺少投递确认时保留为待核验，不自动补发。旧日志不可读或损坏会使本轮失败；不把它当成空日志。

新的去重状态、Discord 回执及 SEC 响应证据位于：

```text
~/Library/Application Support/investment-assistant/sec-monitor/
  state.json          # 每条申报的归档状态、每条通知的状态与消息 ID
  monitor.lock        # 单机并发互斥，覆盖手动与定时运行
  evidence/           # SEC 原始响应，按 SHA-256 命名；运行报告保留来源映射
  migration-backup/   # 切换前的私有配置和旧调度记录
```

发送前先保存状态，收到 Discord 消息 ID 后才标记 `sent`。明确拒绝的请求可在下一轮重试；网络超时、无有效回执、进程中断后的 `sending` 记录标记 `unknown`，停止自动重发，需核查 Discord 实际消息后处理。同一天同一窗口的重复运行不会重复发送已确认通知。

`job_reports` 保存范围、运行状态、来源覆盖情况和 `delivery.receipts`。采集失败或投递未确认时任务为 `error`；采集失败但失败通知送达时，两者分别记录为采集失败、投递成功。原文存在不代表投递成功，本地文件也不证明 OneDrive 已完成云端同步。

## 正文提取与报告

新增报告读取已下载的主文和 EX-99.1，提取营收、毛利、营业利润、利润率及摊薄 EPS。每项记录期间、单位、GAAP/non-GAAP 口径、原文位置、SEC URL 与文件 SHA-256。利润率由金额计算时单独标记并列出公式。Discord 通知包含已提取指标、公司指引或业务进展摘录，以及原文和完整报告位置。

- 10-K/10-Q：从 Inline XBRL 的封面期间、合并口径 context 和单位提取当期事实。年报选择年度，季报选择单季；排除分部数据和比较期，季报不混入年初至今数字。存在冲突、未知单位或不支持的转换格式时不猜数值。
- 8-K：支持带 `Quarterly Financial Results`、金额单位和 FQ 季度列标题的财报新闻稿表格，展开合并单元格后区分 GAAP/non-GAAP。Outlook 表格保留表头及原文。已用 MU 的真实 EX-99.1 验证；不代表所有公司的新闻稿版式均已覆盖。
- 指引、业务进展与风险目前是规则筛选的原文摘录，不是全文语义分析，也不生成投资判断。含 EX-99.1 的普通业务公告不会自动当作业绩发布。
- 无法提取时写「未自动提取，待核验」，不把解析缺口写成公司「未披露」。旧报告保留；恢复中断的运行时仍保留已有报告链接。

正式监控必须同时配置数据库和 `FILINGS_REPORT_DIR`；缺失时告警，不能只生成索引却声称完整完成。

## 配置与操作

`config/local.json` 增加 `sec_monitor`：

```json
{
  "enabled": true,
  "start_date": "2026-10-01",
  "watchlist_path": "/absolute/path/SEC观察名单.md",
  "legacy_log_path": "/absolute/path/_sec_log.jsonl",
  "state_dir": "/absolute/path/sec-monitor",
  "discord_channel_id": "1559080522393587782"
}
```

此配置是本机私有配置，不进入 Git。默认未配置 `sec_monitor.enabled` 的其他实例仍使用原有财报下载流程。配置改动后重启本机服务；名单内容则每轮自动重读。

在仓库根目录手动运行（包含实际通知，遵守开关和去重）：

```bash
.venv/bin/python -m investment_assistant.tasks.filings
.venv/bin/python -m investment_assistant.tasks.filings --from 2026-10-01 --to 2026-10-15
```

网页入口为 `http://127.0.0.1:8787/`。使用「工具」查看 `filings` 运行记录，使用定时任务设置暂停该任务。启动方式为 `./start.command`；已运行的用户服务修改配置后可用：

```bash
launchctl kickstart -k gui/$(id -u)/local.investment-assistant
```

首次切换直接为 `scheduled_jobs.filings` 写入美东 20:30 及计算好的未来 `next_run_at`，避免 NULL 导致立即补跑。电脑需要运行并唤醒；休眠恢复后到期任务补跑一次。

## 切换与验证记录

2026-10-16 首次切换试跑时，SEC 在 TLS 连接阶段失败，运行被正确记为 `error`，没有写入新原文或生成虚构零命中结果。失败说明已送至原频道并通过 Discord GET 回读核对；消息 ID 为 `1560484513568522260`。同窗口重复运行复用该回执，没有重复发送失败通知。

同日继续排查时，submissions、申报主文与附件已恢复 HTTP 200，实际 Python 下载成功。未修改全局代理或关闭 TLS 校验，因此不能把恢复归因于代码修复；前次 TLS 异常根因仍未确认。代码现在区分证书校验失败、TLS 对端关闭、代理不可用、连接重置及超时，并避免输出代理凭据。

完整生产运行 `filings-20261016031531-67635399` 检查 8 只观察股、2026-10-01 至 2026-10-15 美东日期窗口，状态为 `success`。新归档 RKLB 的 `0001819994-26-000067` 主文和 EX-99.1，生成正文报告；通知消息 `1560491428671524864` 已经 Discord GET 回读，内容与本地发送记录一致。该公告说明 Neutron 首次发射预计调整至 2027 年，报告将它归为业务事件。

另外从 SEC 实际下载 MU 的 2026-10-09 10-K 和 2026-09-30 8-K/EX-99.1，验证年报 Inline XBRL 与财报新闻稿表格两条提取路径。正式报告目录的 MU 子目录新增两份 `-正文核验.md`，保留旧 `-整理.md`；较早的 8-K 仅用于正文验证，没有扩大正式监控窗口或补发历史通知。验证原文、分析结果和回执位于状态目录的 `verification-2026-10-16/`。

完整 Python 回归为 344 项通过、1 项跳过。测试覆盖源失败、筛选与去重、投递不确定性、断点恢复、季度/年度期间、单位缩放、分部排除、GAAP/non-GAAP、指引表头和报告保留。重启后的服务端读回确认调度线程正常，`filings` 已启用，下次为北京时间 2026-10-17 08:30。

重启后通过网页 API 重跑同一窗口，运行 `filings-20261016032257-6523571d` 再次成功：新增下载为 0，通知事件及消息 ID 未变，96 份既有报告的 SHA-256 全部一致。`filings` 中该 RKLB accession 仅一条记录，下载端点返回的字节与归档原文相同。数据库为本机 `investment_assistant`，网页与正式 SEC 名单的 8 只 ticker 一致。

旧任务 ID 为 `8b59f993-da67-42d0-af51-5f9dcae4c3e0`（`sec-filing-collector`），已停用并读回确认 `enabled=false`。其他 OpenClaw 自动化开关保持原值，旧任务定义保留便于回退。若回退，应先暂停本项目的 `filings` 调度，再恢复私有配置并重启本地服务，最后启用旧任务，避免两个调度器同时通知。

## 来源

- 原 OpenClaw `sec-filing-collector` 任务的实际配置及 `workspace-investment-research/skills/sec-filing-collector/SKILL.md`（迁移时读取，规则以当时生效的任务配置为准）。
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)：submissions 及历史文件。
- [Inline XBRL 1.1](https://www.xbrl.org/specification/inlinexbrl-part1/rec-2013-11-18/inlinexbrl-part1-rec-2013-11-18.html)：数字事实的 context、单位、scale 与 sign。
- [Discord Message API](https://docs.discord.com/developers/resources/message)：消息回执、nonce 及 allowed_mentions。
