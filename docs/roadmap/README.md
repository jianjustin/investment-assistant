# Roadmap

> v2 已完成，发布为 `v2.0.0`（2026-10-25）。v2 的收尾版 `v2.1.0` 收拢 v1 遗留功能，设计见 [spec](../specs/2026-10-25-v2.1-legacy-consolidation-design.md)。其余候选项见 [backlog.md](backlog.md)。v1（2026-06-30 – 2026-10-23）已归档到 [archive/roadmap-v1](../archive/roadmap-v1/README.md)，仅作历史参考。
> 从 v2 起，roadmap 版本即发布的大版本号。

## 文档

| 文档 | 内容 | 更新方式 |
| --- | --- | --- |
| [v2-decision-loop.md](v2-decision-loop.md) | 长期路线：目标与成功标准、各环节设计、P1–P4 阶段、暂缓与不做、决策记录 | 方向变化时改，并在决策记录追加 |
| [v2-progress.md](v2-progress.md) | v2 各阶段状态与阶段证据 | 已冻结（v2.0.0），只追加验收证据 |
| [backlog.md](backlog.md) | 下一版候选：v1 遗留的合并或删除、v2 暂缓项、未完成的使用验收 | 排期变化时改 |

## 版本

| 版本 | 时间 | 主线 | 状态 |
| --- | --- | --- | --- |
| v1 | 2026-06-30 – 2026-10-23 | Phase 0 事件研究 → 数据地基 → 计划—执行—复盘 → 区制与校准 | 已归档；FastAPI 迁移、事件研究框架、美股工作台已落地，Phase 0 正式 Gate HOLD |
| v2 | 2026-10-23 – 2026-10-25 | 数据 → 交易计划（规则主计划 + Agent 建议）→ Discord 投递 → 复盘 | 已完成，发布 `v2.0.0`；P1–P4 `engineering_done`，`user_acceptance_pending`；删除 A 股 |
| v2.1 | 2026-10-25 | v1 遗留收拢：删除 Hermes、SPY/VIX 信号、趋势快照、策略评分、事件研究、研究观察卡；K 线图、基本面并入「标的」页，信号后超额并入 `backcheck-2`（[spec](../specs/2026-10-25-v2.1-legacy-consolidation-design.md)） | `engineering_done`、`user_acceptance_pending`、`runtime_unverified`（迁移 022 未在真实库执行）；v2 路线收尾，不开 v3 |
| 下一版 | — | 见 [backlog.md](backlog.md) | 未排期 |

## 沿用原则

以下来自 v1 [00](../archive/roadmap-v1/00-principles-and-direction.md)，v2 继续有效：

- **闭环优先于回测**：价值在「计划、执行、结果」的归因，不在小样本上的组合回测。
- **证伪优先于建设**：规则和 Agent 都要有影子跟踪证据，没有证据不宣称有效。
- **诚实优先于漂亮**：统计带样本量；区分「没算」和「无信号」；不用历史反推参数。
- **人在环路**：系统出计划，人决定是否下单；不接券商、不自动下单。

## 交付标准（DoD）

每个阶段的每项交付同时满足四条：

1. **手动入口**：自动任务有手动触发路径（API、CLI 或前端按钮至少其一）。
2. **验证入口**：结果可查（`job_reports`、前端状态或 CLI 输出至少其一）。
3. **功能说明 + 如何验证**：文档或页面写清做什么、怎么手动验证一次。
4. **离线测试**：pytest 离线可跑，数据库、网络、LLM 全部 mock 或注入。

工程纪律沿用：路由层薄封装（`api/routes` → `services` → `db` / `tasks`）；外部失败结构化返回，不吞成成功；凭据不进报告；业务数据只追加，更正用新记录指向旧记录。

## 状态用语

| 用语 | 含义 |
| --- | --- |
| `engineering_done` | 代码和入口在仓库里 |
| `runtime_unverified` | 尚未经真实库、HTTP 或页面验收 |
| `gate_hold` | 证据不够，不能当作有效规则 |
| `user_acceptance_pending` | 工程结果不能代替使用验收 |

没有新证据时，不把状态改成完成。
