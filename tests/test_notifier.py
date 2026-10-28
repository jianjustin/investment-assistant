from datetime import date

from investment_assistant.config import NotifyConfig
from investment_assistant.notify import notifier, templates


class FakeClient:
    def __init__(self):
        self.sent = []

    def send(self, channel, payload):
        self.sent.append((channel, payload))


def test_dispatch_skips_when_globally_disabled():
    out = notifier.dispatch("workbench", "success", {}, NotifyConfig(discord_enabled=False), client=FakeClient())
    assert out["sent"] is False and out["reason"] == "discord_disabled"


def test_dispatch_skips_when_task_disabled():
    cfg = NotifyConfig(task_enabled={"workbench": False})
    out = notifier.dispatch("workbench", "success", {}, cfg, client=FakeClient())
    assert out["sent"] is False and out["reason"] == "task_disabled"


def test_dispatch_routes_to_channel():
    client = FakeClient()
    out = notifier.dispatch("filings", "success", {"filings": []}, NotifyConfig(), client=client)
    assert out["sent"] is True and out["channel"] == "discord" and out["discord_channel"] == "earnings"
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
    assert client.sent and client.sent[0][0] == "[investment-assistant] 📄 财报 · 2026-07-03"


def test_dispatch_email_requires_password(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    cfg = NotifyConfig(channel="email", email={"from_addr": "a@gmail.com", "to_addr": "b@outlook.com"})
    out = notifier.dispatch("workbench", "success", {}, cfg)
    assert out == {"sent": False, "reason": "email_no_password"}


def test_dispatch_email_requires_recipient(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    cfg = NotifyConfig(channel="email", email={"from_addr": "a@gmail.com", "to_addr": ""})
    out = notifier.dispatch("workbench", "success", {}, cfg)
    assert out == {"sent": False, "reason": "email_no_recipient"}


def test_dispatch_email_requires_sender(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    cfg = NotifyConfig(channel="email", email={"from_addr": "", "to_addr": "b@outlook.com"})
    out = notifier.dispatch("workbench", "success", {}, cfg)
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


def test_send_notifications_disabled_task():
    from investment_assistant.notify.message import Notification

    out = notifier.send_notifications('workbench', [Notification(title='x', color=1, fields=[])],
                                      NotifyConfig(task_enabled={'workbench': False}), client=FakeClient())
    assert out['sent'] is False and out['reason'] == 'task_disabled' and out['messages'] == 0


def test_send_notifications_sends_each_message():
    from investment_assistant.notify.message import Notification

    client = FakeClient()
    notes = [Notification(title='a', color=1, fields=[]), Notification(title='b', color=2, fields=[])]
    out = notifier.send_notifications('workbench', notes, NotifyConfig(), client=client)
    assert out['sent'] is True and out['messages'] == 2 and len(client.sent) == 2


def test_send_notifications_partial_failure_counts_sent():
    from investment_assistant.notify.message import Notification

    class HalfBoom(FakeClient):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def send(self, channel, payload):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError('network')

    out = notifier.send_notifications('workbench', [Notification(title='a', color=1, fields=[]),
                                                    Notification(title='b', color=2, fields=[])],
                                      NotifyConfig(), client=HalfBoom())
    assert out['sent'] is False and out['messages'] == 1 and 'send_failed' in out['reason']


def test_send_notifications_failure_is_structured():
    from investment_assistant.notify.message import Notification

    class Boom(FakeClient):
        def send(self, channel, payload):
            raise RuntimeError('network')

    out = notifier.send_notifications('workbench', [Notification(title='x', color=1, fields=[])],
                                      NotifyConfig(), client=Boom())
    assert out['sent'] is False and out['messages'] == 0 and 'send_failed' in out['reason']


def test_agent_error_source_uses_display_name():
    from investment_assistant.notify.templates import SOURCE_NAMES, workbench_digest
    assert SOURCE_NAMES['agent'] == 'Agent'
    payload = {'session': '2026-10-22', 'overview': {}, 'plans': [], 'holdings': [], 'pending': {},
               'errors': [], 'errors_by_source': {'agent': ['NVDA', 'MU']}}
    fields = [f for m in workbench_digest(payload) for f in m.fields]
    agent_field = next(f for f in fields if f.name == 'Agent')
    assert 'NVDA' in agent_field.value and 'MU' in agent_field.value


def test_unknown_channel_is_structured_failure():
    from dataclasses import replace

    from investment_assistant.config import NotifyConfig
    from investment_assistant.notify import notifier
    from investment_assistant.notify.discord import DiscordChannel
    from investment_assistant.notify.message import Notification

    sent = []

    class Fake:
        def send(self, channel, payload):
            sent.append(channel)

    cfg = replace(NotifyConfig(), task_channels={"workbench": "daily"})
    n = Notification(title="t", color=1, fields=[], footer="")
    out = notifier.send_notifications("workbench", [n], cfg, client=Fake())
    assert out == {"sent": False, "messages": 0, "reason": "unknown_channel: daily"}
    assert sent == []


# --- v2.5 §10.3: the plan-updates message ---

def _digest_payload(updates):
    return {'session': '2026-10-22', 'overview': {'plan_updates': {'revise': 0, 'invalidate': len(updates)}},
            'plans': [], 'holdings': [], 'pending': {}, 'errors': [], 'errors_by_source': {},
            'plan_updates': updates}


def _invalidate(ticker, reason='失效条件成立：收盘跌破 112'):
    return {'ticker': ticker, 'kind': 'invalidate', 'from_version': 0, 'to_version': None, 'changes': [],
            'levels': None, 'valid_until': None, 'decided_by': 'host', 'reason': reason}


def test_plan_updates_message_is_third():
    from investment_assistant.notify.templates import workbench_digest
    messages = workbench_digest(_digest_payload([_invalidate('NVDA')]))
    assert len(messages) == 6
    assert messages[2].title == '🔁 计划更新 · 2026-10-22'
    assert [m.title.split(' · ')[0] for m in messages] == ['📊 工作台', '🆕 新计划', '🔁 计划更新', '💼 持仓',
                                                          '⏳ 待处理与异常', '🔎 筛选报告']
    assert messages[2].fields[0].value == 'NVDA 作废（系统规则）：失效条件成立：收盘跌破 112'


def test_no_plan_updates_no_message():
    from investment_assistant.notify.templates import workbench_digest
    messages = workbench_digest(_digest_payload([]))
    assert len(messages) == 5
    assert not any(m.title.startswith('🔁 计划更新') for m in messages)
    no_key = {k: v for k, v in _digest_payload([]).items() if k != 'plan_updates'}
    assert len(workbench_digest(no_key)) == 5


def test_plan_updates_respect_field_and_message_limits():
    from investment_assistant.notify.templates import workbench_digest
    messages = workbench_digest(_digest_payload([_invalidate(f'T{i:02d}', '长' * 3000) for i in range(12)]))
    updates = messages[2]
    assert all(len(f.value) <= 1024 for f in updates.fields)
    total = len(updates.title) + sum(len(f.name) + len(f.value) for f in updates.fields) + len(updates.footer)
    assert total <= 6000
    assert updates.fields[-1].name == '溢出'
