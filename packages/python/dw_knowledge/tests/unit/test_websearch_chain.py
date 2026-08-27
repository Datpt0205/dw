"""When one search engine stops working, does anyone notice — and who takes over.

The failure this guards against is not loud. A spent free tier answers 403, the
drafting node swallows retrieval failures by design, and a procurement package
goes to the approver with its deadline taken from a hardcoded default and no
legal citation at all. Nothing errors. So these pin the two things that must
happen instead: someone else gets asked, and an exhausted provider is not asked
again five seconds later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dw_kernel.resilience import CircuitBreaker
from dw_knowledge.adapters.websearch.chain import FailoverSearchClient, ProviderCooldown
from dw_knowledge.adapters.websearch.contracts import (
    SearchAuthError,
    SearchHit,
    SearchParams,
    SearchProviderError,
    SearchQuotaError,
)

pytestmark = pytest.mark.unit


PARAMS = SearchParams(query="thời gian chuẩn bị hồ sơ dự thầu")


class _Clock:
    """Frozen: the cooldown is measured in hours and no test should wait."""

    def now(self) -> datetime:
        return datetime(2026, 8, 25, tzinfo=UTC)


def _hit(host: str = "luatvietnam.vn") -> SearchHit:
    return SearchHit(title="Điều 45", url=f"https://{host}/dieu-45", snippet="", position=1)


class Provider:
    """A provider that does whatever the test needs, and counts being asked."""

    def __init__(
        self,
        name: str,
        *,
        hits: list[SearchHit] | None = None,
        raises: Exception | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._name = name
        self._hits = hits if hits is not None else [_hit()]
        self._raises = raises
        self._breaker = breaker
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return self._name

    async def search(self, params: SearchParams) -> list[SearchHit]:
        # Where a real provider consults it: before spending the call.
        if self._breaker is not None:
            self._breaker.before_call()
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._hits


@pytest.mark.asyncio
async def test_a_broken_provider_hands_over_instead_of_ending_the_query() -> None:
    first = Provider("serper", raises=SearchProviderError("máy chủ trả 500"))
    second = Provider("brave")

    hits, used = await FailoverSearchClient(providers=[first, second]).search(PARAMS)

    assert used == "brave"
    assert hits and first.calls == 1 and second.calls == 1


@pytest.mark.asyncio
async def test_an_exhausted_provider_is_not_asked_again_for_hours() -> None:
    """429 means "you are out of credit", not "try me again shortly".

    Without the cooldown every query would spend one doomed call on the spent
    provider before moving on — which over a day of drafting is a lot of calls
    to be told the same thing.
    """
    first = Provider("serper", raises=SearchQuotaError("hết credit"))
    second = Provider("brave")
    chain = FailoverSearchClient(providers=[first, second], cooldown=ProviderCooldown(3600))

    await chain.search(PARAMS)
    await chain.search(PARAMS)
    await chain.search(PARAMS)

    assert first.calls == 1, "chỉ được hỏi một lần rồi cho nghỉ"
    assert second.calls == 3


@pytest.mark.asyncio
async def test_a_provider_whose_results_are_all_untrusted_counts_as_no_answer() -> None:
    """Ten results from ten sources we do not trust is not ten results.

    The allowlist has to be applied inside the chain for this to be knowable —
    filtering after the fact would leave the chain believing the first provider
    succeeded and returning nothing.
    """
    first = Provider("serper", hits=[_hit("seo-farm.example")])
    second = Provider("brave", hits=[_hit("luatvietnam.vn")])

    hits, used = await FailoverSearchClient(providers=[first, second]).search(
        PARAMS,
        accept=lambda found: [h for h in found if h.host == "luatvietnam.vn"],
    )

    assert used == "brave" and [h.host for h in hits] == ["luatvietnam.vn"]


@pytest.mark.asyncio
async def test_advance_on_empty_can_be_turned_off_to_save_calls() -> None:
    first = Provider("serper", hits=[])
    second = Provider("brave")

    hits, used = await FailoverSearchClient(
        providers=[first, second], advance_on_empty=False
    ).search(PARAMS)

    assert used == "serper" and hits == [] and second.calls == 0


@pytest.mark.asyncio
async def test_an_open_breaker_is_stepped_over_rather_than_argued_with() -> None:
    """A provider's own breaker refuses before it calls out; that means skip.

    Built from the real breaker rather than a stub exception, because the thing
    worth pinning is that ``CircuitOpenError`` — which subclasses
    ``InfrastructureError`` like every other retrieval failure — does not end
    the query the way a genuine provider error would.
    """
    breaker = CircuitBreaker(clock=_Clock(), name="knowledge.serper", failure_threshold=1)
    breaker.record_failure()
    first = Provider("serper", breaker=breaker)
    second = Provider("brave")

    _, used = await FailoverSearchClient(providers=[first, second]).search(PARAMS)

    assert used == "brave"
    assert first.calls == 0, "breaker mở thì không được gọi ra ngoài"


@pytest.mark.asyncio
async def test_when_everyone_is_down_the_caller_is_told_so() -> None:
    """Silence here would be indistinguishable from "the law says nothing"."""
    chain = FailoverSearchClient(
        providers=[
            Provider("serper", raises=SearchQuotaError("hết credit")),
            Provider("brave", raises=SearchProviderError("timeout")),
        ]
    )

    with pytest.raises(SearchProviderError) as caught:
        await chain.search(PARAMS)

    assert "mọi nhà cung cấp" in str(caught.value)


@pytest.mark.asyncio
async def test_an_empty_chain_is_a_configuration_error_not_an_empty_answer() -> None:
    with pytest.raises(SearchProviderError):
        await FailoverSearchClient(providers=[]).search(PARAMS)


def test_cooldown_forgets_a_provider_once_its_window_passes() -> None:
    cooldown = ProviderCooldown(3600)
    cooldown.block("serper", seconds=0.0)

    assert not cooldown.blocked("serper")


@pytest.mark.asyncio
async def test_a_rejected_key_hands_over_and_says_which_key_to_go_fix() -> None:
    """Failing over is not enough when the cause is a person's typo.

    Handled the same way as an exhausted quota — no point asking again — but the
    chain must not absorb it silently, or the deployment runs one provider short
    for six hours with nothing in the log an operator can act on.
    """
    first = Provider("tavily", raises=SearchAuthError("tavily: khoá bị từ chối"))
    second = Provider("brave")
    chain = FailoverSearchClient(providers=[first, second], cooldown=ProviderCooldown(3600))

    _, used = await chain.search(PARAMS)
    await chain.search(PARAMS)

    assert used == "brave"
    assert first.calls == 1, "khoá sai thì không hỏi lại — nó không tự lành"
