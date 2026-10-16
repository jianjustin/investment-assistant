# 文档索引

## 上手

| 文档 | 内容 |
|------|------|
| [getting-started.md](getting-started.md) | 本机安装、配置、启动、跑测试 |
| [architecture.md](architecture.md) | 模块分层与数据流（FastAPI + services + tasks + Svelte 5 前端） |
| [deployment-sealos.md](deployment-sealos.md) | 云端部署（Sealos Starter Plan：镜像构建、数据库、双进程、验证清单） |

## 功能验证手册（按前端五区）

每个功能点包含：功能说明 + 手动入口（前端路径）+ API/CLI 入口 + 如何验证示例。

| 区 | 文档 | 覆盖功能 |
|----|------|---------|
| 📊 数据 | [features/data.md](features/data.md) | 市场信号总览、趋势分析、技术面趋势、财报 |
| 🎯 策略 | [features/strategy.md](features/strategy.md) | 策略评分、事件研究 |
| 🤖 交易 | [features/trade.md](features/trade.md) | 宏观分析、决策证据、agent 注册表 |
| 🔧 工具 | [features/tools.md](features/tools.md) | 任务中心（含按日期回补）、运行记录、SSE 事件流 |
| ⚙️ 设置 | [features/settings.md](features/settings.md) | 系统状态、关注列表、Discord 推送、定时任务、认证 |

全部 API 的参数与响应可在服务运行时访问 `http://localhost:8787/docs`（OpenAPI）交互查看。

## 模块深度参考

| 文档 | 内容 |
|------|------|
| [research-event-study.md](research-event-study.md) | 事件研究：方法、字段、CLI/API/前端三条验证路径 |
| [scheduling-and-notifications.md](scheduling-and-notifications.md) | 调度器 daemon、job_reports、Discord 通知机制 |
| [sec-downloader.md](sec-downloader.md) | SEC EDGAR filings 下载器 |
| [sec-monitor-migration.md](sec-monitor-migration.md) | 本机接管 SEC 监控：正文事实、来源报告、历史去重、Discord 通知及回执 |
| [hermes-usage.md](hermes-usage.md) | Hermes（宏观/决策）概念与用法 |

## 方向与历史

| 位置 | 内容 |
|------|------|
| [roadmap/](roadmap/README.md) | 原则与各 Phase 方向文档（含 DoD 标准，roadmap/00 §6） |
| [superpowers/](superpowers/) | 各阶段的设计 spec 与实施 plan（历史工件，按日期命名，只增不改） |
