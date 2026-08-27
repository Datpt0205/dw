"""Every sentence this feature shows a human, in one place.

Gathered here for one reason: the wording is a hard requirement, not a matter
of style, and a rule spread across six f-strings in six modules cannot be
tested. One module, one test file, one place to look when someone asks whether
the system accuses anybody of anything.

The rule itself predates this feature — see ``repeat_purchase.py`` and the test
that guards its phrasing. Being asked for a paragraph of context is a small
thing; being told by software that you are suspected of something is not, and
the second one is remembered long after the threshold was retuned.

So: talk about the paperwork, never about the person. Ask what is getting in
the way rather than what went wrong. Offer a next step in every message.
"""

from __future__ import annotations

from dw_tender.application.preparation.rework import ReworkAssessment, SupportLevel

# Words that must never reach a user through this feature. Kept as data so the
# test can iterate them, and so adding one is a one-line change.
FORBIDDEN: tuple[str, ...] = ("vi phạm", "sai phạm", "lách", "chia nhỏ")


def support_headline(assessment: ReworkAssessment) -> str:
    """One line for the top of the card.

    Subject is the paperwork, not the requester. "Mấy hồ sơ gần đây" rather
    than "Bạn đã bị trả" — the same fact, and only one of the two reads like
    a reprimand.
    """
    if assessment.level is SupportLevel.BLOCK:
        return (
            f"Hồ sơ gần đây phải chỉnh lại {assessment.block_count} lần trong "
            f"{assessment.block_window_days} ngày — cùng xem lại một chút nhé"
        )
    if assessment.level is SupportLevel.NUDGE:
        return (
            f"Có {assessment.nudge_count} hồ sơ phải chỉnh lại trong "
            f"{assessment.nudge_window_days} ngày qua"
        )
    return ""


def support_lines(assessment: ReworkAssessment) -> list[str]:
    """Body of the card: what was noticed, what usually causes it, what to do."""
    if assessment.level is SupportLevel.NONE:
        return []
    lines: list[str] = []
    if assessment.top_reason_label:
        lines.append(f"Hay gặp nhất: {assessment.top_reason_label}.")
    if assessment.guidance:
        lines.append(assessment.guidance)
    if assessment.level is SupportLevel.BLOCK:
        lines.append(
            "Để tiếp tục tạo hồ sơ mới, bạn mô tả giúp bối cảnh ở phần bên dưới "
            "rồi bên mua sắm sẽ xem và hỗ trợ."
        )
    else:
        lines.append(
            "Nếu có gì đang vướng, mô tả giúp ở phần bên dưới để bên mua sắm "
            "hỗ trợ sớm. Việc hiện tại của bạn vẫn tiếp tục bình thường."
        )
    return lines


def explanation_prompt(assessment: ReworkAssessment) -> str:
    """The question above the form.

    A question about circumstances, with the answer framed as useful to the
    person answering. Not a request to account for oneself.
    """
    if assessment.level is SupportLevel.BLOCK:
        return (
            "Bạn mô tả giúp: đợt vừa rồi có gì đang vướng, và bên mua sắm hỗ trợ "
            "được gì để lần nộp tới trôi hơn?"
        )
    return (
        "Có gì đang làm bạn mất thời gian ở khâu chuẩn bị hồ sơ không? "
        "Mô tả ngắn cũng được — để bên mua sắm biết đường hỗ trợ."
    )


def blocked_message(assessment: ReworkAssessment) -> str:
    """Shown when the server refuses a new case or a submission.

    Says what happened, why, and exactly how to move — a refusal without a way
    forward is where people start working around the system.
    """
    return (
        f"Hồ sơ gần đây phải chỉnh lại {assessment.block_count} lần trong "
        f"{assessment.block_window_days} ngày. Bạn gửi phần mô tả bối cảnh để "
        "bên mua sắm xem và hỗ trợ, sau đó tạo hồ sơ mới tiếp nhé. "
        "Hồ sơ đang làm dở vẫn sửa và lưu được bình thường."
    )


def supporter_lines(assessment: ReworkAssessment, *, creator_label: str) -> list[str]:
    """Card for the person who can help — context, not a case file.

    Names the pattern and the likely cause so the conversation can start
    somewhere concrete, and says outright what the card is for. Someone
    receiving this at 8am should read it as "go help", not "go investigate".
    """
    lines = [
        f"{creator_label} có {assessment.block_count} hồ sơ phải chỉnh lại "
        f"trong {assessment.block_window_days} ngày.",
    ]
    if assessment.top_reason_label:
        lines.append(f"Hay gặp nhất: {assessment.top_reason_label}.")
    lines.append("Bạn xem phần mô tả bối cảnh rồi trao đổi giúp để gỡ vướng nhé.")
    return lines


def escalation_lines(assessment: ReworkAssessment, *, creator_label: str) -> list[str]:
    """Nobody picked the explanation up in time.

    The worst state this whole mechanism can produce is someone blocked and
    waiting on a queue nobody is reading, so this card is about the queue.
    """
    return [
        f"Phần mô tả bối cảnh của {creator_label} chưa có ai xem.",
        "Người gửi đang phải chờ để tạo hồ sơ mới — nhờ bạn phân công người xem giúp.",
    ]
