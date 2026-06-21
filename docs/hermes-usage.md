# Hermes 使用说明

Hermes 是投资助手中的自动化解释层：它读取已经落库的数据，生成结构化判断和下一步动作建议。当前已将原“市场信号解读”升级为“宏观分析师”，用于承接投资决策系统五段链路中的 Research / MacroSnapshot 阶段；后续可继续接入 filings、watchlist、研究简表、回测报告和观点生成。

## 在后台页面中使用

打开服务看板后进入 `市场信号` 一级菜单：

- `市场总览`：查看最新市场状态、趋势判断和“宏观分析师”最近窗口分析。
- `趋势看板`：查看 VIX 趋势、周期判断和同一份宏观分析。
- `手动拉取`：回补某一天或一段日期的市场信号；提交后会显示“正在拉取市场信号...”状态栏。

宏观分析师的目标不是预测涨跌，而是稳定回答投资决策系统第一阶段的问题：当前市场适合进攻、谨慎还是防守；哪些指标支持；对成长股和 watchlist 有什么影响；下一次应该重点观察什么。

## 自定义 Hermes Agent

打开 `Hermes -> Hermes Agents` 可以查看内置 agent 与自定义 agent。当前自定义 agent 会持久化到：

```text
/opt/hermes-investment-assistant/config/hermes-agents.json
```

一个 agent 配置包含：

- `id`：稳定标识，只支持小写字母、数字、连字符和下划线
- `name` / `role` / `description`：用于后台展示和后续编排
- `system_prompt`：该 agent 的行为边界
- `data_sources`：允许读取的数据源，如 `market_signals`、`watchlist`、`filings`
- `tools`：允许调用的 Hermes 能力，如 `market_signal_interpretation`
- `enabled`：是否启用

当前版本只保存配置，不从浏览器执行任意 shell 命令。真正运行 agent 前，需要再增加运行记录、审计和输入确认。

## 宏观分析师与五段链路

投资决策系统的五段链路是：

```text
Research -> Discover -> Backtest -> Viewpoint -> Plan -> 人工闸门
```

宏观分析师对应第一段 `Research`，输出 `MacroSnapshot` 风格结构：

- `macro_state`：`offense` / `cautious` / `defense`
- `stance_label`：进攻 / 谨慎 / 防守
- `key_changes`：最近窗口最重要变化
- `growth_implications`：对美股成长股研究的影响
- `watchlist_implications`：对当前 watchlist 的影响
- `next_checks`：下一次重点观察
- `actions`：下一步动作建议

DeepSeek 作为显式触发的解释增强边界：`investment_assistant/hermes/deepseek_client.py` 使用 OpenAI-compatible Chat Completions 格式，读取 `DEEPSEEK_API_KEY`，请求 JSON output。当前 dashboard 普通刷新默认使用规则版宏观分析；点击“调用 DeepSeek 解读”或调用 POST 接口时才会触发真实 LLM 调用，并把 run_id 与 LLM 状态写入运行日志。

## API 调用

查看 Hermes 总览、能力、agents 和扩展思路：

```bash
curl -u "$HERMES_DASHBOARD_USER:$SERVER_PWD" \
  'http://127.0.0.1:8787/api/hermes'
```

创建或更新自定义 agent：

```bash
curl -u "$HERMES_DASHBOARD_USER:$SERVER_PWD" \
  -H 'Content-Type: application/json' \
  -d '{"id":"risk-reviewer","name":"风险复核 Agent","role":"risk_reviewer","data_sources":["market_signals"],"tools":["market_signal_interpretation"],"enabled":true}' \
  'http://127.0.0.1:8787/api/hermes/agents'
```

获取最近一个月市场信号解读：

```bash
curl -u "$HERMES_DASHBOARD_USER:$SERVER_PWD"   'http://127.0.0.1:8787/api/hermes/market-signals/interpretation?window=30'

# 显式触发真实 LLM 解读
curl -u "$HERMES_DASHBOARD_USER:$SERVER_PWD" \
  -H 'Content-Type: application/json' \
  -d '{"window":30,"model":"deepseek-v4-pro"}' \
  'http://127.0.0.1:8787/api/hermes/macro-analysis/run'
```

返回结构包含：

- `macro_state`：`offense`、`cautious` 或 `defense`
- `stance_label`：进攻、谨慎或防守
- `summary`：宏观分析师的一句话判断
- `macro_snapshot`：Research / MacroSnapshot 风格结构
- `key_changes`、`growth_implications`、`watchlist_implications`、`next_checks`
- `actions`：建议动作列表

## 在投资助手中如何利用 Hermes

当前建议把 Hermes 当作“编排与解释组件”，而不是直接替你下判断：

1. 数据层先由定时任务或手动拉取写入 `market_signals`，中期接入 `vibe-trading-system` 的 `MacroSnapshot` artifact。
2. 宏观分析师读取最近窗口数据，生成 `macro_state + MacroSnapshot + actions`。
3. 后台页面把宏观分析师输出放在市场看板旁边，减少你在数据表、趋势图和命令行之间切换。
4. 后续 Discover / Backtest / Viewpoint / Plan 阶段读取同一份宏观状态作为上游约束。
5. 真正的投资动作仍由你确认；Hermes 只负责提供框架、证据、反方问题和检查清单。

后续扩展方向：把 filings 摘要、watchlist 技术信号、ResearchBrief、BacktestReport、持仓暴露一起输入 Hermes，形成“宏观环境 -> 标的筛选 -> 回测验证 -> 观点生成 -> 执行计划草案”的统一工作流。
