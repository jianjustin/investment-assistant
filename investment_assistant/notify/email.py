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
