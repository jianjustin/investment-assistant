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
    assert out["sent"] is True and out["channel"] == "discord" and out["discord_channel"] == "daily"
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


def test_dispatch_email_requires_sender(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    cfg = NotifyConfig(channel="email", email={"from_addr": "", "to_addr": "b@outlook.com"})
    out = notifier.dispatch("metrics", "success", {}, cfg)
    assert out == {"sent": False, "reason": "email_no_sender"}


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
