# 功能验证 — 交易区（Trade / Hermes）

> 前端入口：侧边栏「🤖 交易」。LLM 相关功能需要 `DEEPSEEK_API_KEY`，未配置时返回降级错误（不崩）。hermes 概念说明见 [hermes-usage.md](../hermes-usage.md)。

## 1. 宏观分析（macro）

**功能**：基于近 N 日市场信号生成宏观解读（`stance_label` + `summary`）；可触发 LLM 深度分析。

- **手动入口**：交易 → 宏观分析 → 「运行 LLM 宏观分析」（异步，轮询 run_id）
- **API**：
  ```bash
  curl -s "localhost:8787/api/hermes/macro-analysis?window=30"
  curl -s -X POST "localhost:8787/api/hermes/macro-analysis/run" -H 'content-type: application/json' -d '{"window": 30}'
  # 别名路由（同一 handler）：GET /api/hermes/market-signals/interpretation
  ```
- **如何验证**：无 LLM key 时 GET 仍返回规则版解读；配 key 后点按钮，完成时页面出现 LLM 生成的 summary。

## 2. 决策证据（decision）

**功能**：汇总当前信号/评分/持仓上下文生成决策证据包。

- **手动入口**：交易 → 决策证据 → 「生成决策证据」
- **API**：
  ```bash
  curl -s -X POST "localhost:8787/api/hermes/decision-evidence/run" -H 'content-type: application/json' -d '{"use_llm": true}'
  curl -s "localhost:8787/api/runs/<run_id>"
  ```
- **如何验证**：提交后 run 状态 pending → done，result 内含证据结构。

## 3. Agent 注册表

**功能**：hermes agent 定义的查看与保存（当前仅 API 面，前端无独立编辑页）。

- **API**：
  ```bash
  curl -s "localhost:8787/api/hermes"                    # overview
  curl -s "localhost:8787/api/hermes/agents"             # {"agents": [...]}
  curl -s -X POST "localhost:8787/api/hermes/agents" -H 'content-type: application/json' -d '{"name": "test-agent"}'
  ```
- **错误契约**：无效 agent 定义抛 ValueError → 400 `{"error": "<原因>"}`。

## 4. 交易指令（orders）— 未实现

占位页（Placeholder），计划于后续 Phase 实现。
