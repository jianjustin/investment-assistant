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
    assert subject == "[investment-assistant] 📄 财报 · 2026-07-03"


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
