# 事件研究（Event Study）— 功能说明与验证

## 功能与当前边界

事件研究是回测分层中的描述性 A 层：统计某类事件之后 5/10/20 个交易日的股票收益减同期 SPY 收益，报告有效样本数、区制、缺失/跳过原因及统计限制，不模拟可交易组合。工程入口已落地，本轮成熟度、准确端点、as-of、来源与缓存语义修复正在最终复核；最终回归数字见 [实施状态](implementation-status-2026-10-17.md)待补项。

[2026-10-17 只读归档评审](roadmap/reports/2026-10-17-phase0-review.md)的正式 Gate 全部 HOLD。它只重建 SMA20 事件；RS、score、EPS/VCP 未计算的 n 为 null，不是零事件。当前 DB 不可达，实际表行数/覆盖 unknown；本轮未进行 HTTP/UI 验收，不能把历史报告或离线组件测试当成本次运行通过。

| kind | 当前定义 / 可用性 | 使用限制 |
| --- | --- | --- |
| `ma_reclaim` | 前一交易日 Close ≤ SMA20，当日 Close > SMA20 | **SMA20，不是 21EMA**；必须有相邻且来源可核对的状态，旧不可信快照不能直接使用 |
| `score_high` | 已有评分阈值事件定义 | 需可信同日快照、策略/计算版本与历史市场输入；本次归档缺这些证据，未计算 |
| `rs_strong` | 挂起 | RS 为 20 日收益差小数；旧 1.2 等于 120 个百分点，单位/意图未确认，不改成 1.2% 或 1.2 倍 |
| `eps_beat` / `eps_miss` | 不可用 | 可信历史 EPS 实际/市场一致预期及公布时点源未实现，不能用占位返回零样本成功 |
| `vcp` / `vcp_breakout` | 不可用 | 事件源未实现 |

可选定义存在不等于运行数据可用。`kinds` 接口返回可选定义及不可用原因；生产来源缺失/数据库失败、真正空样本与已计算零超额应分别解释。015 最小补强正在为快照增加 `price_date` / `calculation_version`、为评分增加 `calculation_version`，老行 null、不回填、不覆盖冲突旧记录；迁移文件本轮未在真实 DB 执行，不能声称历史数据已经可信。

## 日期与统计语义

`asof` 同时限制事件日和收益端点。事件研究默认采用纽约当前日期之前的最近交易日作为保守截止，显式未来日期也不能突破该上界；这不同于技术扫描在美东 16:15 后允许当日已完成 session 的默认规则。5/10/20 均为交易日数，不是自然日；端点尚未到达截止日即未成熟，不能缩短持有期。

股票与 SPY 必须都有事件日、精确第 h 个交易日的唯一有效收盘价；重复、未标日期、非有限/非正值或缺失端点不能用前值/未来值替代。窗口分别统计有效 n，不能把事件总数当每个窗口样本数。新语义使用新缓存版本/参数身份，不沿用旧口径结果；来源可信度的第二轮修复仍须完成最终复核。

| 字段 | 含义 |
| --- | --- |
| `horizon` / `n` | 交易日窗口 / 该窗口实际有效样本数 |
| `mean_excess` / `median` / `std` | 超额均值、中位数、标准差；JSON 用小数，0.01 = 1 个百分点 |
| `hit_rate` | 超额严格大于零的比例，不是含成本策略胜率 |
| `t_stat` / `ci95` | 朴素均值统计量 / 描述性 95% 区间 |
| `by_regime` | 按已知区制分组；`unknown` 不得解读为真实 green/yellow/red |
| `params` / `caveats` | 实际 `asof`、窗口、语义/定义、跳过原因与限制；应连同数值查看 |

当前区间为 `mean ± 1.96 × sample_std / sqrt(n)`，未处理同日跨股、同股重复、持有期重叠和多重检验。`n<30` 的警告只是最低提示，不是 `n≥30` 就可信。缺历史区制、当前池选择偏差、供应商复权回填、无成本/入场模型时，即使 CI 不跨零也不能推断信号有效。事件收盘到未来收盘的统计不是观察信号后能在同一收盘成交的保证。

## 首选：本次归档的无副作用离线复现

在仓库根、使用已安装的项目依赖，运行以下只读脚本。它不调用生产事件源、任务、服务或采集器，不联网/访问数据库，不通知；默认仅打印 JSON。

```bash
.venv/bin/python -I -B scripts/review_phase0_archives.py \
  --raw-root .local/us-research/raw \
  --asof 2026-10-15
```

需保存时可追加 `--output "$OUTPUTS/新的评审文件.json"`；`OUTPUTS` 必须在仓库与 raw-root 之外。脚本只创建新文件且不覆盖。固定原始字节、代码 hash 与 asof 后才具有复现意义；不是运行一次就获得新数据或正式 Gate 通过。

## 生产入口：仅在另行确认副作用后验收

**以下不是本轮只读归档核验命令。** 生产 CLI 会读取事件源并可能联网取价/区制；普通任务可写 `job_reports` 并按配置通知。API 即使为 GET，缓存未命中也可能计算和写 `event_studies`；UI“运行”调用该路径。`--no-record` 只绕开任务报告/通知外壳，不能理解为通用离线或只读开关。不要为验证而启动第二个服务/调度器或触发补采。

### CLI

实际任务入口为 `tasks.event_study`；缺省仅尝试已提供定义的 kind（目前 MA 与 score），不再默认 RS/EPS。建议用明确 `ma_reclaim` 和固定截止日检查口径，而不是未知阈值的 RS。

```bash
# 生产计算示例：仅在另行确认访问/副作用边界后运行
.venv/bin/python -m investment_assistant.tasks.event_study \
  --kind ma_reclaim --asof 2026-10-15 --no-record

# 只查看参数
.venv/bin/python -m investment_assistant.tasks.event_study --help
```

`--kind` 可多次传入，`--since` 设置事件下界。`--no-record` 输出的顶层为 `task/status/summary`，结果和实参在 `summary` 中；普通模式经任务外壳输出 job report。内部 `research.event_study` 委托到相同 CLI，参数以任务入口为准。验收应同时核对 unavailable/source 信息、实际截止、逐窗口 n/跳过和错误，不能只看 JSON 能返回。

### API 与前端

使用已运行的本地服务，认证值仅从用户环境读取，不写入文档。以下是未来手动验收示例，本轮未执行；第二个 GET 可能写缓存。

```bash
curl -s -u "$HERMES_DASHBOARD_USER:$SERVER_PWD" \
  "http://127.0.0.1:8787/api/research/event-study/kinds"
curl -s -u "$HERMES_DASHBOARD_USER:$SERVER_PWD" \
  "http://127.0.0.1:8787/api/research/event-study?kind=ma_reclaim&asof=2026-10-15"
```

可浏览 `http://127.0.0.1:8787/docs` 查看参数。到“策略 → 事件研究”选择 `ma_reclaim`，在获准运行后核对 5/10/20、SMA20 定义、实际 asof、有效 n、未成熟/缺失和 caveats；不可用定义不能伪装为零样本成功。网络/数据库失败不应被视为空库或全绿结果；UI 显示须与原始响应一起验收。

## 调度与运行记录

`event_study` **无默认调度行**，不是“系统每天自动跑”。是否运行取决于 `scheduled_jobs` 和服务级调度开关，本轮不启用或更改。普通任务报告在“工具 → 运行记录”或 `GET /api/jobs/reports?task=event_study` 查看；缓存写入属于事件研究服务路径，不能将任务报告与缓存混为一谈。调度/通知配置见 [说明](scheduling-and-notifications.md)。

手动验收前应在可合法连接的环境只读确认 schema、真实记录覆盖、来源日期/版本及旧输入隔离。015 的真实迁移、真实任务运行、缓存写入和通知均需另行授权；可信历史输入与运行验收完成后，仍须独立处理研究 Gate 的统计前置条件。
