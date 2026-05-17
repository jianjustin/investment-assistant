# 测试用例与报告

## 执行摘要

| 指标 | 结果 |
|------|------|
| 总用例数 | 14 |
| 通过 | **14** |
| 失败 | 0 |
| 运行时间 | 0.89s |
| 运行环境 | Python 3.11.15, pytest 9.0.3, macOS |
| 测试策略 | 全部使用 `unittest.mock` 隔离，无网络调用 |

```
============================= test session starts ==============================
platform darwin -- Python 3.11.15, pytest-9.0.3, pluggy-1.6.0
rootdir: earnings-agent/
collected 14 items

tests/test_discord.py   ...                                              [ 21%]
tests/test_market.py    ....                                             [ 50%]
tests/test_price.py     ...                                              [ 71%]
tests/test_technicals.py....                                             [100%]

============================== 14 passed in 0.89s ==============================
```

---

## 测试设计原则

**隔离策略**：所有测试 mock `data.price.get_price_history` 或 `yf.Ticker`，确保：
- 无网络请求（离线可运行）
- 确定性结果（不受市场数据波动影响）
- 毫秒级执行速度

**TDD 执行顺序**：每个模块均先写失败测试，再实现代码，确保测试真正覆盖功能而非倒推通过。

**mock 挂载点**：统一 patch 在被测模块的导入路径（如 `signals.market.get_price_history`），而非原始模块路径，确保 patch 有效。

---

## 模块测试详情

### tests/test_discord.py — Discord 通知层

| # | 用例名 | 验证内容 | 测试手段 |
|---|--------|---------|---------|
| 1 | `test_send_earnings_calls_correct_webhook` | 发送到 EARNINGS 频道时使用包含 "earnings" 的 URL | mock `requests.post`，断言调用 URL |
| 2 | `test_send_raises_on_non_204` | HTTP 400 响应时抛出 `RuntimeError("Discord send failed")` | mock 返回 status_code=400，`pytest.raises` |
| 3 | `test_send_signals_calls_signals_webhook` | 发送到 SIGNALS 频道时使用包含 "signals" 的 URL | mock `requests.post`，断言调用 URL |

**设计说明**：
- 验证频道路由逻辑（`DiscordChannel` 枚举 → URL 映射）
- 验证错误处理（非 200/204 → RuntimeError，而非静默失败）
- 未测试 `templates.py`：embed 构建为纯数据变换，无外部依赖，视觉验证通过 `scripts/test_discord.py` 端到端完成

---

### tests/test_price.py — 数据获取层

| # | 用例名 | 验证内容 | 测试手段 |
|---|--------|---------|---------|
| 1 | `test_get_price_history_returns_dataframe` | 返回 DataFrame，包含 Close 列，长度 ≥ 1 | mock `yf.Ticker().history()` 返回单行 DF |
| 2 | `test_get_price_history_raises_on_empty` | yfinance 返回空 DF 时抛出 `ValueError("No price data")` | mock 返回空 DF，`pytest.raises(match=...)` |
| 3 | `test_get_price_history_returns_correct_columns` | 返回恰好 5 列：Open/High/Low/Close/Volume，多余列被过滤 | mock 返回含 Dividends/Stock Splits 的 DF，断言列集合 |

**设计说明**：
- 第 3 个测试关键：验证过滤逻辑而非仅验证列存在，mock 数据故意包含额外列

---

### tests/test_market.py — 大盘环境门控

| # | 用例名 | 验证内容 | 测试手段 |
|---|--------|---------|---------|
| 1 | `test_green_when_spy_bull_and_low_vix` | SPY 在 200MA 上方 + VIX=15 → status="green" | mock SPY (150+60) + VIX DF |
| 2 | `test_red_when_vix_above_30` | VIX=35 → status="red"（无论 SPY 位置） | mock SPY + VIX=35 |
| 3 | `test_yellow_when_spy_below_200ma` | SPY 跌破 200MA + VIX=18（< 20）→ status="yellow" | mock SPY 下行趋势 (120*150 + 90*60) |
| 4 | `test_yellow_when_vix_between_20_and_30` | SPY 在 200MA 上方 + VIX=25 → status="yellow" | mock SPY + VIX=25 |

**测试数据构造**：

```python
# 验证 200MA 计算正确性：
# 前 150 根收在 100，后 60 根收在 120 → 最后一根 (120) > MA200 (≈106.7) → 上方 ✓
spy_closes_bull = [100.0] * 150 + [120.0] * 60

# 前 150 根收在 120，后 60 根收在 90 → 最后一根 (90) < MA200 (≈110.5) → 下方 ✓
spy_closes_bear = [120.0] * 150 + [90.0] * 60
```

**设计说明**：
- 使用 `mock.side_effect = [spy_result, vix_result]` 模拟两次连续调用，顺序与实现一致
- 覆盖所有三种 status 的边界条件（red/yellow 两个触发路径/green）

---

### tests/test_technicals.py — 技术面信号

| # | 用例名 | 验证内容 | 测试手段 |
|---|--------|---------|---------|
| 1 | `test_rs_score_above_1_when_ticker_outperforms_spy` | 个股涨幅 > SPY → RS Score > 1.0 | ticker +30% vs SPY +10%，断言 `rs_score > 1.0` |
| 2 | `test_ma_reclaim_detected_when_price_crosses_21ema` | 价格从 21-EMA 下方穿越到上方 → `ma_reclaim=True` | 25根@50→1根@45→1根@55，EMA在~50 |
| 3 | `test_no_signal_on_flat_price` | 价格完全水平 → vcp/ma_reclaim 均为 False，has_signal=False | 130根完全相同价格+成交量 |
| 4 | `test_vcp_detected_when_atr_and_volume_contract` | ATR 和成交量同时收缩 → `vcp=True` | 70根高波动(2M vol) + 20根低波动(500K vol) |

**VCP 测试数据验证**：

```
高波动段 (70根): 价格 100-118 震荡，成交量 2M
紧缩段   (20根): 价格 110-110.5 震荡，成交量 500K

ATR_20 (紧缩段均值)  ≈ 2.2
ATR_60 (后60根均值)  ≈ 5.7  (含40根高波动 + 20根紧缩)
VCP 条件: 2.2 < 5.7 × 0.70 = 3.99  ✅

vol_20 = 500K
vol_60 = (40 × 2M + 20 × 500K) / 60 ≈ 1.5M
VCP 条件: 500K < 1.5M × 0.70 = 1.05M  ✅
```

**MA Reclaim 测试数据验证**：

```
25根@50 建立 21-EMA ≈ 50
第26根@45: EMA ≈ 49.5  → 45 < 49.5 ✅ (昨收 < 昨EMA)
第27根@55: EMA ≈ 50.0  → 55 > 50.0 ✅ (今收 > 今EMA)
ma_reclaim = True ✅
```

**特殊实现注意**：  
`has_signal` 属性的 `bool()` 包装是必要的——pandas 算术返回 `numpy.float64`，比较运算返回 `numpy.bool_`。不加 `bool()` 会导致 `assert sig.has_signal is False`（identity check）失败，因为 `numpy.bool_(False) is not False`。

---

## 未覆盖范围

| 模块 | 未测试内容 | 原因 |
|------|-----------|------|
| `notify/templates.py` | embed 结构字段内容 | 纯数据变换，通过 `scripts/test_discord.py` 目视验证 |
| `ops/earnings_monitor.py` | 完整 run() 流程 | 依赖外部文件系统和网络，集成测试范围 |
| `ops/daily_scan.py` | 完整 run() 流程 | 同上 |
| `data/earnings.py` | yfinance earnings_dates | Phase 1 遗留，集成验证通过 `--dry-run` |
| `data/sec.py` | SEC EDGAR 下载 | Phase 1 遗留，集成验证通过 `--date` 模式 |

---

## 运行测试

```bash
# 全套测试
python -m pytest tests/ -v

# 单模块
python -m pytest tests/test_technicals.py -v

# 指定用例
python -m pytest tests/test_market.py::test_red_when_vix_above_30 -v

# 生成简洁报告
python -m pytest tests/ -q
```

---

## Phase 3 测试计划（预告）

Phase 3 新增模块的测试方向：

| 模块 | 计划测试用例 |
|------|------------|
| `data/financials.py` | 返回正确季度数、空数据处理 |
| `signals/fundamentals.py` | EPS 加速分数计算、ROE 趋势判断 |
| `engine/scorer.py` | 权重加总逻辑、大盘门控截断 |
| `engine/claude_client.py` | mock Claude API 响应解析、JSON 格式校验 |
