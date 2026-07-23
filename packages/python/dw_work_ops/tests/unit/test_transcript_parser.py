import pytest

from dw_work_ops.adapters.transcript.parser import parse_transcript, resolve_speaker_names

pytestmark = pytest.mark.unit

SAMPLE = """Lê Thị Chi: Bắt đầu họp giao ban tuần.
Nguyễn Văn An: Em báo cáo dự báo nhu cầu.
tiếp tục phần bổ sung không có tên người nói.
Trần Thị Bình: Phòng Mua hàng đề xuất phát hành RFQ sớm.
"""


def test_parse_transcript_deterministic_segments() -> None:
    first = parse_transcript(SAMPLE)
    second = parse_transcript(SAMPLE)
    assert first == second
    assert [s.speaker for s in first] == ["Lê Thị Chi", "Nguyễn Văn An", "Trần Thị Bình"]
    # continuation line attaches to the previous speaker
    assert "bổ sung" in first[1].text
    assert [s.index for s in first] == [0, 1, 2]


def test_parse_transcript_empty() -> None:
    assert parse_transcript("   \n\n ") == []


def test_resolve_speaker_names_exact_and_suffix() -> None:
    segments = parse_transcript("Chi: chào\nAn: dạ\nNgười lạ: ai đó\n")
    known = ["Lê Thị Chi", "Nguyễn Văn An", "Trần Thị Bình"]
    mapping = resolve_speaker_names(segments, known)
    assert mapping["Chi"] == "Lê Thị Chi"
    assert mapping["An"] == "Nguyễn Văn An"
    assert mapping["Người lạ"] is None


def test_resolve_ambiguous_suffix_returns_none() -> None:
    segments = parse_transcript("An: xin chào\n")
    mapping = resolve_speaker_names(segments, ["Nguyễn Văn An", "Phạm Hoàng An"])
    assert mapping["An"] is None, "ambiguous names must not be silently guessed"
