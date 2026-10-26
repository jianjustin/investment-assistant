# 文档索引

建议按这个顺序读：[architecture.md](architecture.md) 了解系统由哪些部分组成；[getting-started.md](getting-started.md) 在本机跑起来；再读 `features/` 了解每个功能。

## 系统现在是什么样

| 文档 | 内容 |
| --- | --- |
| [architecture.md](architecture.md) | 运行形态、代码分层、主线数据流、数据表分组、定时任务与前端 |
| [getting-started.md](getting-started.md) | 安装、配置（`.env` 与配置文件）、建库、启动、测试 |

### 功能（features/）

每篇都写：做什么、页面与 API/CLI 入口、怎么验证一次、已知限制。

| 文档 | 功能 |
| --- | --- |
| [daily-plan.md](features/daily-plan.md) | 每日流程、规则 v1、交易计划、持仓止损、每日推送 |
| [agent-track.md](features/agent-track.md) | Agent 轨道：工具层、提议与反方、引用校验、预算、解读 |
| [review.md](features/review.md) | 影子跟踪、纪律、三方对比、周/月复盘、资金与月度收益、复盘推送 |
| [pool-and-context.md](features/pool-and-context.md) | 观察池分层、每日筛选（纳指 100 `screen-1`、成员轮换、报告与只读回放）、市场环境（广度、区制、行业、FRED）、上线前检查 |
| [sec-filings.md](features/sec-filings.md) | SEC 下载器与 SEC 监控 |
| [fundamentals.md](features/fundamentals.md) | 「标的」页的基本面一栏：美股财季数据与公司指引 |
| [legacy/](features/legacy/README.md) | v1 遗留功能的墓碑页：逐项列出 v2.1.0 的删除与去向（旧实现见 tag `v2.0.0`） |

### 运维（operations/）

| 文档 | 内容 |
| --- | --- |
| [local-service.md](operations/local-service.md) | LaunchAgent、启动链路、重启、日志与路径、认证 |
| [scheduling-and-notifications.md](operations/scheduling-and-notifications.md) | 调度线程、任务注册表、运行报告、通知配置 |
| [migrations-and-backup.md](operations/migrations-and-backup.md) | 迁移清单 001–023、真实库备份与执行、一次性测试库 |

## 方向与历史

| 位置 | 内容 |
| --- | --- |
| [roadmap/](roadmap/README.md) | 版本表、沿用原则、交付标准（DoD）；v2 路线与进度（已完成）；[后续路线 v2-visibility](roadmap/v2-visibility.md)（当前）；[backlog](roadmap/backlog.md) |
| [specs/](specs/) | 各阶段的设计 spec |
| [plans/](plans/) | 各阶段的实施 plan |
| [archive/roadmap-v1/](archive/roadmap-v1/README.md) | roadmap v1 及其 spec、plan、评审 |
| [../CHANGELOG.md](../CHANGELOG.md) | 按版本记录的变更 |

## 维护规则

| 类别 | 回答的问题 | 什么时候改 |
| --- | --- | --- |
| roadmap | 往哪走、为什么、走到哪一步了 | 方向变化时改；进度文档按周更新；版本完成后冻结 |
| spec | 某个阶段为什么这样设计 | 写成后冻结，只增不改；命名 `specs/YYYY-MM-DD-<topic>-design.md` |
| plan | 某个阶段怎么实施 | 写成后冻结，只增不改；命名 `plans/YYYY-MM-DD-<topic>.md` |
| features / architecture / operations | 系统现在能做什么、怎么用、怎么验证 | 和代码在同一个提交里更新 |

冻结文档只修失效链接，不改正文。`tests/test_docs_links.py` 会检查所有相对链接都指向存在的文件。
