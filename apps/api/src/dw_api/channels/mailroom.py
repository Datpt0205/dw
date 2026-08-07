"""Mailroom: background IMAP poller for email bid submissions.

Suppliers reply to the RFQ email (subject keeps the ``[DW01:<case-id>]`` tag)
with their bid attached; this task records each bid — receipt + register, no
manual upload — and auto-requests the CP4 card once enough bids are in
(demo: 1). Enabled with ``DW_EMAIL_SUBMISSIONS_ENABLED=true`` plus IMAP
credentials (defaulting to the SMTP account that sends the RFQ).

The poller acts under a fixed procurement identity from the demo roster
(``DW_MAILROOM_SUBJECT``, default Bình) — same trust path as the Slack
channel: subject → roster → verified AccessContext per poll.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import yaml

from dw_platform.application.identity import VerifiedClaims
from dw_tender.application.preparation.email_ingest import EmailSubmissionIngestor

if TYPE_CHECKING:
    from dw_api.bootstrap import ApiContainer

logger = logging.getLogger("dw_api.channels.mailroom")

_POLL_SECONDS_DEFAULT = 20


def _roster_entry(repo_root: Path, subject: str) -> dict[str, Any] | None:
    path = repo_root / "configs" / "demo" / "demo_users.yaml"
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for user in raw.get("users", []):
        if user.get("subject") == subject:
            return dict(user)
    return None


def start_mailroom(container: ApiContainer, repo_root: Path) -> asyncio.Task[None] | None:
    """Start the poll loop when enabled+configured; None otherwise."""
    if os.environ.get("DW_EMAIL_SUBMISSIONS_ENABLED", "").lower() not in ("1", "true", "yes"):
        return None
    if container.preparation is None or container.access_context_factory is None:
        logger.warning("mailroom enabled but preparation/auth not wired — skipping")
        return None
    host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    user = os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER", "")
    password = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD", "")
    if not (host and user and password):
        logger.warning("mailroom enabled but IMAP credentials missing — skipping")
        return None

    subject = os.environ.get("DW_MAILROOM_SUBJECT", "dev|binh.tran")
    entry = _roster_entry(repo_root, subject)
    if entry is None:
        logger.warning("mailroom subject %s not in demo roster — skipping", subject)
        return None

    from dw_api.bootstrap import _build_email_publisher
    from dw_tender.adapters.preparation.imap_mailbox import ImapSubmissionMailbox

    ingestor = EmailSubmissionIngestor(
        mailbox=ImapSubmissionMailbox(
            host=host,
            username=user,
            password=password,
            folder=os.environ.get("IMAP_FOLDER", "INBOX"),
        ),
        record_submission=container.preparation.record_submission,
        request_cp4=container.preparation.request_cp4,
        get_case=container.preparation.get_case,
        clock=container.preparation.audit_recorder.clock,
        ack_sender=_build_email_publisher(),  # type: ignore[arg-type]
        min_submissions_for_cp4=int(os.environ.get("DW_SUBMISSIONS_MIN_TO_CLOSE", "1")),
    )
    interval = int(os.environ.get("DW_MAILROOM_POLL_SECONDS", str(_POLL_SECONDS_DEFAULT)))

    async def _loop() -> None:
        logger.info("mailroom polling %s as %s every %ss", host, subject, interval)
        while True:
            try:
                factory = container.access_context_factory
                assert factory is not None
                context = await factory.build(
                    VerifiedClaims(subject=subject, email=None, issuer="dw-mailroom"),
                    UUID(str(entry["tenant_id"])),
                    UUID(str(entry["workspace_id"])),
                )
                report = await ingestor.poll_once(context)
                if report.recorded or report.skipped:
                    logger.info(
                        "mailroom: recorded=%s cp4_requested=%s skipped=%s",
                        report.recorded,
                        report.cp4_requested,
                        list(report.skipped),
                    )
            except Exception:
                logger.exception("mailroom poll failed — retrying next interval")
            await asyncio.sleep(interval)

    return asyncio.get_running_loop().create_task(_loop(), name="dw-mailroom")
