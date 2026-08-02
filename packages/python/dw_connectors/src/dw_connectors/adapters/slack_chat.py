"""Slack chat channel adapter: outbound messages + Socket Mode inbound.

Front-office channel for the DW01 chat intake (conversation-first plan P1).
This adapter only *transports*: it verifies nothing about business state and
carries no authorization — identity mapping and AccessContext are built by the
API glue from verified configuration, never from Slack display names.

Socket Mode is the local/demo transport (no public callback URL needed): the
app opens a websocket via ``apps.connections.open`` (app-level ``xapp-`` token)
and receives the same Events API + interactivity payloads. Envelopes are ACKed
immediately (Slack requires <3s) and processed asynchronously — plan §12.5.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from websockets.asyncio.client import ClientConnection, connect

from dw_kernel.errors import InfrastructureError
from dw_kernel.net_guard import ensure_allowed_outbound_url

_API_BASE = "https://slack.com/api"

logger = logging.getLogger("dw_connectors.slack_chat")


@dataclass
class SlackChatClient:
    """Minimal outbound client: post/update messages in a channel or thread."""

    bot_token: str
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.bot_token.startswith("xoxb-"):
            raise InfrastructureError("SLACK_BOT_TOKEN missing or not a bot token (xoxb-...)")
        ensure_allowed_outbound_url(_API_BASE)

    async def post_message(
        self,
        *,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "channel": channel,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = await self._call("/chat.postMessage", payload)
        return str(data.get("ts", ""))

    async def download_file(self, url: str, *, max_bytes: int = 10 * 1024 * 1024) -> bytes:
        """Download a user-shared file (url_private) with the bot token.

        Requires the ``files:read`` scope. Slack file hosts are public
        (files.slack.com) so the outbound guard allows them.
        """
        ensure_allowed_outbound_url(url)
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.bot_token}"},
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content
        if not content or len(content) > max_bytes:
            raise InfrastructureError(
                "file download empty or exceeds limit", details={"bytes": len(content)}
            )
        # Slack returns an HTML login page instead of bytes when the token
        # lacks files:read — fail loudly rather than storing garbage.
        if content[:15].lower().startswith(b"<!doctype html") or content[:6].lower() == b"<html>":
            raise InfrastructureError("Slack returned HTML — missing files:read scope?")
        return content

    async def update_message(
        self,
        *,
        channel: str,
        ts: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"channel": channel, "ts": ts, "text": text}
        # Explicit empty list clears old blocks (e.g. disabling stale buttons).
        payload["blocks"] = blocks or []
        await self._call("/chat.update", payload)

    async def publish_home_view(self, *, user_id: str, blocks: list[dict[str, Any]]) -> None:
        """P7 App Home: publish the user's personal "Việc của tôi" tab."""
        await self._call(
            "/views.publish",
            {"user_id": user_id, "view": {"type": "home", "blocks": blocks}},
        )

    async def _call(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=_API_BASE,
                headers={"Authorization": f"Bearer {self.bot_token}"},
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InfrastructureError(
                "Slack request failed", details={"endpoint": endpoint}
            ) from exc
        if not data.get("ok"):
            raise InfrastructureError(
                "Slack rejected the request",
                details={"endpoint": endpoint, "slack_error": str(data.get("error", "unknown"))},
            )
        return dict(data)


PayloadHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class SlackSocketModeRunner:
    """Long-lived Socket Mode loop: connect → ack fast → dispatch async.

    ``handler`` receives the raw envelope (``type`` in {"events_api",
    "interactive", "slash_commands"}). One bad payload must never kill the
    loop; handler errors are logged and swallowed here.
    """

    app_token: str
    handler: PayloadHandler
    timeout_seconds: float = 15.0
    _tasks: set[asyncio.Task[None]] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.app_token.startswith("xapp-"):
            raise InfrastructureError("SLACK_APP_TOKEN missing or not an app token (xapp-...)")
        ensure_allowed_outbound_url(_API_BASE)

    async def run_forever(self) -> None:
        backoff = 1.0
        while True:
            try:
                url = await self._open_connection_url()
                logger.info("slack socket-mode connecting")
                async with connect(url, max_size=2**22) as ws:
                    backoff = 1.0
                    async for raw in ws:
                        if await self._on_frame(ws, raw):
                            break  # server asked us to reconnect
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("slack socket error (%s); retry in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _on_frame(self, ws: ClientConnection, raw: str | bytes) -> bool:
        """Returns True when the connection should be re-established."""
        try:
            message = json.loads(raw)
        except ValueError:
            return False
        kind = message.get("type")
        if kind == "hello":
            logger.info("slack socket-mode connected")
            return False
        if kind == "disconnect":
            logger.info("slack socket-mode disconnect requested (%s)", message.get("reason"))
            return True
        envelope_id = message.get("envelope_id")
        if envelope_id:
            # ACK before processing — Slack redelivers after ~3s of silence.
            await ws.send(json.dumps({"envelope_id": envelope_id}))
        if kind in ("events_api", "interactive", "slash_commands"):
            task = asyncio.get_running_loop().create_task(self._safe_handle(message))
            self._tasks.add(task)  # keep a strong reference until done
            task.add_done_callback(self._tasks.discard)
        return False

    async def _safe_handle(self, envelope: dict[str, Any]) -> None:
        try:
            await self.handler(envelope)
        except Exception:
            logger.exception("slack payload handling failed (type=%s)", envelope.get("type"))

    async def _open_connection_url(self) -> str:
        async with httpx.AsyncClient(
            base_url=_API_BASE,
            headers={"Authorization": f"Bearer {self.app_token}"},
            timeout=self.timeout_seconds,
        ) as client:
            response = await client.post("/apps.connections.open")
            response.raise_for_status()
            data = response.json()
        if not data.get("ok") or not data.get("url"):
            raise InfrastructureError(
                "apps.connections.open failed",
                details={"slack_error": str(data.get("error", "unknown"))},
            )
        return str(data["url"])
