"""Zalo Bot Platform client (bot.zaloplatforms.com) — Telegram-style dialect.

Token rides in the URL; ``getUpdates`` long-polls (no public webhook needed
for local dev); ``sendMessage`` posts plain text. Responses wrap payloads in
{"ok": bool, "result": ..., "description": ...} exactly like Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

_BASE = "https://bot-api.zaloplatforms.com"


@dataclass(frozen=True)
class ZaloBotClient:
    bot_token: str
    poll_timeout: int = 25

    async def get_updates(self, offset: int) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            base_url=f"{_BASE}/bot{self.bot_token}", timeout=self.poll_timeout + 10
        ) as client:
            response = await client.get(
                "/getUpdates",
                params={"offset": offset, "timeout": self.poll_timeout},
            )
            response.raise_for_status()
            data = response.json()
        if not data.get("ok"):
            # Zalo deviates from Telegram here: an empty poll returns
            # ok=false + 408 "Request timeout" instead of an empty result.
            if data.get("error_code") == 408:
                return []
            raise RuntimeError(f"zalo getUpdates failed: {data.get('description')}")
        # Second deviation (captured live): ``result`` is ONE event object
        # ({"message": ..., "event_name": ...}), not a list of updates, and
        # delivery is fire-once (no update_id/offset ack). Normalize to a list
        # and stay tolerant should batching ever appear.
        result = data.get("result")
        if isinstance(result, dict):
            return [result]
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []

    async def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        """Native 'đang nhập…' indicator — auto-clears when a message lands."""
        async with httpx.AsyncClient(base_url=f"{_BASE}/bot{self.bot_token}", timeout=10) as client:
            await client.post("/sendChatAction", json={"chat_id": chat_id, "action": action})

    async def send_photo(self, chat_id: str, image_png: bytes, filename: str = "card.png") -> str:
        """Send a PNG (multipart) — used for styled 'thinking card' images."""
        async with httpx.AsyncClient(base_url=f"{_BASE}/bot{self.bot_token}", timeout=30) as client:
            response = await client.post(
                "/sendPhoto",
                data={"chat_id": chat_id},
                files={"photo": (filename, image_png, "image/png")},
            )
            response.raise_for_status()
            data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"zalo sendPhoto failed: {data.get('description')}")
        result = data.get("result") or {}
        return str(result.get("message_id", ""))

    async def send_message(self, chat_id: str, text: str) -> str:
        """Send plain text; returns the message id (best effort)."""
        async with httpx.AsyncClient(base_url=f"{_BASE}/bot{self.bot_token}", timeout=15) as client:
            response = await client.post("/sendMessage", json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
            data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"zalo sendMessage failed: {data.get('description')}")
        result = data.get("result") or {}
        return str(result.get("message_id", ""))
