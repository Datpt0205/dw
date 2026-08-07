"""Email submission ingest — suppliers reply to the RFQ email with their bid.

The RFQ subject carries ``[DW01:<case-id>]``; replies keep it, so the mailroom
can route each attachment to its case: store the bid (receipt + register, same
handler as the Slack receipt desk) and, once the configured minimum number of
submissions is reached (demo: 1), automatically request CP4 so procurement
only has to APPROVE — nobody uploads bids by hand anymore.

Deliberately deterministic: no LLM anywhere in this path (bids are legal
evidence). Unmatched or malformed mails are skipped and reported, never
guessed at.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from dw_kernel.errors import DWError
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_tender.application.preparation.handlers import (
    GetPreparationCaseHandler,
    RecordPreparationSubmissionHandler,
    RecordSubmissionCommand,
    RequestCp4Handler,
)

_CASE_TAG = re.compile(r"\[DW01:([0-9a-fA-F-]{36})\]")


@dataclass(frozen=True)
class InboundSubmissionEmail:
    """One fetched mail with (at most) one bid attachment."""

    message_id: str
    subject: str
    sender: str
    body_text: str
    attachment_name: str | None
    attachment_bytes: bytes | None
    attachment_content_type: str = "application/octet-stream"


class SubmissionMailboxPort(Protocol):
    """Inbound mailbox adapter (IMAP in prod, fake in tests)."""

    async def fetch_new(self) -> list[InboundSubmissionEmail]: ...


class AckSenderPort(Protocol):
    async def send(self, *, subject: str, body: str, to: str) -> str: ...


@dataclass(frozen=True)
class IngestReport:
    recorded: int = 0
    cp4_requested: bool = False
    skipped: tuple[str, ...] = ()


@dataclass
class EmailSubmissionIngestor:
    """Polls the mailbox and records bids against their cases."""

    mailbox: SubmissionMailboxPort
    record_submission: RecordPreparationSubmissionHandler
    request_cp4: RequestCp4Handler
    get_case: GetPreparationCaseHandler
    clock: UtcClock
    ack_sender: AckSenderPort | None = None
    # Demo: one bid is enough to put the CP4 card in front of procurement.
    min_submissions_for_cp4: int = 1
    _cp4_requested: set[uuid.UUID] = field(default_factory=set)

    async def poll_once(self, context: AccessContext) -> IngestReport:
        recorded = 0
        cp4_requested = False
        skipped: list[str] = []
        for mail in await self.mailbox.fetch_new():
            match = _CASE_TAG.search(mail.subject)
            if match is None:
                skipped.append(f"{mail.message_id}: subject has no [DW01:<case>] tag")
                continue
            if not mail.attachment_bytes or not mail.attachment_name:
                skipped.append(f"{mail.message_id}: no attachment (bid file required)")
                continue
            case_id = uuid.UUID(match.group(1))
            supplier = await self._supplier_name(case_id, mail, context)
            received_at = self.clock.now()
            try:
                await self.record_submission.handle(
                    case_id,
                    RecordSubmissionCommand(
                        filename=mail.attachment_name,
                        content_type=mail.attachment_content_type,
                        content=mail.attachment_bytes,
                        supplier_name=supplier,
                        received_at=received_at.isoformat(),
                        receipt_status="on_time",
                        external_reference=f"email:{mail.message_id}",
                    ),
                    context,
                )
            except DWError as exc:
                skipped.append(f"{mail.message_id}: {exc}")
                continue
            recorded += 1
            if self.ack_sender is not None:
                # Ack is best-effort — the bid IS recorded either way.
                with contextlib.suppress(Exception):
                    await self.ack_sender.send(
                        subject=f"Re: {mail.subject}",
                        body=(
                            f"Kính gửi {supplier},\n\n"
                            "Chúng tôi xác nhận ĐÃ TIẾP NHẬN hồ sơ dự thầu của Quý đơn vị "
                            f"lúc {received_at:%d/%m/%Y %H:%M} (giờ hệ thống).\n"
                            f"Tệp: {mail.attachment_name}\n"
                            "Biên nhận đã được lập và niêm phong vào sổ tiếp nhận.\n\n"
                            "Trân trọng,\nPhòng Mua sắm (hệ thống tự động).\n"
                        ),
                        to=mail.sender,
                    )
            if case_id not in self._cp4_requested:
                try:
                    count = await self.request_cp4.handle(case_id, context)
                except DWError:
                    count = 0  # e.g. state not ready — a later mail retriggers
                if count >= self.min_submissions_for_cp4:
                    self._cp4_requested.add(case_id)
                    cp4_requested = True
        return IngestReport(recorded=recorded, cp4_requested=cp4_requested, skipped=tuple(skipped))

    async def _supplier_name(
        self, case_id: uuid.UUID, mail: InboundSubmissionEmail, context: AccessContext
    ) -> str:
        """Best-effort supplier attribution, deterministic.

        Demo reality: all three invited suppliers share ONE personal mailbox,
        so the sender address identifies nobody. Match the shortlist names
        against subject+body; fall back to the sender's mailbox name.
        """
        haystack = f"{mail.subject}\n{mail.body_text}".lower()
        try:
            view = await self.get_case.handle(case_id, context)
            for artifact in view.artifacts:
                if artifact.artifact_type != "supplier_shortlist":
                    continue
                shortlist = artifact.content.get("shortlist", [])
                if isinstance(shortlist, list):
                    for item in shortlist:
                        name = str(item.get("name", "")) if isinstance(item, dict) else ""
                        if name and name.lower() in haystack:
                            return name
        except Exception:
            pass
        local_part = mail.sender.split("@", 1)[0].strip() or "Nhà cung cấp (email)"
        return f"{local_part} (qua email)"
