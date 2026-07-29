"""Email publisher adapters for DW01 solicitation publication.

``SmtpEmailPublisher`` sends over Gmail (or any SMTP) STARTTLS; ``MockEmailPublisher``
records nothing on the wire and returns a synthetic message id for local/dev runs.
Both implement ``EmailPublisherPort`` — the composition root picks one from config.
"""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid


@dataclass(frozen=True)
class SmtpEmailPublisher:
    host: str
    port: int
    username: str
    password: str
    sender: str

    async def send(self, *, subject: str, body: str, to: str) -> str:
        # smtplib is blocking; run it off the event loop.
        return await asyncio.to_thread(self._send_sync, subject, body, to)

    def _send_sync(self, subject: str, body: str, to: str) -> str:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message_id = make_msgid(domain="dw-tender.local")
        message["Message-ID"] = message_id
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.send_message(message)
        return message_id


@dataclass(frozen=True)
class MockEmailPublisher:
    """No-op publisher for environments without SMTP configured."""

    async def send(self, *, subject: str, body: str, to: str) -> str:
        return f"<mock-{uuid.uuid4().hex[:12]}@dw-tender.local>"
