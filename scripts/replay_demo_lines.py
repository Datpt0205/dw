"""Replay the canonical DW01 demo lines against the real model, unattended.

``docs/runbooks/demo-lines.yaml`` is the single source for the demo: the same 16
lines the presenter reads off ``demo_cue.ps1``. Until now they could only be
driven by two people typing into Zalo, which makes "did swapping the model break
the demo?" an expensive question. This replays them through the same code path
the Zalo channel uses — decision engine first, conversation service otherwise —
and prints every reply in full, so a model swap can be judged from a transcript
instead of a live take.

It asserts nothing. ``chat_scenarios.py`` is the pass/fail harness; this one
produces evidence for a human to read.

The image has no ``docs/``, so copy the lines in first:

    docker compose --env-file .env -f infra/compose/docker-compose.yml \
        cp docs/runbooks/demo-lines.yaml api:/tmp/demo-lines.yaml
    docker compose --env-file .env -f infra/compose/docker-compose.yml \
        exec -T api python - < scripts/replay_demo_lines.py

Reset first, exactly as for a real demo:

    bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

LINES = Path(os.environ.get("DW_DEMO_LINES", "/tmp/demo-lines.yaml"))
ROSTER = Path("/app/configs/demo/demo_users.yaml")
# The YAML's own `wait` values are tuned for a human demo. Scale them here when
# a slower model needs longer, rather than editing the source of truth.
WAIT_SCALE = float(os.environ.get("DW_DEMO_WAIT_SCALE", "1.0"))


def _rendered(reply: Any) -> str:
    """Everything a channel would put on screen for one ChatReply.

    ``text`` alone is the lead-in sentence. The summary card the demo actually
    talks about ("thẻ tóm tắt hiện ra với 2000") lives in ``summary_lines``, and
    the case picker in ``case_options`` — printing only ``text`` makes a correct
    turn look empty.
    """
    parts = [reply.text]
    parts += [f"    • {line}" for line in getattr(reply, "summary_lines", ())]
    parts += [
        f"    [{index}] {title}"
        for index, (_, title) in enumerate(getattr(reply, "case_options", ()), start=1)
    ]
    return "\n".join(p for p in parts if p)


class Chat:
    """One person, one Zalo thread, replaying the channel's own ordering.

    Mirrors ``Chat`` in ``chat_scenarios.py``. Both scripts are piped in on
    stdin (the image ships ``scripts/`` but nothing importable between them),
    so the ordering rule lives in two places; change it in both.
    """

    def __init__(self, container: Any, context: Any, name: str, key: str) -> None:
        from dw_api.channels.decisions import DecisionEngine

        self.svc = container.conversation_service
        self.engine = DecisionEngine(
            container=container, conversation_service=self.svc, channel_label="zalo"
        )
        self.context = context
        self.name = name
        self.key = key

    async def say(self, text: str) -> tuple[str, bool, float]:
        """Returns (reply, went_through_decision_engine, seconds).

        A turn that raises is reported and the replay continues, mirroring the
        channel: ``zalo.py`` answers with an apology and its polling loop keeps
        going, so one bad turn must not end the transcript here either.
        """
        started = time.monotonic()
        active = await self.svc.store.find_active(
            tenant_id=self.context.tenant_id,
            workspace_id=self.context.workspace_id,
            channel_key=self.key,
        )
        try:
            if not self.svc.is_mid_intake(active):
                reply = await self.engine.try_text(text, self.context, self.name)
                if reply is not None:
                    return reply, True, time.monotonic() - started
            outcome = await self.svc.handle_message(
                channel_key=self.key, text=text, context=self.context, display_name=self.name
            )
            reply = "\n".join(_rendered(r) for r in outcome.replies)
        except Exception as exc:
            reply = f"⚠️ LỖI {type(exc).__name__}: {exc}"
        return reply, False, time.monotonic() - started


async def main() -> None:
    from dw_api import bootstrap
    from dw_platform.application.identity import VerifiedClaims

    container = bootstrap.build_container()
    assert container.conversation_service is not None, "conversation service is not wired"
    identity = container.access_context_factory
    assert identity is not None

    settings = container.settings
    print(f"profile={settings.model_profile}  provider={settings.model_provider}")

    people = {u["subject"]: u for u in yaml.safe_load(ROSTER.read_text(encoding="utf-8"))["users"]}
    doc = yaml.safe_load(LINES.read_text(encoding="utf-8"))
    lines = doc["lines"]

    async def chat(subject: str, key: str) -> Chat:
        entry = people[subject]
        context = await identity.build(
            VerifiedClaims(subject=subject, email=None, issuer="dw-zalo"),
            uuid.UUID(str(entry["tenant_id"])),
            uuid.UUID(str(entry["workspace_id"])),
        )
        return Chat(container, context, str(entry["display_name"]), key)

    # One thread per person for the whole run — the slot memory the demo relies
    # on lives in the conversation keyed by these.
    suffix = uuid.uuid4().hex[:6]
    speakers = {
        "an": await chat("dev|an.nguyen", f"zalo:an-{suffix}"),
        "chi": await chat("dev|chi.le", f"zalo:chi-{suffix}"),
    }

    total = 0.0
    for index, line in enumerate(lines, start=1):
        if line.get("scene"):
            print(f"\n{'=' * 70}\n{line['scene']}\n{'=' * 70}")
        speaker = speakers[line["who"]]
        text = " ".join(str(line["text"]).split())
        reply, via_engine, seconds = await speaker.say(text)
        total += seconds
        tag = " [decision]" if via_engine else ""
        print(f"\n[{index:02d}] {speaker.name} ({seconds:.1f}s){tag}")
        print(f"  > {text}")
        print("  < " + (reply or "(không có phản hồi)").replace("\n", "\n    "))
        if line.get("note"):
            print(f"  ~ kỳ vọng: {' '.join(str(line['note']).split())}")
        wait = float(line.get("wait", 0)) * WAIT_SCALE
        if wait:
            print(f"  … chờ {wait:.0f}s cho workflow chạy")
            await asyncio.sleep(wait)

    print(f"\n{'=' * 70}")
    print(
        f"{len(lines)} dòng, tổng {total:.0f}s gọi model, trung bình {total / len(lines):.1f}s/dòng"
    )


asyncio.run(main())
