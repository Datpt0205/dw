"""Has this unit just bought the same thing?

Not a fraud check, and the wording must never suggest otherwise. Buying the
same item twice in a month is usually well founded — the first batch went to
one team, the second to a team that has since been created. What the rule pack
asks for is a document: a justification recorded at the moment it is true,
rather than reconstructed two years later when someone asks.

Which is why a false alarm costs more than a miss. Accusing a colleague of
splitting a package, wrongly, is remembered; being asked for one paragraph of
context is not. The threshold lives in the rule pack so procurement can move
it without a deploy, and the finding always names the earlier case so a person
can see for themselves.

Pure: similarity is computed over text the caller supplies. Retrieval and
storage stay outside.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from dw_tender.application.conversation.focus import _tokens
from dw_tender.application.preparation.rules import ProcurementRules


@dataclass(frozen=True, slots=True)
class PastPurchase:
    case_id: uuid.UUID
    title: str
    created_at: datetime
    estimated_value_minor: int
    business_domain: str
    owner_name: str = ""


@dataclass(frozen=True, slots=True)
class RepeatFinding:
    earlier_case_id: uuid.UUID
    earlier_title: str
    days_ago: int
    similarity: float
    question: str

    def as_clarification(self) -> dict[str, object]:
        """The blocking question DW01 attaches to the case."""
        return {
            "id": f"repeat-{self.earlier_case_id.hex[:8]}",
            "question": self.question,
            "blocking": True,
            "origin": "repeat_purchase",
            "related_case_id": str(self.earlier_case_id),
        }


def _similarity(left: str, right: str) -> float:
    """Jaccard over identity-carrying tokens — same measure, both directions."""
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_repeat(
    *,
    title: str,
    business_domain: str,
    estimated_value_minor: int,
    now: datetime,
    history: list[PastPurchase],
    rules: ProcurementRules,
) -> RepeatFinding | None:
    """The closest recent purchase that crosses the rule pack's threshold."""
    if not rules.watches_repeat_purchase(estimated_value_minor):
        return None

    best: tuple[float, PastPurchase, int] | None = None
    for past in history:
        if past.business_domain != business_domain:
            continue
        days = (now - past.created_at).days
        if days < 0 or days > rules.repeat_lookback_days:
            continue
        score = _similarity(title, past.title)
        if score < rules.repeat_similarity:
            continue
        if best is None or score > best[0]:
            best = (score, past, days)
    if best is None:
        return None

    score, past, days = best
    return RepeatFinding(
        earlier_case_id=past.case_id,
        earlier_title=past.title,
        days_ago=days,
        similarity=round(score, 2),
        question=(
            f"Đơn vị đã mua «{past.title}» cách đây {days} ngày. "
            "Quy chế yêu cầu giải trình khi mua lặp trong thời gian ngắn — "
            "đợt này phục vụ bộ phận nào, và vì sao đợt trước chưa đáp ứng được?"
        ),
    )
