"""Unit tests for the email bid-submission ingest (mailroom)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from dw_kernel.errors import ConflictError
from dw_tender.application.preparation.email_ingest import (
    EmailSubmissionIngestor,
    InboundSubmissionEmail,
)

pytestmark = pytest.mark.unit

CASE_ID = uuid.uuid4()
CONTEXT: Any = object()  # the ingestor only forwards it


def mail(
    *,
    subject: str = f"Re: [MỜI CHÀO GIÁ][DW01:{CASE_ID}] Mua 500 laptop",
    sender: str = "phung@example.com",
    body: str = "Synnex FPT xin nộp hồ sơ dự thầu.",
    attachment: bytes | None = b"%PDF-fake",
    name: str | None = "hsdt-synnex.pdf",
) -> InboundSubmissionEmail:
    return InboundSubmissionEmail(
        message_id=f"<{uuid.uuid4().hex}@mail>",
        subject=subject,
        sender=sender,
        body_text=body,
        attachment_name=name,
        attachment_bytes=attachment,
        attachment_content_type="application/pdf",
    )


@dataclass
class FakeMailbox:
    mails: list[InboundSubmissionEmail] = field(default_factory=list)

    async def fetch_new(self) -> list[InboundSubmissionEmail]:
        out, self.mails = self.mails, []
        return out


@dataclass
class FakeRecord:
    commands: list[Any] = field(default_factory=list)
    error: Exception | None = None

    async def handle(self, case_id: uuid.UUID, command: Any, context: Any) -> None:
        if self.error is not None:
            raise self.error
        self.commands.append((case_id, command))


@dataclass
class FakeCp4:
    count: int = 1
    calls: list[uuid.UUID] = field(default_factory=list)

    async def handle(self, case_id: uuid.UUID, context: Any) -> int:
        self.calls.append(case_id)
        return self.count


@dataclass
class FakeArtifact:
    artifact_type: str
    content: dict[str, Any]


@dataclass
class FakeCaseView:
    artifacts: list[FakeArtifact] = field(default_factory=list)


@dataclass
class FakeGetCase:
    view: FakeCaseView = field(default_factory=FakeCaseView)

    async def handle(self, case_id: uuid.UUID, context: Any) -> FakeCaseView:
        return self.view


@dataclass
class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 5, 9, 30, tzinfo=UTC)


@dataclass
class FakeAck:
    sent: list[dict[str, str]] = field(default_factory=list)

    async def send(self, *, subject: str, body: str, to: str) -> str:
        self.sent.append({"subject": subject, "to": to})
        return "<ack@mail>"


def make_ingestor(
    mailbox: FakeMailbox,
    record: FakeRecord | None = None,
    cp4: FakeCp4 | None = None,
    get_case: FakeGetCase | None = None,
    ack: FakeAck | None = None,
    min_for_cp4: int = 1,
) -> EmailSubmissionIngestor:
    return EmailSubmissionIngestor(
        mailbox=mailbox,
        record_submission=record or FakeRecord(),  # type: ignore[arg-type]
        request_cp4=cp4 or FakeCp4(),  # type: ignore[arg-type]
        get_case=get_case or FakeGetCase(),  # type: ignore[arg-type]
        clock=FakeClock(),
        ack_sender=ack,
        min_submissions_for_cp4=min_for_cp4,
    )


async def test_records_bid_and_requests_cp4_at_demo_threshold_one() -> None:
    record, cp4, ack = FakeRecord(), FakeCp4(count=1), FakeAck()
    ingestor = make_ingestor(FakeMailbox([mail()]), record, cp4, ack=ack)
    report = await ingestor.poll_once(CONTEXT)
    assert report.recorded == 1 and report.cp4_requested is True
    case_id, command = record.commands[0]
    assert case_id == CASE_ID
    assert command.filename == "hsdt-synnex.pdf"
    assert command.receipt_status == "on_time"
    assert command.external_reference.startswith("email:")
    assert cp4.calls == [CASE_ID]
    assert ack.sent and ack.sent[0]["to"] == "phung@example.com"


async def test_supplier_attributed_from_shortlist_names() -> None:
    record = FakeRecord()
    get_case = FakeGetCase(
        FakeCaseView(
            artifacts=[
                FakeArtifact(
                    "supplier_shortlist",
                    {"shortlist": [{"name": "Synnex FPT"}, {"name": "Digiworld"}]},
                )
            ]
        )
    )
    ingestor = make_ingestor(FakeMailbox([mail()]), record, get_case=get_case)
    await ingestor.poll_once(CONTEXT)
    assert record.commands[0][1].supplier_name == "Synnex FPT"


async def test_untagged_or_attachmentless_mail_is_skipped_not_guessed() -> None:
    record = FakeRecord()
    mails = [
        mail(subject="Re: chuyện khác không liên quan"),
        mail(attachment=None, name=None),
    ]
    report = await make_ingestor(FakeMailbox(mails), record).poll_once(CONTEXT)
    assert report.recorded == 0 and len(report.skipped) == 2
    assert not record.commands


async def test_cp4_requested_only_once_per_case() -> None:
    cp4 = FakeCp4(count=1)
    box = FakeMailbox([mail()])
    ingestor = make_ingestor(box, cp4=cp4)
    await ingestor.poll_once(CONTEXT)
    box.mails = [mail()]
    await ingestor.poll_once(CONTEXT)
    assert len(cp4.calls) == 1  # second bid records but does not re-request


async def test_record_conflict_is_reported_not_fatal() -> None:
    record = FakeRecord(error=ConflictError("not receiving"))
    report = await make_ingestor(FakeMailbox([mail()]), record).poll_once(CONTEXT)
    assert report.recorded == 0
    assert len(report.skipped) == 1 and "not receiving" in report.skipped[0]
