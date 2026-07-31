"""Slack channel ingress over HTTPS (P8 production path, plan §12.5).

Socket Mode remains the local/demo transport; this endpoint is the production
path: verify signature/timestamp -> ACK fast -> process asynchronously. The
payload handling is byte-identical to Socket Mode (same SlackFrontOfficeService).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("dw_api.routes.slack_channel")

_tasks: set[asyncio.Task[None]] = set()


def _spawn(coroutine: Any) -> None:
    task = asyncio.get_running_loop().create_task(coroutine)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def build_slack_channel_router(front_office: Any, verifier: Any) -> APIRouter:
    router = APIRouter(prefix="/channels/slack", tags=["channels"])

    async def _verified_body(request: Request) -> bytes | None:
        body = await request.body()
        ok = verifier.verify(
            timestamp=request.headers.get("x-slack-request-timestamp", ""),
            signature=request.headers.get("x-slack-signature", ""),
            body=body,
        )
        return body if ok else None

    @router.post("/events")
    async def events(request: Request) -> Response:
        body = await _verified_body(request)
        if body is None:
            return Response(status_code=401)
        payload = json.loads(body)
        # Slack setup handshake
        if payload.get("type") == "url_verification":
            return Response(
                content=json.dumps({"challenge": payload.get("challenge", "")}),
                media_type="application/json",
            )
        # ACK fast; process async — same envelope shape as Socket Mode.
        _spawn(front_office.handle_envelope({"type": "events_api", "payload": payload}))
        return Response(status_code=200)

    @router.post("/interactions")
    async def interactions(request: Request) -> Response:
        body = await _verified_body(request)
        if body is None:
            return Response(status_code=401)
        # Interactivity arrives form-encoded with a JSON `payload` field.
        form = parse_qs(body.decode("utf-8"))
        raw = (form.get("payload") or ["{}"])[0]
        _spawn(
            front_office.handle_envelope({"type": "interactive", "payload": json.loads(raw)})
        )
        return Response(status_code=200)

    return router
