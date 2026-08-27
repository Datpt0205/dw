"""What every search provider returns, whoever it is.

``SearchHit`` was already provider-neutral when it lived in the law adapter —
title, url, snippet, rank is what a search engine gives you, and nothing in it
is Serper's. Moving it here just states that out loud, so a second provider has
something to target other than "whatever the Serper client happens to produce".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from dw_kernel.errors import InfrastructureError


@dataclass(frozen=True)
class SearchHit:
    """One result from a search engine, before anyone decides to trust it."""

    title: str
    url: str
    snippet: str
    position: int
    # Some engines (Tavily) return the page body with the result. When they do,
    # fetching the URL again is a second round trip for text we already hold —
    # and it is the only way past a source that renders with JavaScript.
    content: str | None = None

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()


@dataclass(frozen=True)
class SearchParams:
    """One question, in terms every engine understands.

    Deliberately not a config object. The previous shape handed the whole legal
    source policy to the HTTP client, which meant the client read ``site_bias``
    — a string of Google ``site:`` syntax — and no non-Google provider could
    honour it. Here the caller says *which hosts it wants*; rendering that into
    a query operator, an ``include_domains`` array or nothing at all is each
    provider's own business.
    """

    query: str
    country: str = "vn"
    language: str = "vi"
    count: int = 10
    sites: tuple[str, ...] = ()

    def site_operator(self) -> str:
        """``site:a OR site:b`` — for the engines that speak Google's dialect."""
        return " OR ".join(f"site:{host}" for host in self.sites)


class WebSearchProvider(Protocol):
    """One search integration (serper, brave, tavily, ...).

    Mirrors ``ModelProviderAdapter``: a name for logs and breaker keys, and one
    async call. Providers raise and never swallow — deciding whether a failure
    is worth moving to the next provider belongs to the chain, not here.
    """

    @property
    def provider_name(self) -> str: ...

    async def search(self, params: SearchParams) -> list[SearchHit]: ...


class SearchProviderError(InfrastructureError):
    """This provider failed. Another one might not."""


class SearchQuotaError(SearchProviderError):
    """This provider is out of quota — 429, or 403 on a metered free tier.

    Split from the plain failure because the right reaction is different in
    kind, not degree: a timeout is worth retrying in half a minute, a spent
    monthly grant is not worth retrying today.
    """


class SearchAuthError(SearchProviderError):
    """The key was rejected — 401. Not the same thing as being out of credit.

    Handled identically by the chain (step over it, stop asking for a while)
    but reported differently, and that difference is the whole point. A spent
    quota fixes itself overnight; a mistyped key never does, and an operator
    who reads "out of quota" will wait for a morning that never comes.
    """
