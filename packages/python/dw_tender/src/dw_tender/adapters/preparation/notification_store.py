"""Worker-side durable store for DW01 approval notification deliveries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import UtcClock
from dw_platform.adapters.persistence import tables as platform_tables
from dw_tender.adapters.preparation import tables
from dw_tender.adapters.preparation.repositories import _notification_from_row
from dw_tender.domain.preparation.notifications import IntakeNotificationDelivery

_SET_WORKER_DRAIN = text("SELECT set_config('app.worker_drain', 'on', true)")


@dataclass
class IntakeNotificationJobStore:
    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock
    stale_after_seconds: int = 120

    async def claim_next(self) -> IntakeNotificationDelivery | None:
        now = self.clock.now()
        stale_before = now - timedelta(seconds=self.stale_after_seconds)
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_WORKER_DRAIN)
            row = (
                await session.execute(
                    sa.select(
                        *tables.approval_notification_jobs.c,
                        platform_tables.users.c.subject.label("recipient_subject"),
                        tables.preparation_cases.c.state.label("case_state"),
                    )
                    .join(
                        platform_tables.users,
                        platform_tables.users.c.id
                        == tables.approval_notification_jobs.c.recipient_user_id,
                    )
                    .join(
                        tables.preparation_cases,
                        tables.preparation_cases.c.id
                        == tables.approval_notification_jobs.c.case_id,
                    )
                    .where(
                        tables.approval_notification_jobs.c.due_at <= now,
                        sa.or_(
                            tables.approval_notification_jobs.c.status == "queued",
                            sa.and_(
                                tables.approval_notification_jobs.c.status == "processing",
                                tables.approval_notification_jobs.c.claimed_at < stale_before,
                            ),
                        ),
                    )
                    .order_by(tables.approval_notification_jobs.c.due_at.asc())
                    .limit(1)
                    .with_for_update(
                        skip_locked=True,
                        of=tables.approval_notification_jobs,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            attempts = row.attempts + 1
            await session.execute(
                sa.update(tables.approval_notification_jobs)
                .where(tables.approval_notification_jobs.c.id == row.id)
                .values(
                    status="processing",
                    attempts=attempts,
                    claimed_at=now,
                    updated_at=now,
                )
            )
            job = replace(_notification_from_row(row), attempts=attempts, claimed_at=now)
            return IntakeNotificationDelivery(
                job=job,
                recipient_subject=row.recipient_subject,
                case_state=row.case_state,
            )

    async def mark_sent(
        self, delivery: IntakeNotificationDelivery, *, channel: str, ts: str
    ) -> None:
        await self._update(
            delivery,
            status="sent",
            slack_channel_id=channel,
            slack_message_ts=ts,
            sent_at=self.clock.now(),
            last_error=None,
        )

    async def mark_cancelled(self, delivery: IntakeNotificationDelivery, *, reason: str) -> None:
        await self._update(delivery, status="cancelled", last_error=reason[:2000])

    async def mark_failed(self, delivery: IntakeNotificationDelivery, *, error: str) -> None:
        await self._update(
            delivery,
            status="failed",
            claimed_at=None,
            last_error=error[:2000],
        )

    async def mark_retry(self, delivery: IntakeNotificationDelivery, *, error: str) -> None:
        job = delivery.job
        if job.attempts >= job.max_attempts:
            await self._update(delivery, status="failed", last_error=error[:2000])
            return
        delay = min(2 ** max(job.attempts - 1, 0), 60)
        await self._update(
            delivery,
            status="queued",
            due_at=self.clock.now() + timedelta(seconds=delay),
            claimed_at=None,
            last_error=error[:2000],
        )

    async def _update(self, delivery: IntakeNotificationDelivery, **values: object) -> None:
        values["updated_at"] = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_WORKER_DRAIN)
            await session.execute(
                sa.update(tables.approval_notification_jobs)
                .where(
                    tables.approval_notification_jobs.c.id == delivery.job.id,
                    tables.approval_notification_jobs.c.status == "processing",
                )
                .values(**values)
            )
