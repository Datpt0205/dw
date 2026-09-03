"""The join the live-law feature rests on.

Retrieval changed source — Qdrant to the open web — but the rule that keeps a
model from inventing a legal deadline did not. ``verified_constraint`` accepts a
number only when the sentence carrying it appears verbatim in a retrieved
passage, so web passages have to arrive shaped the way that check expects.

If this ever fails, the visible symptom is not an error: constraints are quietly
discarded, the deterministic default window applies, and the feature looks wired
while doing nothing.
"""

import pytest

from dw_knowledge.adapters.web_law_search import LegalSourceConfig, passages
from dw_tender.application.preparation.legal import (
    LegalConstraintExtraction,
    verified_constraint,
)

pytestmark = pytest.mark.unit


CONFIG = LegalSourceConfig(
    version="1.0.0",
    allowed_domains=frozenset({"vanban.chinhphu.vn"}),
    preferred_order=("vanban.chinhphu.vn",),
    gl="vn",
    hl="vi",
    num=10,
    site_bias="",
    context_terms="luật đấu thầu",
    max_bytes=3_000_000,
    fetch_timeout_seconds=15.0,
    max_pages_per_query=3,
    accept_content_types=("text/html",),
    window_chars=1200,
    max_passages_per_page=3,
    anchors=("thời gian chuẩn bị hồ sơ",),
    cache_ttl_seconds=3600,
    cache_max_entries=8,
)

SENTENCE = (
    "Thời gian chuẩn bị hồ sơ dự thầu đối với đấu thầu rộng rãi trong nước "
    "tối thiểu là 18 ngày, kể từ ngày đầu tiên hồ sơ mời thầu được phát hành "
    "đến ngày có thời điểm đóng thầu."
)
PAGE = ("Phần mở đầu dài dòng. " * 40) + SENTENCE + (" Phần sau không liên quan. " * 40)


def test_web_passages_feed_the_legal_check() -> None:
    found = passages(PAGE, CONFIG)

    verified = verified_constraint(
        LegalConstraintExtraction(
            min_bid_preparation_days=18,
            article_ref="Điều 45 khoản 1",
            source_quote=SENTENCE,
        ),
        found,
    )

    assert verified is not None
    assert verified["min_bid_preparation_days"] == 18
    assert verified["article_ref"] == "Điều 45 khoản 1"


def test_a_number_the_page_never_stated_is_still_rejected() -> None:
    """Moving to the open web must not weaken the fence.

    A page that ranks well is not a page that is right; the check exists exactly
    so a plausible sentence is not enough.
    """
    found = passages(PAGE, CONFIG)

    invented = verified_constraint(
        LegalConstraintExtraction(
            min_bid_preparation_days=90,
            article_ref="Điều 45",
            source_quote="Thời gian chuẩn bị hồ sơ dự thầu tối thiểu là 90 ngày.",
        ),
        found,
    )

    assert invented is None


def test_a_real_sentence_with_the_wrong_number_is_rejected() -> None:
    """Quoting honestly and counting wrong fails too — the number must be in the quote."""
    found = passages(PAGE, CONFIG)

    mismatched = verified_constraint(
        LegalConstraintExtraction(
            min_bid_preparation_days=35,
            article_ref="Điều 45",
            source_quote=SENTENCE,
        ),
        found,
    )

    assert mismatched is None
