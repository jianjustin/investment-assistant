# 起步指南

## 前置条件

- Python 3.11+
- Node.js 18+（构建 `web/` 前端）
- PostgreSQL 16（可选；缺省时调度/报告路径优雅降级，不崩）
- SEC EDGAR 用户标识（免费，填邮箱即可）
- Discord webhook（可选，用于推送；也可在「设置 · Discord 推送」页配置）

---

## 安装

```bash
# 克隆仓库
git clone <repo-url>
cd investment-assistant

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装测试依赖
pip install pytest
```

---

## 配置 .env

在项目根目录创建 `.env`（已在 `.gitignore` 中，不会提交）：

```env
# SEC EDGAR — 下载财报必填，格式固定（含邮箱）
SEC_USER_AGENT=YourName your@email.com

# PostgreSQL — 可选；不配置时报告/快照路径跳过，不影响离线运行
INVESTMENT_ASSISTANT_DATABASE_URL=postgresql://user:pass@localhost:5432/investment

# Discord webhooks — 可选；也可在「设置 · Discord 推送」页填写并验证
DISCORD_WEBHOOK_EARNINGS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_SIGNALS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_DAILY=https://discord.com/api/webhooks/...
```

> Discord 配置优先级：「设置 · Discord 推送」页写入数据库的 `notify_settings`（overlay）> `.env` 中的 webhook 环境变量。详见 [scheduling-and-notifications.md](scheduling-and-notifications.md)。

---

## 初始化数据库（可选）

配置了 `INVESTMENT_ASSISTANT_DATABASE_URL` 后，按编号顺序执行 `migrations/` 下的 SQL（001-008）建表。迁移均为幂等（`CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO NOTHING`），可重复执行：

```bash
for f in migrations/0*.sql; do
  psql "$INVESTMENT_ASSISTANT_DATABASE_URL" -f "$f"
done
```

`scheduled_jobs`（007）已 seed 三个任务：`metrics` 08:00 / `filings` 09:00 / `scores` 18:00（America/New_York，周一至周五）。

---

## 构建并运行

```bash
# 构建前端（产物落到 web/dist，由 API server 提供静态资源）
cd web && npm install && npm run build && cd ..

# 启动 API server（含前端面板与 SSE）
python -m investment_assistant.api.server
```

面板为五层信息架构：**工具 / 数据 / 策略 / 交易 / 设置**，默认落地「工具」层。

---

## 手动运行单个任务

每个定时任务都可单独调用，无需启动常驻调度器。适用于调试与按需补跑。结果写入 `job_reports` 表（有 DB 时），并按配置推送 Discord；在面板「工具 · 运行记录 / 数据结果」页可回看。

```bash
# 08:00 指标任务（大盘信号 + 个股趋势快照）
python -m investment_assistant.tasks.metrics

# 09:00 财报任务（SEC EDGAR 下载昨日新提交财报落盘）
python -m investment_assistant.tasks.filings

# 18:00 策略评分任务
python -m investment_assistant.tasks.nightly_scores
```

财报下载器细节（落盘路径、`SEC_USER_AGENT` 降级行为）见 [sec-downloader.md](sec-downloader.md)。

---

## 常驻调度守护进程

自研 pg 调度器按 `scheduled_jobs` 表定时触发已注册任务，取代了逐任务 systemd timer：

```bash
python -m investment_assistant.tasks.scheduler
```

- 改运行时间 / 启停某任务：在面板「设置 · 定时任务」页操作（写 `scheduled_jobs`），或直接 `UPDATE scheduled_jobs ...`。
- 生产部署见 `deploy/systemd/hermes-investment-scheduler.service`（`Restart=always`，单一常驻 service）。
- 调度、报告（`job_reports` 30 天 TTL）与通知机制详见 [scheduling-and-notifications.md](scheduling-and-notifications.md)。

---

## 验证 Discord 推送

无需命令行脚本：在面板「设置 · Discord 推送」页，为每个频道（earnings / signals / daily）填入 webhook 并点「验证」即时发送测试消息；webhook 明文不回显（仅显示是否已配置）。

---

## 运行测试

```bash
# 运行所有单元测试（全程 mock，离线可跑）
.venv/bin/python -m pytest -q

# 运行特定测试文件
.venv/bin/python -m pytest tests/test_jobs_repository.py -v
```

外部依赖（SEC / Discord / yfinance / DB）全部 mock 或注入，无网络与真实 DB 也能跑；DB 集成测试在缺少 `INVESTMENT_ASSISTANT_TEST_DATABASE_URL` 时自动 skip。

---

## 常见问题

**Q: `No price data returned for ^VIX`**  
A: yfinance 有时对 VIX 返回空数据，重试通常可解决。指标任务将其作为非致命错误记录，下一周期自动恢复。

**Q: Discord 没有收到推送**  
A: 检查「设置 · Discord 推送」页是否启用且 webhook 已配置（或 `.env` 中的 webhook 环境变量）；`discord_enabled=False` 或该任务被关闭时不推送。

**Q: 财报没有下载 / 返回空**  
A: 确认 `SEC_USER_AGENT` 已设置且格式含邮箱；缺失时下载器优雅降级返回空结果。SEC EDGAR 有访问频率限制，必要时重试。

**Q: 报告/快照相关功能不生效**  
A: 未配置 `INVESTMENT_ASSISTANT_DATABASE_URL` 时，报告与快照路径会被跳过（接口返回 `degraded: true`），属预期降级。

---

## 项目结构快速参考

```
investment_assistant/   生产包（api / services / tasks / filings / notify / db.py）
web/                    Svelte 5 前端（工具 / 数据 / 策略 / 交易 / 设置 五层 IA）
migrations/             PostgreSQL schema 迁移（001-008）
deploy/                 systemd service 模板与安装脚本
tests/                  单元测试
docs/                   项目文档
```

完整架构说明见 [architecture.md](architecture.md)。
