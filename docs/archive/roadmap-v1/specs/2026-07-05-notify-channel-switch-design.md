# 通知渠道切换（Discord / 邮件）设计

日期：2026-07-05
状态：已与用户确认设计，待实现

## 背景与动机

当前通知模块（`investment_assistant/notify/`）只支持 Discord webhook：`dispatch()` 按任务（metrics/filings/scores）映射到三个 Discord 频道（daily/earnings/signals），模板层直接产出 Discord embed dict。

动机：

1. Discord 访问不稳定/不方便，通知到达不可靠；
2. 希望架构上支持渠道切换的灵活性——保留 Discord 实现，可全局切换到邮件。

用户决策（brainstorming 确认）：

- **保留 Discord，新增邮件渠道**，全局单选切换（所有任务走同一渠道）；
- 邮件通过 **Gmail SMTP** 发送到 Outlook 收件箱；
- 邮件正文用**简单 HTML**，主题行按「任务类型 + 日期」区分；
- 采用方案 A：轻量渠道抽象（渠道中立消息模型 + 各渠道渲染器/发送器）。

## 架构总览

核心思路：**内容与渠道解耦**。模板层产出渠道中立的 `Notification` 消息模型，各渠道负责「渲染 + 发送」，`dispatch()` 按全局配置 `channel` 选择路径：

```
任务 (metrics/filings/scores)
        │ summary dict
        ▼
templates.py  ──产出──►  Notification(title, color, fields, footer)
        │
   dispatch() 读 notify_cfg.channel ── "discord" ─► render_discord() → DiscordClient.send()
        │
        └──────────────────────────── "email" ───► render_email() → EmailClient.send()
```

## 组件设计

### 1. 消息模型（新增 `notify/message.py`）

```python
@dataclass(frozen=True)
class NotifyField:
    name: str
    value: str
    inline: bool = False

@dataclass(frozen=True)
class Notification:
    title: str                 # 如 "📄 财报 · 2026-07-05"
    color: int                 # Discord 用作 embed 色；邮件用作标题条强调色
    fields: list[NotifyField]
    footer: str                # 如 "earning-agent • 2026-07-05"
```

### 2. 模板层（重写 `notify/templates.py`）

- 在用的 3 个 builder（`metrics_summary` / `filings_digest` / `scores_summary`）改为返回 `Notification`；内容逻辑（截断条数、emoji、回补分支、date_label）原样保留。
- 删除仅被 `discord.py` `__main__` 使用的 3 个 builder（`earnings_alert_embed` / `signal_alert_embed` / `daily_summary_embed`）；CLI 手动测试改用真实 builder + 假数据。
- `date_label_for()` 保留不变。

### 3. Discord 渠道（改造 `notify/discord.py`）

- 新增 `render_discord(notification) -> dict`：把 `Notification` 渲染为 embed payload，输出结构与现状逐字段一致（测试锁定，防回归）。
- `DiscordChannel` / `DiscordClient` 及其 `from_config` / `from_env` 不动。

### 4. 邮件渠道（新增 `notify/email.py`）

- `render_email(notification) -> (subject, html)`：
  - 主题行：`[Hermes] {title}`，即 `[Hermes] 📄 财报 · 2026-07-05`——任务类型靠 title 中的 emoji + 名称区分，支持收件箱按主题排序/搜索；
  - HTML：轻量内联样式（标题条用 `color`、字段名加粗、行列表用 `<ul>`），f-string 拼接 + `html.escape` 转义，不引入模板引擎。
- `EmailClient`：标准库 `smtplib.SMTP_SSL`，默认 `smtp.gmail.com:465`，timeout 10 秒；用户名默认取发件地址，密码从环境变量 `SMTP_PASSWORD`（Gmail 应用专用密码）读取，**绝不写入 DB**。

### 5. 分发层（改造 `notify/notifier.py`）

`dispatch(task, status, summary, notify_cfg, ...)` 流程：

1. `task_enabled.get(task) is False` → `{"sent": False, "reason": "task_disabled"}`（保留现状）；
2. 按 `notify_cfg.channel` 分支：
   - `"discord"`：沿用现状（`discord_enabled` 开关、`task_channels` 映射频道、`render_discord` + `DiscordClient`）；
   - `"email"`：前置检查（见错误处理），`render_email` + `EmailClient` 发送，邮件不需要 task→频道映射（单收件箱，主题行区分）；
3. 成功返回 `{"sent": True, "channel": "discord"|"email", ...}`；失败捕获异常结构化返回，不拖垮任务。

## 配置与存储

### NotifyConfig（`config.py`）

- 新增 `channel: str = "discord"`（取值 `"discord"` / `"email"`）；
- 新增 `email: dict`，默认 `{"from_addr": "", "to_addr": "", "host": "smtp.gmail.com", "port": 465}`；
- 删除从未使用的 `email_enabled` 字段。

### migration 012（`migrations/012_notify_channel.sql`）

010/011 已被占用，本次用 012：

```sql
ALTER TABLE notify_settings
  ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'discord',
  ADD COLUMN IF NOT EXISTS email   JSONB NOT NULL DEFAULT '{}'::jsonb;
```

### settings 服务（`services/settings.py`）与 db 层

- `db.get_notify_settings` / `update_notify_settings` 增加 `channel` / `email` 两列的读写（`email` 沿用 JSONB merge 语义）；
- `effective_notify_config`：合并 `channel`（标量覆盖）与 `email`（dict merge）；
- `read_notify_view`：返回 `channel`、`email`（地址明文返回，无敏感信息；密码只有环境变量，不出现在视图中）；
- `update_notify`：透传 `channel` / `email`；
- `test_notify_channel`：请求 `channel: "email"` 时发一封测试邮件（也是验证部署环境 SMTP 出网连通性的手段）；Discord 测试路径不变；
- `_ENV_KEYS` 增加 `SMTP_PASSWORD`，用于环境状态展示。

### API 路由（`api/routes/settings.py`）

现有三个端点（GET/PATCH `/api/settings/notify`、POST `/api/settings/notify/test`）签名不变，仅 payload 语义扩展（`channel` / `email` 字段、test 支持 `channel: "email"`）。

## 前端（`web/src/routes/Settings.svelte`）

- 通知设置区顶部加渠道单选：Discord / 邮件；
- 选「邮件」时显示：发件地址、收件地址输入框 + 「发送测试邮件」按钮 + `SMTP_PASSWORD` 是否已配置的状态提示（来自现有 env status 接口）；
- Discord 区块维持现状；
- `web/src/lib/api.ts` 对应类型/请求同步扩展。

## 错误处理

沿用「通知失败不拖垮任务」约定，`dispatch` 捕获所有异常并结构化返回：

| 场景 | 返回 |
|---|---|
| 任务开关关闭 | `{"sent": False, "reason": "task_disabled"}` |
| Discord 路径：`discord_enabled=False` / 无频道映射 | 现状保留（`discord_disabled` / `no_channel`） |
| 邮件路径：`SMTP_PASSWORD` 未配置 | `{"sent": False, "reason": "email_no_password"}` |
| 邮件路径：收件地址为空 | `{"sent": False, "reason": "email_no_recipient"}` |
| 发送异常 | `{"sent": False, "reason": "send_failed: ..."}` |

测试端点错误信息不含敏感内容（SMTP 异常不携带密码；Discord 路径保留 webhook URL 脱敏）。

## 测试策略

- **模板层**：3 个 builder 返回的 `Notification` 内容断言（改造现有 case）；
- **render_discord**：输出与迁移前 embed 结构逐字段一致（防回归快照）；
- **render_email**：主题行格式、HTML 含关键内容、HTML 转义正确；
- **EmailClient**：mock SMTP，验证连接参数（host/port/timeout）与 MIME 组装（From/To/Subject/HTML part）；
- **dispatch**：渠道选择分支覆盖（discord / email / email 缺密码 / email 缺收件人 / task_disabled）；
- **settings 服务**：channel/email 的存取与 merge 语义；
- **migration 012**：按现有迁移测试风格补一条。

## 风险与部署注意

- **Gmail SMTP 出网连通性**：若 Sealos 集群在国内区，`smtp.gmail.com:465` 可能不通。上线前先在 Settings 页用「发送测试邮件」验证；不通的备选是换 Outlook SMTP 或国内邮箱 SMTP 发件——渠道抽象不受影响，仅改 host/port/发件账号。
- **Gmail 应用专用密码**：需在 Google 账号开启两步验证后生成，部署时以 `SMTP_PASSWORD` 环境变量注入（Sealos 两进程均需注入，与 `DISCORD_WEBHOOK_*` 同层）。

## 范围外（YAGNI）

- 每任务独立渠道、多渠道同时发送；
- 邮件模板引擎、富 HTML 主题；
- 通知重试/队列；
- Telegram/飞书等其他渠道（本设计的抽象为其留了扩展点，但不实现）。
