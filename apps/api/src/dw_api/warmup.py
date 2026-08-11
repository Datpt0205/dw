"""Keep the self-hosted embedding/rerank models resident.

Measured on the demo box: BGE-M3 answers a query embedding in ~0.2s and the
reranker in ~0.7s — but the FIRST call after a few idle minutes costs 5-9s
each, because the host reclaims the memory the models sit in. A demo hits
exactly that path: nobody talks to the bot for a while, then the first
retrieval of the run pays ~14s and looks broken.

A tiny periodic request keeps them warm. It is a health-keeping ping, not a
feature: failures are ignored and never touch a run.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx

logger = logging.getLogger("dw_api.warmup")

_INTERVAL_SECONDS = 120
_PROBE_TEXT = "làm nóng mô hình"


async def _ping(client: httpx.AsyncClient, embed_url: str | None, rerank_url: str | None) -> None:
    if embed_url:
        await client.post(embed_url.rstrip("/") + "/embed", json={"inputs": _PROBE_TEXT})
    if rerank_url:
        await client.post(
            rerank_url.rstrip("/") + "/rerank",
            json={"query": _PROBE_TEXT, "texts": [_PROBE_TEXT]},
        )


async def _loop(embed_url: str | None, rerank_url: str | None) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            with contextlib.suppress(Exception):  # cosmetic: never break the API
                await _ping(client, embed_url, rerank_url)
            await asyncio.sleep(_INTERVAL_SECONDS)


def start_model_warmup(embed_url: str | None, rerank_url: str | None) -> asyncio.Task[None] | None:
    """Spawn the keep-warm loop when a self-hosted model endpoint is configured."""
    if not embed_url and not rerank_url:
        return None
    logger.info("model warm-up loop started (every %ss)", _INTERVAL_SECONDS)
    return asyncio.get_running_loop().create_task(
        _loop(embed_url, rerank_url), name="dw-model-warmup"
    )
