# Hermes：宏观分析与决策证据

> v1 遗留，保留但不再演进，见 [遗留功能清单](README.md)。工作台的解读已经由 [Agent 轨道](../agent-track.md) 产出，不使用 Hermes。

Hermes 读取已入库的市场信号，生成结构化的宏观判断：当前适合进攻、谨慎还是防守，哪些指标支持这个判断，对 watchlist 有什么影响，下一步应该观察什么。规则版默认可用；只有显式触发时才调用 DeepSeek（`DEEPSEEK_API_KEY`），未配置时返回降级错误，不会崩溃。

## 功能

- **宏观分析**：基于最近 N 日（5–90，默认 30）的 `market_signals`，输出 `macro_state`（offense / cautious / defense）、`stance_label`、`summary`、`key_changes`、`growth_implications`、`watchlist_implications`、`next_checks`、`actions`。
- **决策证据**：汇总信号、评分和上下文，生成一份证据包，异步运行。
- **Agent 注册表**：保存自定义 agent 的配置（`id`、`name`、`role`、`system_prompt`、`data_sources`、`tools`、`enabled`），写入固定路径 `/opt/hermes-investment-assistant/config/hermes-agents.json`（不受 `INVESTMENT_ASSISTANT_RUNTIME_BASE` 影响）。只保存配置，不执行任何命令。

## 入口与验证

- 页面：「更多 → 交易 → 宏观分析 / 决策证据」。「交易指令」是占位页，未实现。
- API：

  ```bash
  curl -s "localhost:8787/api/hermes/macro-analysis?window=30"
  curl -s -X POST "localhost:8787/api/hermes/macro-analysis/run" -H 'content-type: application/json' -d '{"window": 30}'
  curl -s -X POST "localhost:8787/api/hermes/decision-evidence/run" -H 'content-type: application/json' -d '{"use_llm": true}'
  curl -s "localhost:8787/api/runs/<run_id>"
  curl -s "localhost:8787/api/hermes/agents"
  ```

  `GET /api/hermes/market-signals/interpretation` 是宏观分析的别名。
- 验证一次：没有 `DEEPSEEK_API_KEY` 时，GET 仍能返回规则版解读；配置之后点「运行 LLM 宏观分析」，运行完成后页面显示 LLM 生成的 summary。
