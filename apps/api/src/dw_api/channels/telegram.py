"""Telegram bot intake: drop a transcript into chat → full work_ops run.

Long-polling (getUpdates) — no public webhook/tunnel needed for local dev.
The channel is intake/notify ONLY:

- identity: telegram user id → demo subject via configs/demo/channel_identities.yaml,
  then the normal DB membership check builds the AccessContext (a wrong or
  unmapped id gets a polite refusal — chat is never authorization);
- the run pauses at approval exactly like the web flow; the bot replies with
  the analysis summary and a link to the approval page.
"""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
import yaml

from dw_platform.application.identity import VerifiedClaims

if TYPE_CHECKING:
    from dw_api.bootstrap import ApiContainer

logger = logging.getLogger("dw_api.channels.telegram")

_MIN_TRANSCRIPT_CHARS = 60


@dataclass
class TelegramBotService:
    """Poll Telegram and drive the meeting-to-action flow end to end."""

    container: ApiContainer
    bot_token: str
    repo_root: Path
    web_base_url: str = "http://localhost:3000"
    poll_timeout: int = 25
    _offset: int = field(default=0, init=False)

    # ------------------------------------------------------------------ api --
    async def run_forever(self) -> None:
        logger.info("telegram bot polling started")
        backoff = 1.0
        while True:
            try:
                updates = await self._get_updates()
                backoff = 1.0
                for update in updates:
                    self._offset = max(self._offset, int(update["update_id"]) + 1)
                    try:
                        await self._handle_update(update)
                    except Exception:  # one bad message must not kill the loop
                        logger.exception("telegram update failed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("telegram poll error (%s); retry in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    # ------------------------------------------------------------- telegram --
    async def _get_updates(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{self.bot_token}",
            timeout=self.poll_timeout + 10,
        ) as client:
            response = await client.get(
                "/getUpdates",
                params={
                    "offset": self._offset,
                    "timeout": self.poll_timeout,
                    "allowed_updates": '["message"]',
                },
            )
            response.raise_for_status()
            data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram getUpdates failed: {data.get('description')}")
        return list(data.get("result", []))

    async def _send(self, chat_id: int, text: str) -> None:
        async with httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{self.bot_token}", timeout=15
        ) as client:
            await client.post(
                "/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )

    # ------------------------------------------------------------- identity --
    def _resolve_subject(self, telegram_user_id: int) -> str | None:
        path = self.repo_root / "configs" / "demo" / "channel_identities.yaml"
        if not path.exists():
            return None
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        mapping = raw.get("telegram") or {}
        value = mapping.get(str(telegram_user_id))
        return str(value) if value else None

    def _roster_entry(self, subject: str) -> dict[str, Any] | None:
        path = self.repo_root / "configs" / "demo" / "demo_users.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for user in raw.get("users", []):
            if user["subject"] == subject:
                return dict(user)
        return None

    # -------------------------------------------------------------- handler --
    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        from_id = message.get("from", {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or from_id is None or not text:
            return

        subject = self._resolve_subject(int(from_id))
        if text.startswith("/start") or subject is None:
            await self._send(chat_id, self._onboarding_text(int(from_id), subject))
            return
        if len(text) < _MIN_TRANSCRIPT_CHARS or ":" not in text:
            await self._send(
                chat_id,
                "Gửi tôi <b>transcript cuộc họp</b> (mỗi dòng dạng "
                "<code>Tên người nói: nội dung</code>) — tôi sẽ tóm tắt, phân tích "
                "và đề xuất giao việc.",
            )
            return

        await self._send(chat_id, "⏳ Đã nhận transcript — đang phân tích cuộc họp…")
        try:
            reply = await self._process_transcript(subject, text)
        except Exception as exc:
            logger.exception("telegram transcript processing failed")
            reply = f"❌ Không xử lý được: {html.escape(str(exc)[:200])}"
        await self._send(chat_id, reply)

    def _onboarding_text(self, from_id: int, subject: str | None) -> str:
        if subject:
            return (
                f"✅ Bạn đang được map với <b>{html.escape(subject)}</b>.\n"
                "Gửi transcript cuộc họp (mỗi dòng <code>Tên: nội dung</code>) "
                "để tôi phân tích và đề xuất giao việc."
            )
        return (
            "👋 Chào bạn! Telegram ID của bạn là "
            f"<code>{from_id}</code>.\n"
            "Nhờ quản trị viên thêm dòng sau vào "
            "<code>configs/demo/channel_identities.yaml</code> rồi nhắn lại:\n"
            f'<code>  "{from_id}": dev|an.nguyen</code>'
        )

    # ----------------------------------------------------------------- flow --
    async def _process_transcript(self, subject: str, transcript: str) -> str:
        container = self.container
        if container.work_ops is None or container.access_context_factory is None:
            raise RuntimeError("work_ops slice is not configured")
        entry = self._roster_entry(subject)
        if entry is None:
            raise RuntimeError(f"subject {subject} not in demo roster")

        # Same trust path as the web: claims + DB membership → AccessContext.
        context = await container.access_context_factory.build(
            VerifiedClaims(subject=subject, email=None, issuer="dw-telegram"),
            UUID(str(entry["tenant_id"])),
            UUID(str(entry["workspace_id"])),
        )

        from dw_work_ops.application.handlers import CreateMeetingCommand

        now = datetime.now(tz=UTC)
        meeting_id = await container.work_ops.create_meeting.handle(
            CreateMeetingCommand(
                title=f"Họp qua Telegram {now.strftime('%d/%m %H:%M')}",
                occurred_at=now,
                transcript_text=transcript,
                transcript_filename="telegram.txt",
            ),
            context,
        )
        await container.work_ops.generate_actions.handle(meeting_id, context)
        meeting = await container.work_ops.get_meeting.handle(meeting_id, context)

        headline = ""
        if meeting.summary and isinstance(meeting.summary.get("headline"), str):
            headline = str(meeting.summary["headline"])
        analysis: dict[str, Any] = dict(meeting.analysis or {})
        score = analysis.get("effectiveness_score")
        went_well = [dict(p) for p in analysis.get("went_well") or [] if isinstance(p, dict)]
        needs = [dict(p) for p in analysis.get("needs_improvement") or [] if isinstance(p, dict)]
        recommendations = list(analysis.get("recommendations") or [])

        lines = [f"📋 <b>{html.escape(headline or meeting.title)}</b>", ""]
        if score is not None:
            lines.append(f"⭐ Chất lượng họp: <b>{score}/10</b>")
        if went_well:
            lines.append("✅ <b>Điểm tốt:</b>")
            lines += [f"  • {html.escape(str(p.get('point', '')))}" for p in went_well[:3]]
        if needs:
            lines.append("⚠️ <b>Cần cải thiện:</b>")
            lines += [f"  • {html.escape(str(p.get('point', '')))}" for p in needs[:3]]
        if recommendations:
            lines.append("💡 <b>Lần sau nên:</b>")
            lines += [f"  • {html.escape(str(r))}" for r in recommendations[:3]]
        lines.append("")
        lines.append(
            f"🗒 {len(meeting.decisions)} quyết định · {len(meeting.actions)} việc cần giao"
        )
        for action in meeting.actions[:5]:
            assignee = action.assignee_display_name or "chưa rõ người nhận"
            lines.append(f"  → {html.escape(action.title)} — {html.escape(assignee)}")
        lines.append("")
        lines.append(
            "⏸ Việc CHƯA được giao — cần phê duyệt: "
            f'<a href="{self.web_base_url}/approvals">mở trang Phê duyệt</a> · '
            f'<a href="{self.web_base_url}/meetings/{meeting.id}">xem chi tiết</a>'
        )
        return "\n".join(lines)


def start_telegram_bot(
    container: ApiContainer, bot_token: str, repo_root: Path
) -> asyncio.Task[None]:
    """Spawn the polling loop as a background task (cancelled on shutdown)."""
    service = TelegramBotService(container=container, bot_token=bot_token, repo_root=repo_root)
    return asyncio.get_running_loop().create_task(service.run_forever())
