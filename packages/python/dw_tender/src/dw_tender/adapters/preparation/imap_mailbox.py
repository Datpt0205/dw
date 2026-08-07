"""IMAP inbound mailbox adapter for email bid submissions.

Fetches UNSEEN messages whose subject carries the ``[DW01:<case-id>]`` RFQ
tag, extracts the first real attachment, and marks the message seen so a
poll loop never processes it twice. imaplib is blocking — every call runs
off the event loop.
"""

from __future__ import annotations

import asyncio
import email
import email.header
import email.utils
import imaplib
from dataclasses import dataclass

from dw_tender.application.preparation.email_ingest import InboundSubmissionEmail


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


@dataclass(frozen=True)
class ImapSubmissionMailbox:
    host: str
    username: str
    password: str
    folder: str = "INBOX"
    port: int = 993

    async def fetch_new(self) -> list[InboundSubmissionEmail]:
        return await asyncio.to_thread(self._fetch_sync)

    def _fetch_sync(self) -> list[InboundSubmissionEmail]:
        results: list[InboundSubmissionEmail] = []
        with imaplib.IMAP4_SSL(self.host, self.port) as imap:
            imap.login(self.username, self.password)
            imap.select(self.folder)
            # Server-side prefilter on the RFQ tag keeps personal inboxes calm;
            # the ingestor still re-validates the full [DW01:<uuid>] pattern.
            status, data = imap.search(None, '(UNSEEN SUBJECT "DW01:")')
            if status != "OK" or not data or not data[0]:
                return results
            for num in data[0].split():
                status, fetched = imap.fetch(num, "(RFC822)")
                if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    continue
                message = email.message_from_bytes(fetched[0][1])
                subject = _decode(message.get("Subject"))
                sender = email.utils.parseaddr(message.get("From", ""))[1]
                message_id = _decode(message.get("Message-ID")) or f"imap-{num.decode()}"

                body_text = ""
                attachment_name: str | None = None
                attachment_bytes: bytes | None = None
                attachment_type = "application/octet-stream"
                for part in message.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    filename = part.get_filename()
                    payload = part.get_payload(decode=True)
                    if not isinstance(payload, bytes) or not payload:
                        continue
                    if filename and attachment_bytes is None:
                        attachment_name = _decode(filename)
                        attachment_bytes = payload
                        attachment_type = part.get_content_type()
                    elif part.get_content_type() == "text/plain" and not body_text:
                        charset = part.get_content_charset() or "utf-8"
                        body_text = payload.decode(charset, errors="replace")

                results.append(
                    InboundSubmissionEmail(
                        message_id=message_id,
                        subject=subject,
                        sender=sender,
                        body_text=body_text,
                        attachment_name=attachment_name,
                        attachment_bytes=attachment_bytes,
                        attachment_content_type=attachment_type,
                    )
                )
                # Seen = processed; failures inside the ingestor surface in its
                # report — redelivery loops would double-record bids otherwise.
                imap.store(num, "+FLAGS", "\\Seen")
        return results
