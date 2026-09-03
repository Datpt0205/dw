"""Background sweep: re-read the law under packages still waiting to be signed.

Runs in the API process rather than the worker for a plain reason — re-reading
the law is retrieval plus a model extraction, and the worker builds no model
adapters. It sits beside the mailroom loop, which already established the shape:
a long-lived task holding a proper AccessContext, polling on an interval.

The interval defaults to six hours. Serper's free tier is a fixed grant of
credits and this sweep spends one per waiting case per pass; a tighter loop
would exhaust the grant on a question whose answer changes a few times a year.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import yaml

from dw_agent_runtime.ports import ModelRequest
from dw_knowledge.contracts import SearchQuery
from dw_platform.application.access_context import AccessContext
from dw_platform.application.identity import VerifiedClaims
from dw_tender.application.preparation.law_watch import (
    LawChangeScanner,
    LegalPosition,
)
from dw_tender.application.preparation.legal import (
    LEGAL_WINDOW_QUERY,
    LegalConstraintExtraction,
    numbered_passages,
    verified_constraint,
)
from dw_tender.domain.preparation.entities import PreparationCase

if TYPE_CHECKING:  # pragma: no cover
    from dw_api.bootstrap import ApiContainer

logger = logging.getLogger("dw_api.law_watch")

_POLL_SECONDS_DEFAULT = 21_600  # 6 hours


def _roster_entry(repo_root: Path, subject: str) -> dict[str, Any] | None:
    roster = repo_root / "configs" / "demo" / "demo_users.yaml"
    if not roster.exists():
        return None
    users = yaml.safe_load(roster.read_text(encoding="utf-8")).get("users", [])
    return next((u for u in users if str(u.get("subject")) == subject), None)


class LiveLegalPositionReader:
    """Asks the sources what the window is now, under the same rules as drafting.

    The model is only ever allowed to copy: it returns a number and the sentence
    it came from, and ``verified_constraint`` throws the pair away unless that
    sentence is literally present in a retrieved passage. A watcher with a looser
    rule than the drafting path would raise alarms the package never had to meet.
    """

    def __init__(self, container: ApiContainer) -> None:
        # legal_gateway, not knowledge_gateway: the watcher has to ask the same
        # way the drafting run asked, or it compares two sources rather than two
        # moments in one source.
        self._knowledge = container.legal_gateway
        self._models = container.model_gateway
        self._profile = container.settings.model_profile
        self._container = container

    async def __call__(self, case: PreparationCase, context: AccessContext) -> LegalPosition | None:
        if self._knowledge is None or self._models is None:
            return None
        try:
            hits = await self._knowledge.search(
                SearchQuery(text=LEGAL_WINDOW_QUERY, domain="legal", top_k=3), context
            )
        except Exception:
            # Unreachable sources must not read as "the law changed"; the
            # scanner treats None as "no comparison possible".
            logger.warning("law watch retrieval failed for %s", case.title, exc_info=True)
            return None
        quotes = [chunk.content for chunk in hits if chunk.content]
        if not quotes:
            return None

        run_context = self._container.run_context_for(context, case.id.value)
        try:
            extraction: LegalConstraintExtraction = await self._models.generate_structured(
                ModelRequest(
                    task="preparation.legal_constraints",
                    prompt_id="preparation.extract_legal_constraints",
                    prompt_version="1.0.0",
                    variables={"method_label": "", "passages": numbered_passages(quotes)},
                    model_profile=self._profile,
                ),
                LegalConstraintExtraction,
                run_context=run_context,
            )
        except Exception:
            logger.warning("law watch extraction failed for %s", case.title, exc_info=True)
            return None

        verified = verified_constraint(extraction, quotes)
        if verified is None:
            return None
        return LegalPosition(
            min_bid_preparation_days=int(verified["min_bid_preparation_days"]),
            article_ref=str(verified.get("article_ref") or ""),
            source_quote=str(verified.get("source_quote") or ""),
        )


def start_law_watch(container: ApiContainer, repo_root: Path) -> asyncio.Task[None] | None:
    if os.environ.get("DW_LAW_WATCH_ENABLED", "false").lower() not in ("1", "true", "yes"):
        return None
    if container.preparation is None or container.access_context_factory is None:
        logger.warning("law watch enabled but the preparation slice is not wired — skipping")
        return None
    if os.environ.get("DW_LEGAL_SOURCE", "qdrant") != "web":
        # Against a static corpus the answer cannot move, so the sweep would
        # burn a model call per case to confirm nothing happened.
        logger.info("law watch idle: DW_LEGAL_SOURCE is not 'web'")
        return None

    subject = os.environ.get("DW_LAW_WATCH_SUBJECT", "dev|binh.tran")
    entry = _roster_entry(repo_root, subject)
    if entry is None:
        logger.warning("law watch subject %s not in demo roster — skipping", subject)
        return None

    scanner = LawChangeScanner(
        uow_factory=container.preparation.uow_factory,
        read_current=LiveLegalPositionReader(container),
        rules=container.preparation.rules,
        clock=container.preparation.audit_recorder.clock,
        id_generator=container.preparation.audit_recorder.id_generator,
    )
    interval = int(os.environ.get("DW_LAW_WATCH_INTERVAL_SECONDS", str(_POLL_SECONDS_DEFAULT)))

    async def _loop() -> None:
        logger.info("law watch every %ss as %s", interval, subject)
        while True:
            try:
                factory = container.access_context_factory
                assert factory is not None
                context = await factory.build(
                    VerifiedClaims(subject=subject, email=None, issuer="dw-law-watch"),
                    UUID(str(entry["tenant_id"])),
                    UUID(str(entry["workspace_id"])),
                )
                report = await scanner.poll_once(context)
                for line in report.changed:
                    logger.warning("law changed: %s", line)
                if report.checked or report.skipped:
                    logger.info(
                        "law watch: checked=%d changed=%d skipped=%s",
                        len(report.checked),
                        len(report.changed),
                        list(report.skipped),
                    )
            except Exception:
                logger.exception("law watch pass failed — retrying next interval")
            await asyncio.sleep(interval)

    return asyncio.get_running_loop().create_task(_loop(), name="dw-law-watch")
