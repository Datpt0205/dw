"""Deterministic transcript normalization.

Accepts the common "Speaker: utterance" line format; free text lines attach to
the previous speaker. No model involved — same input, same segments.
"""

from __future__ import annotations

import re

from dw_work_ops.domain.value_objects.transcript import TranscriptSegment

_SPEAKER_LINE = re.compile(r"^\s*(?P<speaker>[^:]{1,80}?)\s*:\s*(?P<text>.+)$")


def parse_transcript(raw_text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    current_speaker = "Không rõ"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        content = " ".join(part.strip() for part in buffer if part.strip())
        if content:
            segments.append(
                TranscriptSegment(index=len(segments), speaker=current_speaker, text=content)
            )
        buffer = []

    for line in raw_text.splitlines():
        if not line.strip():
            continue
        match = _SPEAKER_LINE.match(line)
        if match:
            flush()
            current_speaker = match.group("speaker").strip()
            buffer.append(match.group("text"))
        else:
            buffer.append(line)
    flush()
    return segments


def resolve_speaker_names(
    segments: list[TranscriptSegment], known_names: list[str]
) -> dict[str, str | None]:
    """Map raw speaker labels to known directory names (exact or last-name match)."""
    mapping: dict[str, str | None] = {}
    normalized_known = {name.casefold(): name for name in known_names}
    for segment in segments:
        raw = segment.speaker.strip()
        if raw in mapping:
            continue
        matched = normalized_known.get(raw.casefold())
        if matched is None:
            # try "given name" suffix match, e.g. "An" -> "Nguyễn Văn An"
            candidates = [
                full for key, full in normalized_known.items() if key.endswith(raw.casefold())
            ]
            matched = candidates[0] if len(candidates) == 1 else None
        mapping[raw] = matched
    return mapping
