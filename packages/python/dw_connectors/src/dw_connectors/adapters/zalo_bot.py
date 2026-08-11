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


# Zalo hard-caps one message at 2000 characters; stay under it with room to
# spare so a multi-byte tail never trips the count.
_MAX_CHARS = 1900


def _split_for_zalo(text: str) -> list[str]:
    """Whole message when it fits, else consecutive parts split on line breaks.

    Splitting on lines keeps a card's bullets intact; a single line longer than
    the cap is cut by length as a last resort.
    """
    if len(text) <= _MAX_CHARS:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.splitlines():
        while len(line) > _MAX_CHARS:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:_MAX_CHARS])
            line = line[_MAX_CHARS:]
        candidate = current + "\n" + line if current else line
        if len(candidate) > _MAX_CHARS:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


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

    async def send_message(self, chat_id: str, text: str) -> str:
        """Send plain text, splitting to fit the platform cap.

        Zalo rejects anything over 2000 characters outright — a checkpoint card
        that quotes the retrieved legal basis blows past that, and the whole
        approval silently never arrives. The cap is a property of this channel,
        so it is handled here rather than by every caller. Returns the last
        message id (best effort).
        """
        message_id = ""
        async with httpx.AsyncClient(base_url=f"{_BASE}/bot{self.bot_token}", timeout=15) as client:
            for part in _split_for_zalo(text):
                response = await client.post(
                    "/sendMessage", json={"chat_id": chat_id, "text": part}
                )
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    raise RuntimeError(f"zalo sendMessage failed: {data.get('description')}")
                message_id = str((data.get("result") or {}).get("message_id", ""))
        return message_id
