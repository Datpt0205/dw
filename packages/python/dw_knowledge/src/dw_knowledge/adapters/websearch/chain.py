"""Try providers in order until one gives back something usable.

A single search provider is a single point of failure with a bill attached. When
Serper's one-time grant runs out it answers 403, the caller swallows retrieval
failures by design, and a procurement package is drafted with no legal grounding
at all — no error, no gap in the audit trail, just a deadline taken from the
deterministic default. This exists so that the second, third and fourth engines
get their turn before that happens.

Two separate mechanisms hold a provider back, and they are separate on purpose:

``CircuitBreaker`` — the service is unwell. Timeouts, 5xx, unreadable bodies.
Short reset, because a service that is merely struggling recovers on its own.

``ProviderCooldown`` — the service is fine and we are out of credit. 429, or the
403 a metered free tier sends once a grant is spent. Hours, not seconds: retrying
a spent monthly allowance in thirty seconds buys nothing but another 429.

Collapsing the two into one timer would mean either giving up on a flaky provider
for six hours, or asking an exhausted one two thousand times a day.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from dw_kernel.resilience import CircuitOpenError
from dw_knowledge.adapters.websearch.contracts import (
    SearchAuthError,
    SearchHit,
    SearchParams,
    SearchProviderError,
    SearchQuotaError,
    WebSearchProvider,
)

logger = logging.getLogger("dw_knowledge.websearch")


@dataclass
class ProviderCooldown:
    """Which providers are out of quota, and until when.

    In-process, so a restart forgets. That costs exactly one wasted call per
    provider per restart — the provider says 429 again and goes straight back on
    cooldown. Persisting it would mean a table, a migration and a number that
    can drift out of step with what the provider actually thinks; the 429 is the
    provider's own accounting, and it is never stale.
    """

    default_seconds: float = 21_600.0  # 6 hours
    _until: dict[str, float] = field(default_factory=dict)

    def block(self, provider: str, seconds: float | None = None) -> None:
        self._until[provider] = time.monotonic() + (
            self.default_seconds if seconds is None else seconds
        )

    def blocked(self, provider: str) -> bool:
        until = self._until.get(provider)
        if until is None:
            return False
        if until <= time.monotonic():
            del self._until[provider]
            return False
        return True

    def remaining(self, provider: str) -> float:
        until = self._until.get(provider)
        return max(0.0, until - time.monotonic()) if until is not None else 0.0


@dataclass
class FailoverSearchClient:
    """The configured providers, in the configured order.

    ``providers`` is ordered and the order is the policy: always start at the
    top and walk down. Round-robin would spread the load and stretch the total
    free allowance further, but it would also mean the same question answered
    from a different index on Tuesday than on Monday — and when someone
    challenges a bid deadline, "which engine did we ask" is not a question that
    should have a random answer.
    """

    providers: Sequence[WebSearchProvider]
    cooldown: ProviderCooldown = field(default_factory=ProviderCooldown)
    # An engine that returns nothing has not failed, but for our purposes it has
    # not helped either: no passages means no verified constraint means the
    # default window silently applies. Asking the next one costs a call and can
    # save a wrong deadline.
    advance_on_empty: bool = True

    async def search(
        self,
        params: SearchParams,
        *,
        accept: Callable[[list[SearchHit]], list[SearchHit]] | None = None,
    ) -> tuple[list[SearchHit], str]:
        """Returns the usable hits and the name of whoever supplied them.

        ``accept`` is the caller's definition of "usable" — for legal retrieval
        it is the source allowlist. It has to run inside this loop, not after
        it: a provider that returns ten results from ten sites we do not trust
        has given us nothing, and the chain can only know that if it is the one
        applying the filter.
        """
        if not self.providers:
            raise SearchProviderError("không có nhà cung cấp tìm kiếm nào được cấu hình")

        skipped: list[str] = []
        failures: list[str] = []
        for provider in self.providers:
            name = provider.provider_name
            if self.cooldown.blocked(name):
                skipped.append(f"{name} (hết lượt, còn {self.cooldown.remaining(name) / 60:.0f}p)")
                continue
            try:
                hits = await provider.search(params)
            except SearchAuthError as exc:
                # Same mechanism as an exhausted quota — there is no point
                # asking again — but named for what it is, because this one
                # needs a person to go and fix it.
                self.cooldown.block(name)
                failures.append(f"{name} khoá bị từ chối")
                logger.error("web search: %s — %s", name, exc)
                continue
            except SearchQuotaError as exc:
                self.cooldown.block(name)
                failures.append(f"{name} hết lượt")
                logger.warning(
                    "web search: %s hết lượt, nghỉ %.0f phút — %s",
                    name,
                    self.cooldown.remaining(name) / 60,
                    exc,
                )
                continue
            except CircuitOpenError:
                # The provider's own breaker refused before making a call.
                # Each provider holds its breaker — the chain does not keep a
                # second copy, it just reads the refusal as "skip this one".
                skipped.append(f"{name} (breaker mở)")
                continue
            except SearchProviderError as exc:
                failures.append(f"{name} lỗi")
                logger.warning("web search: %s hỏng — %s", name, exc)
                continue

            usable = accept(hits) if accept is not None else hits
            if not usable and self.advance_on_empty:
                # Logged, and this is not decoration. Measured 2026-08-26: a
                # replay of the whole demo failed every legal query with "mọi
                # nhà cung cấp đều không dùng được", and the only line in the
                # log named the SECOND provider's rejected key. The first had
                # returned results and had them all filtered out, silently, so
                # there was no way to tell a bad key from an allowlist that
                # matched nothing — which are opposite problems with opposite
                # fixes. A branch that ends a query has to say so.
                failures.append(f"{name} 0/{len(hits)} kết quả dùng được")
                logger.warning(
                    "web search: %s trả %d kết quả nhưng không cái nào qua được bộ lọc",
                    name,
                    len(hits),
                )
                continue
            if skipped or failures:
                logger.info(
                    "web search: dùng %s (bỏ qua: %s)",
                    name,
                    "; ".join([*skipped, *failures]),
                )
            return usable, name

        # The reasons go in the message as well as in ``details``: the caller
        # that matters here logs the exception and falls back to the indexed
        # corpus, and it prints the message. Reasons only in ``details`` were
        # reasons nobody read.
        reasons = "; ".join([*skipped, *failures]) or "không rõ"
        raise SearchProviderError(
            f"mọi nhà cung cấp tìm kiếm đều không dùng được ({reasons})",
            details={"skipped": "; ".join(skipped), "failed": "; ".join(failures)},
        )
