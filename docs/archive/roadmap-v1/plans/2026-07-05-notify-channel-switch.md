# 通知渠道切换（Discord / 邮件）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通知模块支持全局单选切换 Discord / 邮件（Gmail SMTP → Outlook，简单 HTML），内容与渠道解耦。

**Architecture:** 模板层产出渠道中立的 `Notification` 消息模型；Discord 与邮件各自实现「渲染器 + 客户端」；`dispatch()` 按 `NotifyConfig.channel` 选路。配置存 `notify_settings` 表（migration 012 新增 `channel` / `email` 列），SMTP 密码只走环境变量 `SMTP_PASSWORD`。

**Tech Stack:** Python 3.11（标准库 `smtplib` / `email.mime`，零新依赖）、FastAPI、PostgreSQL JSONB、Svelte 5 runes。

**Spec:** `docs/superpowers/specs/2026-07-05-notify-channel-switch-design.md`

## Global Constraints

- 通知失败不拖垮任务：`dispatch` 捕获所有异常，结构化返回 `{"sent": False, "reason": ...}`。
- SMTP 密码只从环境变量 `SMTP_PASSWORD` 读取，绝不写入 DB、不出现在 API 响应中。
- 邮件主题前缀固定 `[Hermes]`，主题行 = `[Hermes] {Notification.title}`。
- migration 编号用 **012**（010/011 已被占用）。
- Python 测试命令：`.venv/bin/pytest`（在仓库根目录运行）；前端测试：`cd web && npm test`。
- 中文注释/文案风格与现有代码一致；ruff line-length 120。

---

### Task 1: 消息模型 + Discord 渲染器

**Files:**
- Create: `investment_assistant/notify/message.py`
- Modify: `investment_assistant/notify/discord.py`（新增 `render_discord`，其余不动）
- Test: `tests/test_notify_discord.py`

**Interfaces:**
- Consumes: 无（本任务是最底层）。
- Produces:
  - `Notification(title: str, color: int, fields: list[NotifyField], footer: str)`（frozen dataclass）
  - `NotifyField(name: str, value: str, inline: bool = False)`（frozen dataclass）
  - `render_discord(notification: Notification) -> dict`：返回 Discord webhook embed payload。

- [ ] **Step 1: 写失败测试**

在 `tests/test_notify_discord.py` 末尾追加：

```python
def test_render_discord_matches_embed_shape():
    from investment_assistant.notify.discord import render_discord
    from investment_assistant.notify.message import Notification, NotifyField

    n = Notification(
        title="📄 财报 · 2026-07-03",
        color=15844367,
        fields=[NotifyField("新提交 (1)", "• **TEST** 10-Q — 2026-07-03")],
        footer="earning-agent • 2026-07-03",
    )
    payload = render_discord(n)
    embed = payload["embeds"][0]
    assert embed["title"] == "📄 财报 · 2026-07-03"
    assert embed["color"] == 15844367
    assert embed["fields"] == [{"name": "新提交 (1)", "value": "• **TEST** 10-Q — 2026-07-03", "inline": False}]
    assert embed["footer"] == {"text": "earning-agent • 2026-07-03"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notify_discord.py::test_render_discord_matches_embed_shape -v`
Expected: FAIL（`ModuleNotFoundError: investment_assistant.notify.message` 或 `ImportError: render_discord`）

- [ ] **Step 3: 实现**

新建 `investment_assistant/notify/message.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NotifyField:
    name: str
    value: str
    inline: bool = False


@dataclass(frozen=True)
class Notification:
    """渠道中立的通知消息模型；各渠道自行渲染。"""

    title: str
    color: int
    fields: list[NotifyField] = field(default_factory=list)
    footer: str = ""
```

在 `investment_assistant/notify/discord.py` 顶部加导入，并在 `DiscordClient` 类定义之后加渲染函数：

```python
from investment_assistant.notify.message import Notification
```

```python
def render_discord(notification: Notification) -> dict:
    return {
        "embeds": [{
            "title": notification.title,
            "color": notification.color,
            "fields": [
                {"name": f.name, "value": f.value, "inline": f.inline}
                for f in notification.fields
            ],
            "footer": {"text": notification.footer},
        }]
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_notify_discord.py -v`
Expected: 全部 PASS（含原有 3 个用例）

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/notify/message.py investment_assistant/notify/discord.py tests/test_notify_discord.py
git commit -m "feat(notify): 渠道中立消息模型 Notification + Discord 渲染器"
```

---

### Task 2: 模板层中立化（templates 重写 + notifier/CLI 切换）

**Files:**
- Modify: `investment_assistant/notify/templates.py`（整文件重写）
- Modify: `investment_assistant/notify/notifier.py`（整文件重写，本任务保持 Discord-only 语义）
- Modify: `investment_assistant/notify/discord.py`（仅 `__main__` 块）
- Test: `tests/test_notifier.py`（整文件重写）

**Interfaces:**
- Consumes: Task 1 的 `Notification` / `NotifyField` / `render_discord`。
- Produces（Task 5/7 依赖）:
  - `templates.metrics_summary(summary: dict, *, date_label: str | None = None) -> Notification`
  - `templates.filings_digest(summary: dict, *, date_label: str | None = None) -> Notification`
  - `templates.scores_summary(summary: dict, *, date_label: str | None = None) -> Notification`
  - `templates.date_label_for(start: date | None, end: date | None) -> str`（签名不变）
  - `notifier._build_notification(task, status, summary, *, target_start_date, target_end_date) -> Notification`
  - 旧的 `*_embed` builder 全部删除（含 `earnings_alert_embed` / `signal_alert_embed` / `daily_summary_embed`）。

注意：本任务的 `dispatch` 返回值与现状完全一致（`{"sent": True, "channel": "daily"}` 等），渠道分支留给 Task 5。

- [ ] **Step 1: 重写测试文件**

`tests/test_notifier.py` 整文件替换为：

```python
from datetime import date

from investment_assistant.config import NotifyConfig
from investment_assistant.notify import notifier, templates


class FakeClient:
    def __init__(self):
        self.sent = []

    def send(self, channel, payload):
        self.sent.append((channel, payload))


def test_dispatch_skips_when_globally_disabled():
    out = notifier.dispatch("metrics", "success", {}, NotifyConfig(discord_enabled=False), client=FakeClient())
    assert out["sent"] is False and out["reason"] == "discord_disabled"


def test_dispatch_skips_when_task_disabled():
    cfg = NotifyConfig(task_enabled={"metrics": False})
    out = notifier.dispatch("metrics", "success", {}, cfg, client=FakeClient())
    assert out["sent"] is False and out["reason"] == "task_disabled"


def test_dispatch_routes_to_channel():
    client = FakeClient()
    summary = {"market_status": "green", "vix": 15.0, "tickers": [{"ticker": "NVDA", "trend_state": "uptrend"}]}
    out = notifier.dispatch("metrics", "success", summary, NotifyConfig(), client=client)
    assert out["sent"] is True and out["channel"] == "daily"
    assert client.sent and "embeds" in client.sent[0][1]


def test_dispatch_send_failure_is_structured():
    class Boom(FakeClient):
        def send(self, channel, payload):
            raise RuntimeError("network")

    out = notifier.dispatch("filings", "success", {"filings": []}, NotifyConfig(), client=Boom())
    assert out["sent"] is False and "send_failed" in out["reason"]


def test_date_label_single_range_and_default():
    assert templates.date_label_for(date(2026, 7, 3), date(2026, 7, 3)) == "2026-07-03"
    assert templates.date_label_for(date(2026, 6, 1), date(2026, 6, 30)) == "2026-06-01 ~ 2026-06-30"
    assert templates.date_label_for(None, None) == date.today().isoformat()


def test_filings_digest_uses_actual_date_label():
    n = templates.filings_digest(
        {"downloaded_count": 0, "filings": []}, date_label="2026-06-01 ~ 2026-06-30")
    assert n.title == "📄 财报 · 2026-06-01 ~ 2026-06-30"
    assert n.fields[0].name == "新提交 (0)"
    assert n.fields[0].value == "该日期无新财报"


def test_metrics_summary_renders_backfill_days():
    summary = {"days": [
        {"date": "2026-06-01", "market_status": "green"},
        {"date": "2026-06-02", "error": "no data"},
    ]}
    n = templates.metrics_summary(summary, date_label="2026-06-01 ~ 2026-06-02")
    assert "回补" in n.fields[0].name
    assert "2026-06-01" in n.fields[0].value and "GREEN" in n.fields[0].value
    assert "no data" in n.fields[0].value


def test_metrics_summary_renders_watchlist():
    summary = {"market_status": "green", "vix": 15.0, "tickers": [{"ticker": "NVDA", "trend_state": "uptrend"}]}
    n = templates.metrics_summary(summary, date_label="2026-07-03")
    assert n.title == "🗓 每日指标 · 2026-07-03"
    assert n.fields[0].name == "市场环境" and "GREEN | VIX 15.0" == n.fields[0].value
    assert "**NVDA** — uptrend" in n.fields[1].value


def test_scores_summary_renders_backfill_days():
    summary = {"days": [{"date": "2026-06-01", "count": 4, "failures": 0}]}
    n = templates.scores_summary(summary, date_label="2026-06-01")
    assert n.title == "📈 策略评分 · 2026-06-01"
    assert "4" in n.fields[0].value


def test_dispatch_passes_date_label_into_embed():
    client = FakeClient()
    notifier.dispatch(
        "filings", "success", {"downloaded_count": 1, "filings": []}, NotifyConfig(),
        client=client, target_start_date=date(2026, 7, 3), target_end_date=date(2026, 7, 3),
    )
    assert client.sent[0][1]["embeds"][0]["title"] == "📄 财报 · 2026-07-03"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notifier.py -v`
Expected: FAIL（`AttributeError: module ... has no attribute 'filings_digest'` 等）

- [ ] **Step 3: 重写 templates.py**

`investment_assistant/notify/templates.py` 整文件替换为：

```python
from datetime import date

from investment_assistant.notify.message import Notification, NotifyField


def date_label_for(start: date | None, end: date | None) -> str:
    if start is None:
        return date.today().isoformat()
    if end is None or end == start:
        return start.isoformat()
    return f"{start.isoformat()} ~ {end.isoformat()}"


def _footer() -> str:
    return f"earning-agent • {date.today().isoformat()}"


def metrics_summary(summary: dict, *, date_label: str | None = None) -> Notification:
    label = date_label or date.today().isoformat()
    days = summary.get("days")
    if days:
        rows = "\n".join(
            f"• {d.get('date')} — " + (f"❌ {d.get('error')}" if d.get("error")
                                       else str(d.get("market_status", "?")).upper())
            for d in days[:15]
        ) or "无"
        fields = [NotifyField(f"回补 ({len(days)} 天)", rows)]
    else:
        status = str(summary.get("market_status", "?")).upper()
        vix = summary.get("vix")
        tickers = summary.get("tickers", [])
        rows = "\n".join(f"• **{t.get('ticker')}** — {t.get('trend_state', '?')}" for t in tickers[:10]) or "无"
        fields = [
            NotifyField("市场环境", f"{status} | VIX {vix}"),
            NotifyField(f"关注列表 ({len(tickers)})", rows),
        ]
    return Notification(title=f"🗓 每日指标 · {label}", color=3447003, fields=fields, footer=_footer())


def filings_digest(summary: dict, *, date_label: str | None = None) -> Notification:
    label = date_label or date.today().isoformat()
    filings = summary.get("filings", [])
    rows = "\n".join(
        f"• **{f.get('ticker')}** {f.get('form')} — {f.get('filing_date') or f.get('filed_at', '')}"
        for f in filings[:15]
    ) or "该日期无新财报"
    fields = [NotifyField(f"新提交 ({summary.get('downloaded_count', 0)})", rows)]
    return Notification(title=f"📄 财报 · {label}", color=15844367, fields=fields, footer=_footer())


def scores_summary(summary: dict, *, date_label: str | None = None) -> Notification:
    label = date_label or date.today().isoformat()
    days = summary.get("days")
    if days:
        listing = "\n".join(
            f"• {d.get('date')} — " + (f"❌ {d.get('error')}" if d.get("error")
                                       else f"{d.get('count', 0)} 条评分")
            for d in days[:15]
        ) or "无"
        fields = [NotifyField(f"回补 ({len(days)} 天)", listing)]
    else:
        rows = summary.get("rows", [])
        listing = "\n".join(f"• **{r.get('ticker')}** — {r.get('score')}" for r in rows[:10]) or "无评分"
        fields = [NotifyField(f"评分 ({len(rows)})", listing)]
    return Notification(title=f"📈 策略评分 · {label}", color=10070709, fields=fields, footer=_footer())
```

（`earnings_alert_embed` / `signal_alert_embed` / `daily_summary_embed` 及 `*_embed` 全部删除。）

- [ ] **Step 4: 重写 notifier.py**

`investment_assistant/notify/notifier.py` 整文件替换为（本任务保持 Discord-only 语义与返回值）：

```python
from __future__ import annotations

from typing import Any

from investment_assistant.notify.discord import DiscordChannel, DiscordClient, render_discord
from investment_assistant.notify.message import Notification
from investment_assistant.notify.templates import (
    date_label_for,
    filings_digest,
    metrics_summary,
    scores_summary,
)

_BUILDERS = {
    "metrics": metrics_summary,
    "filings": filings_digest,
    "scores": scores_summary,
}


def _build_notification(task: str, status: str, summary: dict[str, Any], *,
                        target_start_date=None, target_end_date=None) -> Notification:
    builder = _BUILDERS.get(task)
    if builder:
        return builder(summary, date_label=date_label_for(target_start_date, target_end_date))
    return Notification(title=f"[{task}] {status}", color=9807270, fields=[], footer="")


def dispatch(task: str, status: str, summary: dict[str, Any], notify_cfg, *,
             client=None, target_start_date=None, target_end_date=None) -> dict[str, Any]:
    if not notify_cfg.discord_enabled:
        return {"sent": False, "reason": "discord_disabled"}
    if notify_cfg.task_enabled.get(task) is False:
        return {"sent": False, "reason": "task_disabled"}
    channel_name = notify_cfg.task_channels.get(task)
    if not channel_name:
        return {"sent": False, "reason": "no_channel"}

    notification = _build_notification(task, status, summary,
                                       target_start_date=target_start_date, target_end_date=target_end_date)
    try:
        cli = client or DiscordClient.from_config(notify_cfg)
        cli.send(DiscordChannel(channel_name), render_discord(notification))
        return {"sent": True, "channel": channel_name}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}
```

（行为变化说明：未知 task 的兜底从 `{"content": ...}` 变为渲染一个只有标题的 embed，无测试依赖旧行为。）

- [ ] **Step 5: 更新 discord.py 的 `__main__` 块**

替换 `investment_assistant/notify/discord.py` 中整个 `if __name__ == "__main__":` 块为：

```python
if __name__ == "__main__":
    import argparse

    from investment_assistant.notify.templates import filings_digest, metrics_summary, scores_summary

    parser = argparse.ArgumentParser(description="发送测试消息到指定 Discord 频道")
    parser.add_argument(
        "--channel",
        choices=["earnings", "signals", "daily"],
        default="earnings",
        help="目标频道（默认：earnings）",
    )
    args = parser.parse_args()

    client = DiscordClient.from_env()
    ch = DiscordChannel(args.channel)

    if ch == DiscordChannel.EARNINGS:
        n = filings_digest({"downloaded_count": 1, "filings": [
            {"ticker": "TEST", "form": "10-Q", "filing_date": "2026-07-05"}]})
    elif ch == DiscordChannel.SIGNALS:
        n = scores_summary({"rows": [{"ticker": "TEST", "score": 88}]})
    else:
        n = metrics_summary({"market_status": "green", "vix": 15.0,
                             "tickers": [{"ticker": "TEST", "trend_state": "uptrend"}]})
    client.send(ch, render_discord(n))
    print(f"✅ 测试消息已发送至 #{args.channel}")
```

- [ ] **Step 6: 运行测试确认通过 + 全量回归**

Run: `.venv/bin/pytest tests/test_notifier.py tests/test_notify_discord.py -v`
Expected: 全部 PASS

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS（确认没有其他模块引用被删的 `*_embed`）

- [ ] **Step 7: Commit**

```bash
git add investment_assistant/notify/templates.py investment_assistant/notify/notifier.py investment_assistant/notify/discord.py tests/test_notifier.py
git commit -m "refactor(notify): 模板层产出渠道中立 Notification，Discord 渲染下沉到渠道层"
```

---

### Task 3: NotifyConfig 增加 channel / email 配置

**Files:**
- Modify: `investment_assistant/config.py`（`NotifyConfig` dataclass，41-53 行附近）
- Test: `tests/test_config_notify.py`

**Interfaces:**
- Consumes: 无。
- Produces（Task 4/5/6/7 依赖）:
  - `NotifyConfig.channel: str = "discord"`（取值 `"discord"` / `"email"`）
  - `NotifyConfig.email: dict[str, Any]`，默认 `{"from_addr": "", "to_addr": "", "host": "smtp.gmail.com", "port": 465}`
  - `email_enabled` 字段删除。

- [ ] **Step 1: 写失败测试**

修改 `tests/test_config_notify.py` 的 `test_notify_config_defaults`，并追加一个用例：

```python
def test_notify_config_defaults():
    cfg = _config_from_dict({})
    assert cfg.notify.channel == "discord"
    assert cfg.notify.discord_enabled is True
    assert cfg.notify.email["host"] == "smtp.gmail.com"
    assert cfg.notify.email["port"] == 465
    assert cfg.notify.task_channels["metrics"] == "daily"
    assert cfg.notify.task_channels["filings"] == "earnings"
    assert cfg.notify.task_enabled["metrics"] is True
    assert not hasattr(cfg.notify, "email_enabled")


def test_notify_config_channel_override_from_dict():
    cfg = _config_from_dict({"notify": {
        "channel": "email",
        "email": {"from_addr": "me@gmail.com", "to_addr": "you@outlook.com"},
    }})
    assert cfg.notify.channel == "email"
    assert cfg.notify.email["to_addr"] == "you@outlook.com"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_config_notify.py -v`
Expected: FAIL（`AttributeError: 'NotifyConfig' object has no attribute 'channel'`）

- [ ] **Step 3: 修改 NotifyConfig**

`investment_assistant/config.py` 中的 `NotifyConfig` 替换为（确认文件顶部已有 `from typing import Any`，没有则补上）：

```python
@dataclass(frozen=True)
class NotifyConfig:
    """Notification channel toggles for the Hermes capability layer."""

    channel: str = "discord"  # "discord" | "email"（全局单选）
    discord_enabled: bool = True
    webhooks: dict[str, str] = field(default_factory=dict)
    email: dict[str, Any] = field(default_factory=lambda: {
        "from_addr": "", "to_addr": "", "host": "smtp.gmail.com", "port": 465,
    })
    task_channels: dict[str, str] = field(
        default_factory=lambda: {"metrics": "daily", "filings": "earnings", "scores": "signals"}
    )
    task_enabled: dict[str, bool] = field(
        default_factory=lambda: {"metrics": True, "filings": True, "scores": True}
    )
```

（`email_enabled: bool = True` 一行删除——全项目无引用。）

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_config_notify.py tests/test_config.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/config.py tests/test_config_notify.py
git commit -m "feat(config): NotifyConfig 增加 channel/email，移除未使用的 email_enabled"
```

---

### Task 4: 邮件渠道（render_email + EmailClient）

**Files:**
- Create: `investment_assistant/notify/email.py`
- Test: `tests/test_notify_email.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `Notification` / `NotifyField`；Task 3 的 `NotifyConfig.email`。
- Produces（Task 5/7 依赖）:
  - `render_email(notification: Notification) -> tuple[str, str]`：返回 `(subject, html_body)`，subject 前缀 `[Hermes]`。
  - `EmailClient(*, host, port, username, password, from_addr, to_addr, timeout=10)`，方法 `send(subject: str, html_body: str) -> None`（失败抛异常）。
  - `EmailClient.from_config(notify_cfg) -> EmailClient`：从 `notify_cfg.email` + 环境变量 `SMTP_PASSWORD` 构造，username 默认取 `from_addr`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_notify_email.py`：

```python
from unittest.mock import patch

from investment_assistant.notify.email import EmailClient, render_email
from investment_assistant.notify.message import Notification, NotifyField


def _notification():
    return Notification(
        title="📄 财报 · 2026-07-03",
        color=15844367,
        fields=[NotifyField("新提交 (2)", "• **TEST** 10-Q — 2026-07-03\n• <tag> & escape")],
        footer="earning-agent • 2026-07-03",
    )


def test_render_email_subject_has_prefix_and_title():
    subject, _ = render_email(_notification())
    assert subject == "[Hermes] 📄 财报 · 2026-07-03"


def test_render_email_html_fields_bold_and_escaped():
    _, body = render_email(_notification())
    assert "<strong>新提交 (2)</strong>" in body
    assert "<b>TEST</b>" in body                # **bold** → <b>
    assert "&lt;tag&gt; &amp; escape" in body   # HTML 转义
    assert "#f1c40f" in body                    # color 15844367 → 强调色 hex
    assert "earning-agent • 2026-07-03" in body


def test_render_email_strips_bullet_prefix_into_list_items():
    _, body = render_email(_notification())
    assert "<li>• " not in body  # "• " 前缀已剥离，由 <li> 承担项目符号


def test_email_client_sends_via_smtp_ssl():
    client = EmailClient(host="smtp.gmail.com", port=465, username="me@gmail.com",
                         password="app-pass", from_addr="me@gmail.com", to_addr="you@outlook.com")
    with patch("investment_assistant.notify.email.smtplib.SMTP_SSL") as mock_ssl:
        smtp = mock_ssl.return_value.__enter__.return_value
        client.send("[Hermes] 测试", "<p>hi</p>")
        mock_ssl.assert_called_once_with("smtp.gmail.com", 465, timeout=10)
        smtp.login.assert_called_once_with("me@gmail.com", "app-pass")
        from_addr, to_addrs, raw = smtp.sendmail.call_args[0]
        assert from_addr == "me@gmail.com" and to_addrs == ["you@outlook.com"]
        assert "Subject:" in raw


def test_email_client_from_config_reads_env_password(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    from investment_assistant.config import NotifyConfig
    cfg = NotifyConfig(email={"from_addr": "me@gmail.com", "to_addr": "you@outlook.com"})
    client = EmailClient.from_config(cfg)
    assert client._password == "secret"
    assert client._username == "me@gmail.com"
    assert client._host == "smtp.gmail.com" and client._port == 465  # 缺省回退
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notify_email.py -v`
Expected: FAIL（`ModuleNotFoundError: investment_assistant.notify.email`）

- [ ] **Step 3: 实现 email.py**

新建 `investment_assistant/notify/email.py`：

```python
from __future__ import annotations

import html
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from investment_assistant.notify.message import Notification

SUBJECT_PREFIX = "[Hermes]"


def _line_html(line: str) -> str:
    escaped = html.escape(line.removeprefix("• "))  # 项目符号由 <li> 承担
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def render_email(notification: Notification) -> tuple[str, str]:
    subject = f"{SUBJECT_PREFIX} {notification.title}"
    accent = f"#{notification.color:06x}"
    parts = [
        f'<div style="font-family:sans-serif;border-left:4px solid {accent};padding:8px 16px;">',
        f'<h2 style="margin:0 0 12px;">{html.escape(notification.title)}</h2>',
    ]
    for f in notification.fields:
        items = "".join(f"<li>{_line_html(line)}</li>" for line in f.value.splitlines())
        parts.append(f'<p style="margin:12px 0 4px;"><strong>{html.escape(f.name)}</strong></p>')
        parts.append(f'<ul style="margin:0;padding-left:20px;">{items}</ul>')
    if notification.footer:
        parts.append(f'<p style="color:#888;font-size:12px;margin-top:16px;">{html.escape(notification.footer)}</p>')
    parts.append("</div>")
    return subject, "".join(parts)


class EmailClient:
    def __init__(self, *, host: str, port: int, username: str, password: str,
                 from_addr: str, to_addr: str, timeout: int = 10):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_addr = from_addr
        self._to_addr = to_addr
        self._timeout = timeout

    def send(self, subject: str, html_body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_addr
        msg["To"] = self._to_addr
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout) as smtp:
            smtp.login(self._username, self._password)
            smtp.sendmail(self._from_addr, [self._to_addr], msg.as_string())

    @classmethod
    def from_config(cls, notify_cfg) -> "EmailClient":
        email = notify_cfg.email or {}
        from_addr = email.get("from_addr", "")
        return cls(
            host=email.get("host") or "smtp.gmail.com",
            port=int(email.get("port") or 465),
            username=from_addr,
            password=os.environ.get("SMTP_PASSWORD", ""),  # 密码只走环境变量，不进 DB
            from_addr=from_addr,
            to_addr=email.get("to_addr", ""),
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_notify_email.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/notify/email.py tests/test_notify_email.py
git commit -m "feat(notify): 邮件渠道——render_email 简单 HTML + EmailClient (Gmail SMTP_SSL)"
```

---

### Task 5: dispatch 渠道分支

**Files:**
- Modify: `investment_assistant/notify/notifier.py`（整文件重写）
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: Task 2 的 `_build_notification` 与 builders；Task 4 的 `render_email` / `EmailClient`；Task 3 的 `NotifyConfig.channel` / `.email`。
- Produces（`_harness.py` 调用方约定，签名不变）:
  - `dispatch(task, status, summary, notify_cfg, *, client=None, target_start_date=None, target_end_date=None) -> dict`
  - 返回值约定：成功 discord → `{"sent": True, "channel": "discord", "discord_channel": "<daily|earnings|signals>"}`；成功 email → `{"sent": True, "channel": "email"}`；失败 → `{"sent": False, "reason": "<task_disabled|discord_disabled|no_channel|email_no_password|email_no_recipient|send_failed: ...>"}`。
  - 检查顺序变化：`task_enabled` 提到最前（渠道无关），`discord_enabled` 只在 Discord 分支内生效。

- [ ] **Step 1: 写失败测试**

修改 `tests/test_notifier.py`：`test_dispatch_routes_to_channel` 的断言改为：

```python
    assert out["sent"] is True and out["channel"] == "discord" and out["discord_channel"] == "daily"
```

并在文件末尾追加：

```python
class FakeEmailClient:
    def __init__(self):
        self.sent = []

    def send(self, subject, html_body):
        self.sent.append((subject, html_body))


def test_dispatch_email_channel_sends_with_subject():
    client = FakeEmailClient()
    cfg = NotifyConfig(channel="email", email={"from_addr": "a@gmail.com", "to_addr": "b@outlook.com"})
    out = notifier.dispatch("filings", "success", {"downloaded_count": 0, "filings": []}, cfg,
                            client=client, target_start_date=date(2026, 7, 3), target_end_date=date(2026, 7, 3))
    assert out == {"sent": True, "channel": "email"}
    assert client.sent and client.sent[0][0] == "[Hermes] 📄 财报 · 2026-07-03"


def test_dispatch_email_requires_password(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    cfg = NotifyConfig(channel="email", email={"from_addr": "a@gmail.com", "to_addr": "b@outlook.com"})
    out = notifier.dispatch("metrics", "success", {}, cfg)
    assert out == {"sent": False, "reason": "email_no_password"}


def test_dispatch_email_requires_recipient(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    cfg = NotifyConfig(channel="email", email={"from_addr": "a@gmail.com", "to_addr": ""})
    out = notifier.dispatch("metrics", "success", {}, cfg)
    assert out == {"sent": False, "reason": "email_no_recipient"}


def test_dispatch_email_send_failure_is_structured():
    class Boom(FakeEmailClient):
        def send(self, subject, html_body):
            raise RuntimeError("smtp down")

    cfg = NotifyConfig(channel="email", email={"from_addr": "a@gmail.com", "to_addr": "b@outlook.com"})
    out = notifier.dispatch("metrics", "success", {}, cfg, client=Boom())
    assert out["sent"] is False and "send_failed" in out["reason"]


def test_dispatch_task_disabled_wins_over_channel():
    cfg = NotifyConfig(channel="email", task_enabled={"metrics": False})
    out = notifier.dispatch("metrics", "success", {}, cfg, client=FakeEmailClient())
    assert out == {"sent": False, "reason": "task_disabled"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notifier.py -v`
Expected: 新增用例与 `test_dispatch_routes_to_channel` FAIL

- [ ] **Step 3: 重写 notifier.py**

整文件替换为：

```python
from __future__ import annotations

import os
from typing import Any

from investment_assistant.notify.discord import DiscordChannel, DiscordClient, render_discord
from investment_assistant.notify.email import EmailClient, render_email
from investment_assistant.notify.message import Notification
from investment_assistant.notify.templates import (
    date_label_for,
    filings_digest,
    metrics_summary,
    scores_summary,
)

_BUILDERS = {
    "metrics": metrics_summary,
    "filings": filings_digest,
    "scores": scores_summary,
}


def _build_notification(task: str, status: str, summary: dict[str, Any], *,
                        target_start_date=None, target_end_date=None) -> Notification:
    builder = _BUILDERS.get(task)
    if builder:
        return builder(summary, date_label=date_label_for(target_start_date, target_end_date))
    return Notification(title=f"[{task}] {status}", color=9807270, fields=[], footer="")


def dispatch(task: str, status: str, summary: dict[str, Any], notify_cfg, *,
             client=None, target_start_date=None, target_end_date=None) -> dict[str, Any]:
    if notify_cfg.task_enabled.get(task) is False:
        return {"sent": False, "reason": "task_disabled"}
    notification = _build_notification(task, status, summary,
                                       target_start_date=target_start_date, target_end_date=target_end_date)
    if notify_cfg.channel == "email":
        return _send_email(notification, notify_cfg, client=client)
    return _send_discord(task, notification, notify_cfg, client=client)


def _send_discord(task: str, notification: Notification, notify_cfg, *, client=None) -> dict[str, Any]:
    if not notify_cfg.discord_enabled:
        return {"sent": False, "reason": "discord_disabled"}
    channel_name = notify_cfg.task_channels.get(task)
    if not channel_name:
        return {"sent": False, "reason": "no_channel"}
    try:
        cli = client or DiscordClient.from_config(notify_cfg)
        cli.send(DiscordChannel(channel_name), render_discord(notification))
        return {"sent": True, "channel": "discord", "discord_channel": channel_name}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}


def _send_email(notification: Notification, notify_cfg, *, client=None) -> dict[str, Any]:
    if client is None:  # 前置检查只针对真实客户端；测试注入的 fake 自带配置
        if not os.environ.get("SMTP_PASSWORD"):
            return {"sent": False, "reason": "email_no_password"}
        if not (notify_cfg.email or {}).get("to_addr"):
            return {"sent": False, "reason": "email_no_recipient"}
        client = EmailClient.from_config(notify_cfg)
    subject, html_body = render_email(notification)
    try:
        client.send(subject, html_body)
        return {"sent": True, "channel": "email"}
    except Exception as exc:  # 通知失败不拖垮任务；结构化返回
        return {"sent": False, "reason": f"send_failed: {exc}"}
```

- [ ] **Step 4: 运行测试确认通过 + 全量回归**

Run: `.venv/bin/pytest tests/test_notifier.py -v`
Expected: 全部 PASS

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS（`test_harness.py` 等对 dispatch 返回值无 `channel == "daily"` 依赖；若有失败按新返回值约定修正断言）

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/notify/notifier.py tests/test_notifier.py
git commit -m "feat(notify): dispatch 按 NotifyConfig.channel 全局切换 Discord/邮件"
```

---

### Task 6: migration 012 + db 读写扩展

**Files:**
- Create: `migrations/012_notify_channel.sql`
- Modify: `investment_assistant/db.py`（`get_notify_settings` / `update_notify_settings`，397-423 行附近）
- Test: `tests/test_db_sql.py`（追加迁移用例）、`tests/test_notify_settings_repository.py`（新建）

**Interfaces:**
- Consumes: Task 3 的字段语义（channel 标量、email dict）。
- Produces（Task 7 依赖）:
  - `db.get_notify_settings(conn) -> dict`：新增键 `channel`（str）、`email`（dict）。
  - `db.update_notify_settings(conn, *, discord_enabled=None, webhooks=None, task_channels=None, task_enabled=None, channel=None, email=None) -> None`：`channel` 整列覆盖，`email` JSONB merge（`||`）。

- [ ] **Step 1: 写失败测试**

`tests/test_db_sql.py` 末尾追加：

```python
def test_notify_channel_migration():
    sql = Path("migrations/012_notify_channel.sql").read_text()
    assert "ALTER TABLE notify_settings" in sql
    assert "channel TEXT NOT NULL DEFAULT 'discord'" in sql
    assert "email" in sql and "JSONB" in sql and "'{}'::jsonb" in sql
```

新建 `tests/test_notify_settings_repository.py`：

```python
from investment_assistant import db


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConn:
    def __init__(self, rows=()):
        self.cur = FakeCursor(list(rows))
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


def test_get_notify_settings_returns_channel_and_email():
    row = (True, {}, {}, {}, "email", {"to_addr": "you@outlook.com"})
    out = db.get_notify_settings(FakeConn(rows=[row]))
    assert out["channel"] == "email"
    assert out["email"] == {"to_addr": "you@outlook.com"}


def test_update_notify_settings_writes_channel_scalar_and_email_merge():
    conn = FakeConn()
    db.update_notify_settings(conn, channel="email", email={"to_addr": "you@outlook.com"})
    sql, params = conn.cur.executed[0]
    assert "channel = %(channel)s" in sql
    assert "email = email || %(email)s::jsonb" in sql
    assert params["channel"] == "email"
    assert "you@outlook.com" in params["email"]
    assert conn.committed is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_db_sql.py::test_notify_channel_migration tests/test_notify_settings_repository.py -v`
Expected: FAIL（迁移文件不存在；`update_notify_settings` 不接受 `channel` 参数）

- [ ] **Step 3: 实现**

新建 `migrations/012_notify_channel.sql`：

```sql
-- 通知渠道全局单选（discord | email）+ 邮件配置（地址等非敏感项；SMTP 密码只走环境变量）
ALTER TABLE notify_settings
  ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'discord',
  ADD COLUMN IF NOT EXISTS email   JSONB NOT NULL DEFAULT '{}'::jsonb;
```

`investment_assistant/db.py` 中两个函数替换为：

```python
def get_notify_settings(conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT discord_enabled, webhooks, task_channels, task_enabled, channel, email "
            "FROM notify_settings WHERE id = 1"
        )
        rows = cur.fetchall()
    if not rows:
        return {}
    keys = ["discord_enabled", "webhooks", "task_channels", "task_enabled", "channel", "email"]
    return dict(zip(keys, rows[0]))


def update_notify_settings(
    conn, *, discord_enabled=None, webhooks=None, task_channels=None, task_enabled=None,
    channel=None, email=None,
) -> None:
    sets = ["updated_at = now()"]
    params: dict[str, Any] = {}
    if discord_enabled is not None:
        sets.append("discord_enabled = %(discord_enabled)s")
        params["discord_enabled"] = discord_enabled
    if channel is not None:
        sets.append("channel = %(channel)s")
        params["channel"] = channel
    for col, value in (("webhooks", webhooks), ("task_channels", task_channels),
                       ("task_enabled", task_enabled), ("email", email)):
        if value is not None:
            sets.append(f"{col} = {col} || %({col})s::jsonb")
            params[col] = json.dumps(value, ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE notify_settings SET {', '.join(sets)} WHERE id = 1", params)
    conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_db_sql.py tests/test_notify_settings_repository.py tests/test_migration_runner.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add migrations/012_notify_channel.sql investment_assistant/db.py tests/test_db_sql.py tests/test_notify_settings_repository.py
git commit -m "feat(db): notify_settings 增加 channel/email 列（migration 012）及读写支持"
```

---

### Task 7: settings 服务 + API 测试端点支持邮件

**Files:**
- Modify: `investment_assistant/services/settings.py`
- Modify: `investment_assistant/api/routes/settings.py`（仅 `test_notify` 一行）
- Test: `tests/test_settings_service.py`

**Interfaces:**
- Consumes: Task 3 的 `NotifyConfig`；Task 4 的 `EmailClient`；Task 6 的 db 读写。
- Produces（前端/harness 依赖）:
  - `effective_notify_config(base) -> NotifyConfig`：合并 `channel`（标量覆盖）与 `email`（dict merge）。
  - `read_notify_view() -> dict`：新增 `channel: str`、`email: dict`（地址明文，无密码）。
  - `update_notify(payload) -> dict`：接受 `channel`（校验取值）与 `email`（空值不覆盖）；非法 channel 返回 `{"updated": False, "error": "invalid channel"}`。
  - `test_notify_channel(channel, url=None, *, email=None, client=None) -> dict`：`channel == "email"` 时发测试邮件，`email` 参数可覆盖收发地址。
  - `read_env_status()` 包含 `SMTP_PASSWORD`。

- [ ] **Step 1: 写失败测试**

`tests/test_settings_service.py` 末尾追加：

```python
def test_effective_notify_config_overlays_channel_and_email(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(settings.db, "get_notify_settings", lambda conn: {
        "channel": "email", "email": {"to_addr": "you@outlook.com"},
    })
    out = settings.effective_notify_config(NotifyConfig())
    assert out.channel == "email"
    assert out.email["to_addr"] == "you@outlook.com"
    assert out.email["host"] == "smtp.gmail.com"  # 与基础默认合并


def test_read_notify_view_includes_channel_and_email(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    monkeypatch.setattr(settings.db, "get_notify_settings", lambda conn: {
        "channel": "email", "email": {"from_addr": "me@gmail.com", "to_addr": "you@outlook.com"},
    })
    view = settings.read_notify_view()
    assert view["channel"] == "email"
    assert view["email"]["to_addr"] == "you@outlook.com"


def test_update_notify_rejects_invalid_channel(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    out = settings.update_notify({"channel": "sms"})
    assert out == {"updated": False, "error": "invalid channel"}


def test_update_notify_passes_channel_and_email(monkeypatch):
    monkeypatch.setenv("INVESTMENT_ASSISTANT_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(settings, "_with_conn", lambda fn: fn("CONN"))
    captured = {}

    def fake_update(conn, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(settings.db, "update_notify_settings", fake_update)
    settings.update_notify({"channel": "email", "email": {"to_addr": "you@outlook.com", "from_addr": "  "}})
    assert captured["channel"] == "email"
    assert captured["email"] == {"to_addr": "you@outlook.com"}  # 空白值不覆盖


def test_test_notify_channel_email_uses_client():
    sent = []

    class FakeEmail:
        def send(self, subject, html_body):
            sent.append((subject, html_body))

    out = settings.test_notify_channel("email", client=FakeEmail())
    assert out["ok"] is True and sent and sent[0][0].startswith("[Hermes]")


def test_test_notify_channel_email_requires_password(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = settings.test_notify_channel("email", email={"to_addr": "you@outlook.com"})
    assert out["ok"] is False and "SMTP_PASSWORD" in out["error"]


def test_test_notify_channel_email_requires_recipient(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.delenv("INVESTMENT_ASSISTANT_DATABASE_URL", raising=False)
    out = settings.test_notify_channel("email")
    assert out["ok"] is False and "recipient" in out["error"]


def test_read_env_status_includes_smtp_password(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert settings.read_env_status()["SMTP_PASSWORD"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_settings_service.py -v`
Expected: 新增用例 FAIL（原有用例 PASS）

- [ ] **Step 3: 实现 settings.py 修改**

`investment_assistant/services/settings.py`：

顶部导入区加：

```python
from investment_assistant.notify.email import EmailClient
```

`_ENV_KEYS` 替换为：

```python
_ENV_KEYS = [
    "SEC_USER_AGENT",
    "INVESTMENT_ASSISTANT_DATABASE_URL",
    "DISCORD_WEBHOOK_EARNINGS",
    "DISCORD_WEBHOOK_SIGNALS",
    "DISCORD_WEBHOOK_DAILY",
    "SMTP_PASSWORD",
]
```

`effective_notify_config` 替换为：

```python
def effective_notify_config(base: NotifyConfig) -> NotifyConfig:
    stored = _stored()
    if not stored:
        return base
    return replace(
        base,
        channel=stored.get("channel") or base.channel,
        discord_enabled=stored.get("discord_enabled", base.discord_enabled),
        webhooks={**base.webhooks, **(stored.get("webhooks") or {})},
        email={**base.email, **(stored.get("email") or {})},
        task_channels={**base.task_channels, **(stored.get("task_channels") or {})},
        task_enabled={**base.task_enabled, **(stored.get("task_enabled") or {})},
    )
```

`read_notify_view` 替换为：

```python
def read_notify_view() -> dict[str, Any]:
    stored = _stored()
    base = NotifyConfig()
    webhooks = {**base.webhooks, **(stored.get("webhooks") or {})}
    return {
        "channel": stored.get("channel") or base.channel,
        "discord_enabled": stored.get("discord_enabled", base.discord_enabled),
        "email": {**base.email, **(stored.get("email") or {})},  # 地址非敏感；密码只在环境变量
        "task_channels": {**base.task_channels, **(stored.get("task_channels") or {})},
        "task_enabled": {**base.task_enabled, **(stored.get("task_enabled") or {})},
        "webhooks": {ch: {"configured": bool(url)} for ch, url in webhooks.items()},
        "degraded": not _has_db(),
    }
```

`update_notify` 替换为：

```python
def update_notify(payload: dict[str, Any]) -> dict[str, Any]:
    channel = payload.get("channel")
    if channel is not None and channel not in ("discord", "email"):
        return {"updated": False, "error": "invalid channel"}
    if not _has_db():
        return {"updated": False, "degraded": True}
    webhooks = {k: v for k, v in (payload.get("webhooks") or {}).items() if str(v).strip()}  # 留空不覆盖
    email = {k: v for k, v in (payload.get("email") or {}).items() if str(v).strip()}
    _with_conn(lambda conn: db.update_notify_settings(
        conn,
        discord_enabled=payload.get("discord_enabled"),
        webhooks=webhooks or None,
        task_channels=payload.get("task_channels"),
        task_enabled=payload.get("task_enabled"),
        channel=channel,
        email=email or None,
    ))
    return {"updated": True}
```

`test_notify_channel` 替换为（并新增 `_test_email`）：

```python
def test_notify_channel(channel: str, url: str | None = None, *,
                        email: dict[str, Any] | None = None, client=None) -> dict[str, Any]:
    if channel == "email":
        return _test_email(email or {}, client=client)
    ch = DiscordChannel(channel)
    if client is None:
        cfg = effective_notify_config(NotifyConfig())
        target = url or cfg.webhooks.get(channel)
        if not target:
            return {"ok": False, "error": "no webhook configured"}
        client = DiscordClient(**{f"{c.value}_url": (target if c == ch else "") for c in DiscordChannel})
    payload = {"content": "✅ Hermes 测试消息：webhook 配置正常，可安全忽略。"}
    try:
        client.send(ch, payload)
        return {"ok": True}
    except Exception as exc:  # 测试失败结构化返回，不抛；脱敏 webhook 明文
        msg = str(exc)
        # redact any discord webhook URL (with token) that requests may embed in the error
        msg = re.sub(r"https?://\S*discord(?:app)?\.com/api/webhooks/\S+", "<webhook redacted>", msg)
        return {"ok": False, "error": msg}


def _test_email(override: dict[str, Any], *, client=None) -> dict[str, Any]:
    if client is None:
        cfg = effective_notify_config(NotifyConfig())
        merged = {**cfg.email, **{k: v for k, v in override.items() if str(v).strip()}}
        if not os.environ.get("SMTP_PASSWORD"):
            return {"ok": False, "error": "SMTP_PASSWORD not set"}
        if not merged.get("to_addr"):
            return {"ok": False, "error": "no recipient configured"}
        client = EmailClient.from_config(replace(cfg, email=merged))
    try:
        client.send("[Hermes] ✅ 测试邮件", "<p>Hermes 测试邮件：SMTP 配置正常，可安全忽略。</p>")
        return {"ok": True}
    except Exception as exc:  # 测试失败结构化返回，不抛（SMTP 异常不携带密码）
        return {"ok": False, "error": str(exc)}
```

`investment_assistant/api/routes/settings.py` 的 `test_notify` 最后一行改为：

```python
    return settings.test_notify_channel(channel, url=payload.get("url"), email=payload.get("email"))
```

- [ ] **Step 4: 运行测试确认通过 + 全量回归**

Run: `.venv/bin/pytest tests/test_settings_service.py -v`
Expected: 全部 PASS

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add investment_assistant/services/settings.py investment_assistant/api/routes/settings.py tests/test_settings_service.py
git commit -m "feat(settings): 通知设置支持 channel/email 存取与邮件测试端点"
```

---

### Task 8: 前端——渠道单选 + 邮件配置表单

**Files:**
- Modify: `web/src/routes/Settings.svelte`（`sub === 'discord'` 分支及相关 script）
- `web/src/lib/api.ts` 无需修改（`getNotifySettings` / `patchNotifySettings` / `testNotifyChannel` 均为宽松类型）。

**Interfaces:**
- Consumes: Task 7 的 API——`GET /api/settings/notify` 返回含 `channel` / `email`；`PATCH` 接受 `channel` / `email`；`POST .../test` 接受 `{channel: "email", email: {...}}`；`GET /api/settings/env` 含 `SMTP_PASSWORD`。
- Produces: 无（终端消费者）。

- [ ] **Step 1: 修改 script 部分**

`web/src/routes/Settings.svelte`：

`notify` 初始 state（27-33 行附近）替换为：

```ts
  // notify（Discord / 邮件）
  let notify = $state<any>({
    channel: 'discord',
    webhooks: {},
    task_channels: {},
    task_enabled: {},
    discord_enabled: true,
    email: { from_addr: '', to_addr: '' },
  })
```

`load()` 中 `sub === 'discord'` 分支替换为（同时拉取 env 以显示 SMTP_PASSWORD 状态）：

```ts
      } else if (sub === 'discord') {
        ;[notify, env] = await Promise.all([api.getNotifySettings(), api.getEnvStatus()])
        if (!notify.email) notify.email = { from_addr: '', to_addr: '' }
        webhookInput = { earnings: '', signals: '', daily: '' }
        testResult = {}
      }
```

`saveNotify()` 的 `patchNotifySettings` 调用替换为：

```ts
    await api.patchNotifySettings({
      channel: notify.channel,
      discord_enabled: notify.discord_enabled,
      webhooks,
      email: notify.email,
      task_enabled: notify.task_enabled,
      task_channels: notify.task_channels,
    })
```

在 `verify` 函数后新增：

```ts
  async function verifyEmail() {
    const r = await api.testNotifyChannel({ channel: 'email', email: notify.email })
    testResult = { ...testResult, email: r.ok ? '✅ 成功' : `❌ ${(r as any).error ?? '失败'}` }
  }
```

- [ ] **Step 2: 修改模板部分**

`{:else if sub === 'discord'}` 分支：标题改为「通知」，顶部加渠道单选，Discord 原有内容包进 `{:else}`：

```svelte
{:else if sub === 'discord'}
  <div class="space-y-4 max-w-lg">
    <h2 class="text-lg font-semibold">通知</h2>
    <div class="flex gap-4 text-sm">
      <label class="flex items-center gap-1">
        <input type="radio" bind:group={notify.channel} value="discord" /> Discord
      </label>
      <label class="flex items-center gap-1">
        <input type="radio" bind:group={notify.channel} value="email" /> 邮件
      </label>
    </div>
    {#if notify.channel === 'email'}
      <div class="space-y-2">
        <div class="text-sm font-medium">发件地址（Gmail）</div>
        <input bind:value={notify.email.from_addr} placeholder="you@gmail.com"
               class="border border-border rounded px-2 py-1 text-sm bg-surface w-full" />
        <div class="text-sm font-medium">收件地址</div>
        <input bind:value={notify.email.to_addr} placeholder="you@outlook.com"
               class="border border-border rounded px-2 py-1 text-sm bg-surface w-full" />
        <div class="text-xs {env.SMTP_PASSWORD ? 'text-green-600' : 'text-red-500'}">
          SMTP_PASSWORD {env.SMTP_PASSWORD ? '✅ 已配置' : '未配置——需以环境变量注入 Gmail 应用专用密码'}
        </div>
        <button class="text-accent text-xs whitespace-nowrap px-2 py-1 border border-accent/30 rounded"
                onclick={verifyEmail}>发送测试邮件</button>
        {#if testResult.email}
          <div class="text-xs text-muted">{testResult.email}</div>
        {/if}
      </div>
    {:else}
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={notify.discord_enabled} />
        启用 Discord 推送
      </label>
      {#each ['earnings', 'signals', 'daily'] as ch}
        <div class="space-y-1">
          <div class="text-sm font-medium">
            {ch}
            {#if notify.webhooks?.[ch]?.configured}
              <span class="text-green-600 text-xs ml-1">（已配置）</span>
            {:else}
              <span class="text-muted text-xs ml-1">（未配置）</span>
            {/if}
          </div>
          <div class="flex gap-2">
            <input
              type="password"
              bind:value={webhookInput[ch]}
              placeholder="留空则不修改"
              class="border border-border rounded px-2 py-1 text-sm bg-surface flex-1"
            />
            <button
              class="text-accent text-xs whitespace-nowrap px-2 py-1 border border-accent/30 rounded"
              onclick={() => verify(ch)}
            >验证 {ch}</button>
          </div>
          {#if testResult[ch]}
            <div class="text-xs text-muted">{testResult[ch]}</div>
          {/if}
        </div>
      {/each}
    {/if}
    <div class="pt-2">
      <button class="px-3 py-1.5 rounded bg-accent/10 text-accent text-sm" onclick={saveNotify}>保存</button>
    </div>
    <p class="text-xs text-muted">webhook 明文不回显；留空字段不会覆盖已存值。SMTP 密码只能通过环境变量配置。</p>
  </div>
```

- [ ] **Step 3: 前端验证**

Run: `cd web && npm test`
Expected: 全部 PASS

Run: `cd web && npm run build`
Expected: svelte-check 无错误，构建成功

- [ ] **Step 4: Commit**

```bash
git add web/src/routes/Settings.svelte
git commit -m "feat(ui): 通知设置支持 Discord/邮件渠道单选与邮件测试"
```

---

### Task 9: 文档更新 + 全量验证

**Files:**
- Modify: `README.md`（86-88 行的 .env 示例、171-173 行的环境变量表）

**Interfaces:**
- Consumes: 前述全部任务。
- Produces: 无。

- [ ] **Step 1: 更新 README**

`.env` 示例块（86-88 行附近）在 `DISCORD_WEBHOOK_DAILY` 行后追加：

```
SMTP_PASSWORD=<Gmail 应用专用密码；邮件渠道启用时必需>
```

环境变量表（171-173 行附近）在 `DISCORD_WEBHOOK_DAILY` 行后追加一行：

```markdown
| `SMTP_PASSWORD`            | ⚠️ | 邮件渠道启用时必需；缺失时跳过邮件通知，不中断 |
```

- [ ] **Step 2: 全量验证**

Run: `.venv/bin/pytest -q`
Expected: 全部 PASS

Run: `cd web && npm test && npm run build`
Expected: 全部 PASS，构建成功

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README 补充 SMTP_PASSWORD 环境变量说明"
```

- [ ] **Step 4: 手动验收清单（部署后执行，不阻塞合并）**

1. Settings → 通知：切到「邮件」，填 Gmail 发件地址与 Outlook 收件地址，保存；
2. 点「发送测试邮件」——验证 Sealos 出网到 `smtp.gmail.com:465` 连通（spec 风险项）；
3. 手动触发一次 filings 任务，确认 Outlook 收到主题 `[Hermes] 📄 财报 · <日期>` 的邮件；
4. 切回「Discord」，确认 Discord 通知路径不回归。
