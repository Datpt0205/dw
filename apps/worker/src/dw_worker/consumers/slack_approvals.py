"""Consumer for durable DW01 Slack notification jobs."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from dw_connectors.adapters.slack_approval_notifier import (
    SlackApprovalMessage,
    SlackMessageRef,
)
from dw_kernel.errors import DWError
from dw_tender.adapters.preparation.notification_store import IntakeNotificationJobStore


class ApprovalNotifierPort(Protocol):
    """Outbound approval-card sender (Slack buttons / Zalo words)."""

    async def send(self, message: SlackApprovalMessage) -> SlackMessageRef: ...


logger = logging.getLogger("dw_worker.slack_approvals")

_PERMANENT_SLACK_ERRORS = {
    "account_inactive",
    "channel_not_found",
    "invalid_auth",
    "invalid_member_id",
    "missing_scope",
    "not_allowed_token_type",
    "token_expired",
    "token_revoked",
    "user_not_found",
}

_SLACK_ERROR_MESSAGES = {
    "account_inactive": "Ứng dụng Slack không còn hoạt động trong workspace.",
    "channel_not_found": "Slack không tìm thấy cuộc trò chuyện với thành viên.",
    "invalid_auth": "Token Slack không hợp lệ.",
    "invalid_member_id": "Member ID Slack không đúng định dạng.",
    "missing_scope": "Ứng dụng Slack chưa được cấp đủ quyền gửi tin nhắn.",
    "not_allowed_token_type": "Loại token Slack hiện tại không được hỗ trợ.",
    "token_expired": "Token Slack đã hết hạn.",
    "token_revoked": "Token Slack đã bị thu hồi hoặc ứng dụng đã bị gỡ.",
    "user_not_found": (
        "Slack không tìm thấy thành viên. Hãy kiểm tra Member ID và bảo đảm "
        "thành viên thuộc đúng workspace đã cài ứng dụng."
    ),
}


def _slack_failure(exc: Exception) -> tuple[str, bool, str]:
    code = ""
    if isinstance(exc, DWError):
        code = str(exc.details.get("slack_error", ""))
    if code:
        message = _SLACK_ERROR_MESSAGES.get(code, "Slack từ chối yêu cầu gửi thông báo.")
        return f"{message} (mã: {code})", code in _PERMANENT_SLACK_ERRORS, code
    return (
        "Chưa thể kết nối tới Slack. Hệ thống sẽ thử lại tự động.",
        False,
        "transient_error",
    )


@dataclass
class SlackApprovalConsumer:
    store: IntakeNotificationJobStore
    notifier: ApprovalNotifierPort
    user_map: dict[str, str]
    web_base_url: str

    async def __call__(self) -> None:
        delivery = await self.store.claim_next()
        if delivery is None:
            return
        job = delivery.job
        if (
            job.event_type.value
            in {
                "intake.approval_requested",
                "intake.approval_escalated",
            }
            and delivery.case_state != "draft"
        ):
            await self.store.mark_cancelled(
                delivery,
                reason=f"case no longer pending intake ({delivery.case_state})",
            )
            return
        # A CP decision card is only worth sending while that checkpoint is
        # actually pending — a stale card would offer buttons for a dead state.
        if job.event_type.value == "cp.approval_requested":
            expected = {
                "CP1": "cp1_pending",
                "CP2": "cp2_pending",
                "CP3": "cp3_pending",
                "CP4": "receiving_bids",
            }.get(str(job.payload.get("checkpoint", "")))
            if expected is not None and delivery.case_state != expected:
                await self.store.mark_cancelled(
                    delivery,
                    reason=f"checkpoint no longer pending ({delivery.case_state})",
                )
                return
        slack_user_id = self.user_map.get(delivery.recipient_subject)
        if not slack_user_id:
            await self.store.mark_failed(
                delivery,
                error="Chưa cấu hình Member ID Slack cho người nhận.",
            )
            return
        payload = job.payload
        estimated_value = payload.get("estimated_value_minor", 0)
        if not isinstance(estimated_value, int | str):
            estimated_value = 0
        raw_lines = payload.get("lines", [])
        lines = tuple(str(item) for item in raw_lines) if isinstance(raw_lines, list) else ()
        raw_buttons = payload.get("buttons", [])
        buttons = (
            tuple(
                {str(k): str(v) for k, v in item.items()}
                for item in raw_buttons
                if isinstance(item, dict)
            )
            if isinstance(raw_buttons, list)
            else ()
        )
        try:
            ref = await self.notifier.send(
                SlackApprovalMessage(
                    message_id=job.id,
                    recipient_slack_user_id=slack_user_id,
                    event_type=job.event_type.value,
                    case_id=uuid.UUID(str(job.case_id.value)),
                    case_title=str(payload.get("title", "Hồ sơ DW01")),
                    web_url=(
                        f"{self.web_base_url.rstrip('/')}/procurement/dw01/cases/"
                        f"{job.case_id.value}"
                    ),
                    source_pr_ref=str(payload.get("source_pr_ref", "")),
                    owner_name=str(payload.get("owner_name", "")),
                    estimated_value_minor=int(estimated_value),
                    currency=str(payload.get("currency", "VND")),
                    comment=str(payload.get("comment", "")),
                    heading=str(payload.get("heading", "")),
                    lines=lines,
                    buttons=buttons,
                    checkpoint=str(payload.get("checkpoint", "")),
                )
            )
        except Exception as exc:
            error, permanent, code = _slack_failure(exc)
            logger.exception(
                "Slack approval delivery failed job=%s slack_error=%s permanent=%s",
                job.id,
                code,
                permanent,
            )
            if permanent:
                await self.store.mark_failed(delivery, error=error)
            else:
                await self.store.mark_retry(delivery, error=error)
            return
        await self.store.mark_sent(delivery, channel=ref.channel, ts=ref.ts)
        logger.info(
            "Slack approval notification sent job=%s event=%s recipient=%s",
            job.id,
            job.event_type.value,
            delivery.recipient_subject,
        )
