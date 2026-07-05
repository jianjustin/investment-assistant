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


def test_filings_embed_uses_actual_date_label():
    payload = templates.filings_digest_embed(
        {"downloaded_count": 0, "filings": []}, date_label="2026-06-01 ~ 2026-06-30")
    assert payload["embeds"][0]["title"] == "📄 财报 · 2026-06-01 ~ 2026-06-30"
    assert "昨日" not in payload["embeds"][0]["title"]


def test_metrics_embed_renders_backfill_days():
    summary = {"days": [
        {"date": "2026-06-01", "market_status": "green"},
        {"date": "2026-06-02", "error": "no data"},
    ]}
    payload = templates.metrics_summary_embed(summary, date_label="2026-06-01 ~ 2026-06-02")
    field = payload["embeds"][0]["fields"][0]
    assert "回补" in field["name"]
    assert "2026-06-01" in field["value"] and "GREEN" in field["value"]
    assert "no data" in field["value"]


def test_scores_embed_renders_backfill_days():
    summary = {"days": [{"date": "2026-06-01", "count": 4, "failures": 0}]}
    payload = templates.scores_summary_embed(summary, date_label="2026-06-01")
    assert payload["embeds"][0]["title"] == "📈 策略评分 · 2026-06-01"
    assert "4" in payload["embeds"][0]["fields"][0]["value"]


def test_dispatch_passes_date_label_into_embed():
    client = FakeClient()
    notifier.dispatch(
        "filings", "success", {"downloaded_count": 1, "filings": []}, NotifyConfig(),
        client=client, target_start_date=date(2026, 7, 3), target_end_date=date(2026, 7, 3),
    )
    assert client.sent[0][1]["embeds"][0]["title"] == "📄 财报 · 2026-07-03"
