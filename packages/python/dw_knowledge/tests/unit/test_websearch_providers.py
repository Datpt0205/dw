"""Each engine's dialect, translated — and each engine's "no" understood.

Two things are worth pinning per provider. That its response shape reaches us as
``SearchHit`` (they disagree about nearly every field name: ``link`` vs ``url``,
``snippet`` vs ``description`` vs ``content``). And that the host allowlist is
actually communicated, in whatever form that engine accepts — a chain where the
second provider silently drops the site restriction would answer from anywhere.

No network: ``httpx.MockTransport`` is httpx's own seam, and every provider takes
one so the full request-and-parse path runs for real.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from dw_knowledge.adapters.websearch.contracts import (
    SearchAuthError,
    SearchParams,
    SearchProviderError,
    SearchQuotaError,
)
from dw_knowledge.adapters.websearch.providers.brave import BraveProvider
from dw_knowledge.adapters.websearch.providers.duckduckgo import DuckDuckGoProvider
from dw_knowledge.adapters.websearch.providers.google_cse import GoogleCseProvider
from dw_knowledge.adapters.websearch.providers.serper import SerperProvider
from dw_knowledge.adapters.websearch.providers.tavily import TavilyProvider

pytestmark = pytest.mark.unit


PARAMS = SearchParams(
    query="thời gian chuẩn bị hồ sơ dự thầu",
    sites=("luatvietnam.vn", "vanban.chinhphu.vn"),
)


def transport(
    payload: Any, *, status: int = 200, text: str | None = None
) -> tuple[Any, list[httpx.Request]]:
    """A transport that answers with ``payload`` and records what it was asked."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler), seen


# --- the request each engine is sent ----------------------------------------


@pytest.mark.asyncio
async def test_serper_is_asked_with_the_site_operator_in_the_query() -> None:
    mock, seen = transport({"organic": []})

    await SerperProvider(api_key="k", transport=mock).search(PARAMS)

    body = json.loads(seen[0].content)
    assert "site:luatvietnam.vn OR site:vanban.chinhphu.vn" in body["q"]
    assert seen[0].headers["X-API-KEY"] == "k"


@pytest.mark.asyncio
async def test_brave_carries_its_key_in_its_own_header() -> None:
    mock, seen = transport({"web": {"results": []}})

    await BraveProvider(api_key="k", transport=mock).search(PARAMS)

    assert seen[0].headers["X-Subscription-Token"] == "k"
    assert "site:luatvietnam.vn" in seen[0].url.params["q"]


@pytest.mark.asyncio
async def test_tavily_gets_the_allowlist_as_data_not_as_query_syntax() -> None:
    """The reason ``sites`` is a list and not a Google operator string.

    Tavily filters domains with a real parameter. Handing it ``site:a OR site:b``
    inside the query would leave it searching the whole web and quietly
    returning whatever it liked.
    """
    mock, seen = transport({"results": []})

    await TavilyProvider(api_key="k", transport=mock).search(PARAMS)

    body = json.loads(seen[0].content)
    assert body["include_domains"] == ["luatvietnam.vn", "vanban.chinhphu.vn"]
    assert "site:" not in body["query"]


@pytest.mark.asyncio
async def test_google_cse_sends_both_secrets_and_respects_its_page_cap() -> None:
    mock, seen = transport({"items": []})

    await GoogleCseProvider(api_key="k", engine_id="cx-1", transport=mock).search(
        SearchParams(query="x", count=50)
    )

    params = seen[0].url.params
    assert params["key"] == "k" and params["cx"] == "cx-1"
    assert params["num"] == "10", "API từ chối num > 10 chứ không tự cắt"


# --- the response each engine sends back ------------------------------------


@pytest.mark.asyncio
async def test_serper_reads_link_and_keeps_the_rank_google_gave() -> None:
    mock, _ = transport(
        {
            "organic": [
                {
                    "title": "Điều 45",
                    "link": "https://luatvietnam.vn/a",
                    "snippet": "s",
                    "position": 4,
                },
                {"title": "no link"},
                "rác",
            ]
        }
    )

    hits = await SerperProvider(api_key="k", transport=mock).search(PARAMS)

    assert len(hits) == 1, "dòng thiếu URL và dòng không phải dict đều bị bỏ"
    assert hits[0].url == "https://luatvietnam.vn/a" and hits[0].position == 4


@pytest.mark.asyncio
async def test_brave_calls_the_snippet_a_description_and_numbers_nothing() -> None:
    mock, _ = transport(
        {
            "web": {
                "results": [
                    {"title": "A", "url": "https://luatvietnam.vn/a", "description": "mô tả"},
                    {"title": "B", "url": "https://vanban.chinhphu.vn/b", "description": "hai"},
                ]
            }
        }
    )

    hits = await BraveProvider(api_key="k", transport=mock).search(PARAMS)

    assert [h.snippet for h in hits] == ["mô tả", "hai"]
    assert [h.position for h in hits] == [1, 2], "không đánh số thì lấy thứ tự trả về"


@pytest.mark.asyncio
async def test_tavily_hands_back_the_page_body_so_it_need_not_be_fetched() -> None:
    """The one provider that can reach a JavaScript-rendered source."""
    mock, _ = transport(
        {
            "results": [
                {
                    "title": "Điều 45",
                    "url": "https://luatvietnam.vn/a",
                    "content": "đoạn ngắn",
                    "raw_content": "Toàn văn Điều 45 …",
                },
                {
                    "title": "B",
                    "url": "https://luatvietnam.vn/b",
                    "content": "c",
                    "raw_content": "   ",
                },
            ]
        }
    )

    hits = await TavilyProvider(api_key="k", transport=mock).search(PARAMS)

    assert hits[0].content == "Toàn văn Điều 45 …"
    assert hits[1].content is None, "raw_content rỗng phải rơi về tải trang như thường"


@pytest.mark.asyncio
async def test_duckduckgo_unwraps_its_own_redirect() -> None:
    """A citation pointing at a redirector is not a citation a reader can check."""
    html = """
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fluatvietnam.vn%2Fa&rut=x">
        Điều 45 Luật Đấu thầu
      </a>
      <a class="result__snippet">Thời gian chuẩn bị hồ sơ dự thầu…</a>
    </div>
    """
    mock, _ = transport(None, text=html)

    hits = await DuckDuckGoProvider(transport=mock).search(PARAMS)

    assert len(hits) == 1
    assert hits[0].url == "https://luatvietnam.vn/a"
    assert hits[0].title == "Điều 45 Luật Đấu thầu"


# --- how each engine says no ------------------------------------------------


@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.asyncio
async def test_being_out_of_credit_is_named_as_such_not_as_a_generic_failure(status: int) -> None:
    """The chain reacts differently to these, so they must arrive distinguishable."""
    mock, _ = transport({}, status=status)

    with pytest.raises(SearchQuotaError):
        await SerperProvider(api_key="k", transport=mock).search(PARAMS)


@pytest.mark.asyncio
async def test_a_rejected_key_is_not_reported_as_an_empty_quota() -> None:
    """Measured 2026-08-25: pasting a non-Tavily key returns 401, and 401 was
    being read as "out of credit" — so a typo looked like a provider to wait out,
    and went on a six-hour cooldown saying so. A spent quota fixes itself
    overnight; a wrong key never does."""
    mock, _ = transport({}, status=401)

    with pytest.raises(SearchAuthError) as caught:
        await TavilyProvider(api_key="sai-tien-to", transport=mock).search(PARAMS)

    assert not isinstance(caught.value, SearchQuotaError)
    assert ".env" in str(caught.value), "thông báo phải nói được người đọc cần đi sửa ở đâu"


@pytest.mark.asyncio
async def test_a_server_error_is_a_plain_failure_worth_trying_someone_else_for() -> None:
    mock, _ = transport({}, status=503)

    with pytest.raises(SearchProviderError) as caught:
        await SerperProvider(api_key="k", transport=mock).search(PARAMS)

    assert not isinstance(caught.value, SearchQuotaError)


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_fails_loudly_instead_of_escaping_raw() -> None:
    """Previously ``response.json()`` raised straight through the error handling.

    The breaker recorded neither success nor failure and a ``JSONDecodeError``
    came out of a retrieval call — which the caller catches as "no results",
    the same as a page that genuinely says nothing about the deadline.
    """
    mock, _ = transport(None, text="<html>rate limited</html>")

    with pytest.raises(SearchProviderError):
        await SerperProvider(api_key="k", transport=mock).search(PARAMS)


@pytest.mark.asyncio
async def test_tavily_defaults_to_the_cheaper_depth_because_we_discard_the_expensive_part() -> None:
    """One credit versus two, for something we throw away.

    "advanced" buys Tavily's own passage extraction. We never use it —
    ``passages()`` cuts on sentence boundaries because ``verified_constraint``
    only accepts a quote found verbatim in a passage WE cut. All that is wanted
    here is ``raw_content``. On the free tier that difference is 1,000 searches
    a month against 500.
    """
    mock, seen = transport({"results": []})

    await TavilyProvider(api_key="k", transport=mock).search(PARAMS)

    assert json.loads(seen[0].content)["search_depth"] == "basic"


@pytest.mark.asyncio
async def test_tavily_depth_can_be_raised_when_measurement_says_it_must_be() -> None:
    """Kept configurable rather than decided here: the docs do not say whether
    ``raw_content`` survives a basic search, and that is a question for a live
    call, not for an assumption baked into an adapter."""
    mock, seen = transport({"results": []})

    await TavilyProvider(api_key="k", search_depth="advanced", transport=mock).search(PARAMS)

    assert json.loads(seen[0].content)["search_depth"] == "advanced"
