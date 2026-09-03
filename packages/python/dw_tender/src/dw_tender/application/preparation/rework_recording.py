"""Writing down that a case came back — inside somebody else's transaction.

This is a function taking an open unit of work rather than a handler owning
one, and that shape is forced by where the three return paths live. Intake
rejection happens in a handler; CP1 and CP2 rejections happen inside workflow
nodes that have already opened a transaction to move the case's state. The
record and the state change have to land together or not at all — a case shown
as returned with no record would undercount silently, and a record with no
state change would count something that never happened.

So: no ``commit`` here. The caller owns the transaction and its outcome.
"""

from __future__ import annotations

from datetime import UTC

from dw_kernel.errors import DomainError
from dw_kernel.ids import UserId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_tender.application.preparation.ports import PreparationUnitOfWork
from dw_tender.application.preparation.rework import ReworkSupportRules
from dw_tender.domain.preparation.entities import PreparationCase
from dw_tender.domain.preparation.rework import ReworkCheckpoint, ReworkEvent

# Used when a channel had no way to offer the catalogue — see design §7.1.
FALLBACK_REASON_CODE = "other"


def normalise_reason_code(reason_code: str, rules: ReworkSupportRules) -> str:
    """Validate a picked reason, or fall back when none was offered.

    Blank means the deciding channel has no reason picker yet (chat replies,
    older API clients). Those fall back rather than fail: refusing the
    rejection itself would be a far worse outcome than filing it as "other".

    A code that is present but not in the catalogue is a different matter —
    that is a caller sending something made up, and it is refused.
    """
    code = (reason_code or "").strip()
    if not code:
        return FALLBACK_REASON_CODE
    if not rules.is_known(code):
        raise DomainError(
            "unknown rework reason code",
            details={"reason_code": code},
        )
    return code


async def record_rework_event(
    uow: PreparationUnitOfWork,
    *,
    case: PreparationCase,
    decided_by: UserId,
    checkpoint: ReworkCheckpoint,
    reason_code: str,
    reason_text: str,
    rules: ReworkSupportRules,
    clock: UtcClock,
    id_generator: IdGenerator,
) -> ReworkEvent | None:
    """Append one returned-case record to the caller's open transaction.

    Returns the record written, or ``None`` when the feature is switched off
    in the rule pack — no rows, no tally, nothing to clean up if procurement
    turns it on again later.

    Attributes the return to ``case.created_by``, never to whoever is acting:
    a case filed on a colleague's behalf must not land on the filer's tally.
    """
    if not rules.is_enabled():
        return None

    text = (reason_text or "").strip()
    if not text:
        raise DomainError("returning a case requires a reason")

    event = ReworkEvent(
        id=id_generator.new_uuid(),
        tenant_id=case.tenant_id,
        workspace_id=case.workspace_id,
        case_id=case.id,
        creator_user_id=case.created_by,
        decided_by_user_id=decided_by,
        checkpoint=checkpoint,
        reason_code=normalise_reason_code(reason_code, rules),
        reason_text=text,
        policy_version=rules.policy_version,
        occurred_at=clock.now().astimezone(UTC),
    )
    await uow.rework_events.add(event)
    return event
