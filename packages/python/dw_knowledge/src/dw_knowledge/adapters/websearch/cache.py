"""Not asking the same question twice, because asking costs quota."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

from dw_knowledge.contracts import EvidenceChunk


@dataclass
class TtlCache:
    """Bounded in-process cache, keyed per tenant.

    Every free search tier is finite, and a single case fires several legal
    queries before the watcher ever re-checks it. This keeps a burst of drafting
    from spending the grant.

    In-process, not Valkey: the API image carries no Redis client, and a cache
    whose whole job is to save quota does not justify a new dependency. The cost
    is that a restart starts cold.

    Tenant-scoped because the query text carries case figures ("hạn mức phê
    duyệt giá trị 300.000.000.000") — that string is tenant data, however public
    the answer to it is.
    """

    ttl_seconds: int
    max_entries: int
    _entries: OrderedDict[str, tuple[float, list[EvidenceChunk]]] = field(
        default_factory=OrderedDict
    )

    def get(self, key: str) -> list[EvidenceChunk] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def put(self, key: str, value: list[EvidenceChunk]) -> None:
        self._entries[key] = (time.monotonic() + self.ttl_seconds, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
