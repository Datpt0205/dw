"""Knowledge ports. The vector adapter is internal to the gateway package;
business contexts call the gateway, never the vector store."""

from __future__ import annotations

from typing import Protocol

from dw_knowledge.contracts import EvidenceChunk, SearchQuery
from dw_platform.application.access_context import AccessContext


class KnowledgeGatewayPort(Protocol):
    """The only retrieval entry point available to workflow nodes.

    Implementations MUST inject tenant/workspace/ACL filters derived from
    ``context`` before any vector search is executed.
    """

    async def search(
        self,
        query: SearchQuery,
        context: AccessContext,
    ) -> list[EvidenceChunk]: ...
