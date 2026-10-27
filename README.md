# Investment Assistant

美股投研工作台。每天早上推送一份交易计划到 Discord，计划的价位能追溯到规则和数据；由你决定是否采纳、自己下单并录入成交，系统再按计划和实际结果做复盘。规则主计划之外，还并列一条 Agent 建议，两条轨道各自做影子跟踪。

不接券商，不自动下单。所有规则都**未经验证**（Phase 0 Gate HOLD），系统输出的价位和仓位只是你所设规则的算术结果，不构成投资建议。

当前版本：**v2.3.0**（2026-10-26），见 [CHANGELOG](CHANGELOG.md)。

v2.3 状态：`engineering_done`、`user_acceptance_pending`；迁移 024 已于 2026-10-27 在真实库执行、服务已重启，§11.2 手动验收已核对，用户确认浏览与连续 5 个交易日定时运行证据尚缺。保留偏差及后续验收条件见 [roadmap](docs/roadmap/README.md)。

## 组成

- **后端**：FastAPI + uvicorn 单进程，内置调度线程；PostgreSQL 是唯一的状态存储。
- **前端**：Svelte 5，主线入口是「今日」「标的」「复盘」「数据」。
- **外部数据**：yfinance、SEC EDGAR、FRED；Agent 用 LangGraph + 智谱；通知走 Discord。
- **运行**：本机 macOS LaunchAgent，只监听 `127.0.0.1:8787`。

详见 [架构](docs/architecture.md)。

## 快速开始

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
```

```bash
cd web && npm install && npm run build && cd ..
```

配置 `.env`、执行迁移、建 Agent 检查点表，见 [上手指南](docs/getting-started.md)；然后启动：

```bash
./start.command
```

## 测试

```bash
env -u INVESTMENT_ASSISTANT_DATABASE_URL -u INVESTMENT_ASSISTANT_TEST_DATABASE_URL -u TEST_DATABASE_URL .venv/bin/python -m pytest tests/ -q
```

```bash
cd web && NODE_OPTIONS=--no-experimental-webstorage npm test && npm run build
```

## 文档

从 [docs/README.md](docs/README.md) 开始：架构、功能、运维、roadmap、spec 与 plan。
