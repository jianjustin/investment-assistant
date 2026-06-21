# Hermes 使用说明

Hermes 是投资助手中的自动化解释层：它读取已经落库的数据，生成结构化判断和下一步动作建议。当前已接入市场信号解读，后续可继续接入 filings、watchlist 和个股技术信号。

## 在后台页面中使用

打开服务看板后进入 `市场信号` 一级菜单：

- `市场总览`：查看最新市场状态、趋势判断和 Hermes 最近一个月解读。
- `趋势看板`：查看 VIX 趋势、周期判断和同一份 Hermes 解读。
- `手动拉取`：回补某一天或一段日期的市场信号；提交后会显示“正在拉取市场信号...”状态栏。

## API 调用

获取最近一个月市场信号解读：

```bash
curl -u "$HERMES_DASHBOARD_USER:$SERVER_PWD"   'http://127.0.0.1:8787/api/hermes/market-signals/interpretation?window=30'
```

返回结构包含：

- `judgement`：`risk_on`、`neutral` 或 `risk_off`
- `summary`：Hermes 的一句话解读
- `metrics`：绿色/红色占比、SPY 高于 200MA 比例、平均 VIX
- `sections`：可直接展示到页面的结构化段落
- `actions`：建议动作列表

## 在投资助手中如何利用 Hermes

当前建议把 Hermes 当作“解释组件”，而不是直接替你下判断：

1. 数据层先由定时任务或手动拉取写入 `market_signals`。
2. Hermes 读取最近窗口数据，生成 `judgement + summary + actions`。
3. 后台页面把 Hermes 输出放在市场看板旁边，减少你在数据表、趋势图和命令行之间切换。
4. 真正的投资动作仍由你确认；Hermes 只负责把环境信号翻译成风险状态和检查清单。

后续扩展方向：把 filings 摘要、watchlist 技术信号、持仓暴露一起输入 Hermes，形成“市场环境 -> 标的筛选 -> 风险动作”的统一工作流。
