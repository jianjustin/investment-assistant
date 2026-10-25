# 美股财季数据、指引与研究观察卡

> v1 遗留，保留但不再演进，见 [遗留功能清单](README.md)。设计见 [归档 spec](../../archive/roadmap-v1/specs/2026-10-16-cross-market-medium-term-research-design.md)。v2.0.0 删除了 A 股部分，研究观察卡只支持美股。

## 功能

- **美股财季数据**（`us_research/`）：从 SEC Company Facts 和申报原文采集实际财季的收入、经营现金流、资本开支、利润等数据，并采集日线和报价。每个数值都保留申报版本、来源 URL、JSON 定位和原始快照的 SHA-256。数据只追加，存入 `us_research_observations`。
- **计算口径**：实际财季按起止日对齐，不直接用申报的 `fy/fp` 或日历季度。单季金额优先用直接披露的值，只有在同财年、同币种、同口径时才用累计值差分；TTM 需要连续四季；标准 FCF = CFO − 现金 PPE。缺少输入时保持 null 并写明原因，不用相近的标签替代。估值（PE / PS / FCF 收益率）在市值来源核实之前保持为空。
- **公司指引**：按原文录入，修订时追加新版本、保留原始记录；只在口径完全一致时与实际值比较。
- **研究观察卡**（`research/cards.py`）：每只美股一张可编辑卡片，包括投资假设、证据（关联数据记录或原文链接，引用的数值必须和原始记录一致）、情景（利润 × PE ÷ 股数，必须写币种，不是目标价）、失效条件、关联的 SEC 原文。按版本号做乐观锁，冲突时返回 409，不覆盖别人的修改。

## 入口与验证

- 页面：「更多 → 数据 → 美股研究数据」（选股、财季表、来源展开、指引编辑、手动刷新）；「更多 → 策略 → 研究观察卡」。
- API：

  ```bash
  curl -s "localhost:8787/api/us-research/MU"
  curl -s -X POST "localhost:8787/api/us-research/sync" -H 'content-type: application/json' -d '{"symbols": ["MU"]}'
  curl -s "localhost:8787/api/us-research/MU/guidance"
  curl -s "localhost:8787/api/research/observation-cards/MU"
  curl -s "localhost:8787/api/research/us-references"
  ```

  `PUT /api/research/observation-cards/{symbol}` 的 body 为 `{body, expected_version}`。
- 只读验收脚本（只读事务 + 回环 GET，唯一的写入是 `--output` 指定的报告）：

  ```bash
  .venv/bin/python scripts/verify_cross_market.py --api-url http://127.0.0.1:8787 --raw-root .local/us-research/raw --output .local/cross-market/verification.json
  ```

## 已知限制

- Company Facts 不含分部、产品和经营指标；HBM、RPO、客户集中度这类数据需要原始披露或人工附证。
- TSLA 沿用「不收 10-K」的规则，所以第四季有缺口，不能把它的 12 行当作连续 12 季，也不能跨缺口算 TTM。
- 当前供应商的复权回填，不等于当时的拆股或分红版本，也不保证是严格的总回报。
