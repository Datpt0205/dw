"""Structure-aware (parent-child, ordered) chunking for enterprise RAG."""

from __future__ import annotations

import pytest

from dw_knowledge.chunking import structure_aware_chunks

pytestmark = pytest.mark.unit

LEGAL = """Chương II
Điều 14. Hình thức lựa chọn nhà thầu
Các hình thức bao gồm đấu thầu rộng rãi, chào hàng cạnh tranh, chỉ định thầu.

Điều 15. Hạn mức
Chỉ định thầu áp dụng cho gói thầu có giá trị nhỏ theo quy định của Chính phủ.
"""


def test_sections_follow_the_legal_outline() -> None:
    result = structure_aware_chunks(LEGAL)
    paths = [s.path for s in result.sections]
    assert "Chương II > Điều 14. Hình thức lựa chọn nhà thầu" in paths
    assert "Chương II > Điều 15. Hạn mức" in paths


def test_leaves_carry_section_path_and_global_order() -> None:
    result = structure_aware_chunks(LEGAL)
    assert result.chunks, "expected leaf chunks"
    # seq is a dense global order starting at 0.
    assert [c.seq for c in result.chunks] == list(range(len(result.chunks)))
    # every leaf knows its section breadcrumb (used for citation + context).
    assert all(c.section_path for c in result.chunks)
    # a leaf's predecessor is recoverable purely from seq within the document.
    for leaf in result.chunks[1:]:
        assert leaf.seq - 1 == result.chunks[result.chunks.index(leaf) - 1].seq


def test_contextual_text_prepends_breadcrumb_for_embedding() -> None:
    result = structure_aware_chunks(LEGAL)
    leaf = result.chunks[-1]
    assert leaf.contextual_text.startswith(f"[{leaf.section_path}]")
    assert leaf.content in leaf.contextual_text
    # raw content is NOT mutated (used for display/citation).
    assert "[" not in leaf.content[:1]


def test_long_section_splits_into_contiguous_leaves() -> None:
    body = "Câu văn dài lặp lại. " * 400  # well over max_chars
    text = f"Điều 1. Phạm vi\n{body}"
    result = structure_aware_chunks(text, max_chars=500, overlap_chars=60)
    same_section = [c for c in result.chunks if c.section_index == result.chunks[0].section_index]
    assert len(same_section) > 1  # the long section was split
    # split leaves stay ordered and share the same parent section.
    seqs = [c.seq for c in same_section]
    assert seqs == sorted(seqs)
    assert all(c.section_path == same_section[0].section_path for c in same_section)


def test_deterministic() -> None:
    a = structure_aware_chunks(LEGAL)
    b = structure_aware_chunks(LEGAL)
    assert [c.content for c in a.chunks] == [c.content for c in b.chunks]
    assert [c.provenance_hash for c in a.chunks] == [c.provenance_hash for c in b.chunks]


def test_plain_text_without_headings_still_chunks() -> None:
    result = structure_aware_chunks("Một đoạn không có tiêu đề. " * 100, max_chars=400)
    assert result.chunks
    assert result.sections[0].path == ""  # single implicit section
