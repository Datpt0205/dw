"""Render the agent's visible thinking as a styled PNG "thought card".

Zalo bot messages are plain text only — a thought printed as text is
indistinguishable from a normal reply. Rendering it as an image gives the
reasoning its own visual identity (muted card, accent bar, small caption),
like reasoning panels in modern AI chat UIs.
"""

from __future__ import annotations

import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Muted "thought" palette — light card, soft gray text, indigo accent.
_BG = (244, 245, 248)
_ACCENT = (99, 102, 241)
_TITLE = (100, 106, 122)
_TEXT = (71, 77, 94)
_RULE = (222, 225, 232)

_WIDTH = 880
_PAD = 34
_ACCENT_W = 6
_WRAP = 56  # chars per line at 26px DejaVu — fits the card width

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)
_FONT_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
)


def _font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def render_thinking_card(thinking: str, *, max_chars: int = 1200) -> bytes:
    """Thinking text → PNG bytes (safe for any content; wraps + truncates)."""
    title_font = _font(_FONT_BOLD_CANDIDATES, 22)
    body_font = _font(_FONT_CANDIDATES, 26)

    lines: list[str] = []
    for raw in thinking[:max_chars].splitlines():
        raw = raw.strip()
        if not raw:
            continue
        bullet = raw.startswith("•")
        content = raw.lstrip("• ").strip()
        wrapped = textwrap.wrap(content, width=_WRAP) or [""]
        for i, piece in enumerate(wrapped):
            prefix = "•  " if bullet and i == 0 else ("    " if bullet else "")
            lines.append(prefix + piece)

    line_h = 38
    height = _PAD + 34 + 18 + line_h * max(len(lines), 1) + _PAD
    image = Image.new("RGB", (_WIDTH, height), _BG)
    draw = ImageDraw.Draw(image)

    # Accent bar + caption row.
    draw.rounded_rectangle(
        (_PAD - 14, _PAD - 4, _PAD - 14 + _ACCENT_W, height - _PAD + 4),
        radius=3,
        fill=_ACCENT,
    )
    draw.text((_PAD + 6, _PAD), "SUY NGHĨ CỦA TRỢ LÝ", font=title_font, fill=_TITLE)
    rule_y = _PAD + 34
    draw.line((_PAD + 6, rule_y, _WIDTH - _PAD, rule_y), fill=_RULE, width=2)

    y = rule_y + 18
    for line in lines:
        draw.text((_PAD + 6, y), line, font=body_font, fill=_TEXT)
        y += line_h

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
