"""SQL conversation store — RLS-scoped per transaction like every tender table."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import UtcClock
from dw_tender.adapters.conversation.tables import channel_event_dedupe, chat_conversations
from dw_tender.application.conversation.schemas import IntakeSlots
from dw_tender.application.conversation.service import ConversationView

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")

_ACTIVE_STATES = ("collecting", "confirming")


def _view(row: sa.Row) -> ConversationView:
    return ConversationView(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        channel_key=row.channel_key,
        subject=row.subject,
        state=row.state,
        slots=IntakeSlots.model_validate(row.slots or {}),
        case_id=row.case_id,
    )


@dataclass
class SqlConversationStore:
    """Implements ``ConversationStorePort``."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock

    async def claim_event(self, event_id: str) -> bool:
        async with self.session_factory() as session, session.begin():
            result = await session.execute(
                pg_insert(channel_event_dedupe)
                .values(event_id=event_id, received_at=self.clock.now())
                .on_conflict_do_nothing(index_elements=["event_id"])
            )
            return bool(result.rowcount)

    async def find_active(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, channel_key: str
    ) -> ConversationView | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            row = (
                await session.execute(
                    sa.select(chat_conversations)
                    .where(
                        chat_conversations.c.tenant_id == tenant_id,
                        chat_conversations.c.workspace_id == workspace_id,
                        chat_conversations.c.channel_key == channel_key,
                        chat_conversations.c.state.in_(_ACTIVE_STATES),
                    )
                    .order_by(chat_conversations.c.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            return _view(row) if row else None

    async def find_latest(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, channel_key: str
    ) -> ConversationView | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            row = (
                await session.execute(
                    sa.select(chat_conversations)
                    .where(
                        chat_conversations.c.tenant_id == tenant_id,
                        chat_conversations.c.workspace_id == workspace_id,
                        chat_conversations.c.channel_key == channel_key,
                    )
                    .order_by(chat_conversations.c.updated_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            return _view(row) if row else None

    async def list_case_conversations(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, channel_key: str
    ) -> list[ConversationView]:
        """Conversations on this channel that own a live case, newest focus first."""
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            rows = (
                await session.execute(
                    sa.select(chat_conversations)
                    .where(
                        chat_conversations.c.tenant_id == tenant_id,
                        chat_conversations.c.workspace_id == workspace_id,
                        chat_conversations.c.channel_key == channel_key,
                        chat_conversations.c.state == "case_created",
                        chat_conversations.c.case_id.is_not(None),
                    )
                    .order_by(chat_conversations.c.updated_at.desc())
                    .limit(8)
                )
            ).all()
            return [_view(row) for row in rows]

    async def touch(self, *, conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Bump updated_at — used by the case picker to switch chat focus."""
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            await session.execute(
                sa.update(chat_conversations)
                .where(chat_conversations.c.id == conversation_id)
                .values(updated_at=self.clock.now())
            )

    async def get(
        self, *, conversation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ConversationView | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            row = (
                await session.execute(
                    sa.select(chat_conversations).where(chat_conversations.c.id == conversation_id)
                )
            ).one_or_none()
            return _view(row) if row else None

    async def create(
        self,
        *,
        conversation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        channel_key: str,
        subject: str,
    ) -> ConversationView:
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            await session.execute(
                sa.insert(chat_conversations).values(
                    id=conversation_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    channel_key=channel_key,
                    subject=subject,
                    state="collecting",
                    slots={},
                    created_at=now,
                    updated_at=now,
                )
            )
        return ConversationView(
            id=conversation_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            channel_key=channel_key,
            subject=subject,
            state="collecting",
            slots=IntakeSlots(),
            case_id=None,
        )

    async def update(
        self,
        *,
        conversation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        state: str | None = None,
        slots: IntakeSlots | None = None,
        case_id: uuid.UUID | None = None,
    ) -> None:
        values: dict[str, object] = {"updated_at": self.clock.now()}
        if state is not None:
            values["state"] = state
        if slots is not None:
            values["slots"] = slots.model_dump(exclude_none=True)
        if case_id is not None:
            values["case_id"] = case_id
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            await session.execute(
                sa.update(chat_conversations)
                .where(chat_conversations.c.id == conversation_id)
                .values(**values)
            )
