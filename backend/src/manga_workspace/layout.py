from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from .models import BoundingBox


class TextMeasurer(Protocol):
    def measure(self, text: str, font_size: int) -> tuple[float, float]:
        """Return text width and height in pixels for the requested font size."""


@dataclass(frozen=True)
class TextLine:
    text: str
    x: float
    y: float
    width: float
    height: float
    font_size: int


@dataclass(frozen=True)
class TextLayout:
    lines: tuple[TextLine, ...]
    font_size: int
    fits: bool


def oval_width_at_y(bbox: BoundingBox, y: float, margin: int = 0) -> float:
    """Return the available horizontal chord width inside an oval bubble."""
    inner = bbox.inset(margin)
    radius_x = inner.width / 2
    radius_y = inner.height / 2
    if radius_x <= 0 or radius_y <= 0:
        return 0

    normalized_y = (y - inner.center_y) / radius_y
    if abs(normalized_y) >= 1:
        return 0
    return 2 * radius_x * math.sqrt(max(0, 1 - normalized_y * normalized_y))


def find_largest_font_layout(
    text: str,
    bbox: BoundingBox,
    measurer: TextMeasurer,
    *,
    min_size: int = 8,
    max_size: int = 48,
    margin: int = 10,
    line_spacing: float = 1.12,
) -> TextLayout:
    """Binary-search the largest font size that fits inside an oval bubble."""
    min_size = max(1, min_size)
    max_size = max(min_size, max_size)
    best: TextLayout | None = None

    low = min_size
    high = max_size
    while low <= high:
        font_size = (low + high) // 2
        layout = layout_text_in_oval(
            text,
            bbox,
            measurer,
            font_size=font_size,
            margin=margin,
            line_spacing=line_spacing,
        )
        if layout.fits:
            best = layout
            low = font_size + 1
        else:
            high = font_size - 1

    return best or layout_text_in_oval(
        text,
        bbox,
        measurer,
        font_size=min_size,
        margin=margin,
        line_spacing=line_spacing,
    )


def layout_text_in_oval(
    text: str,
    bbox: BoundingBox,
    measurer: TextMeasurer,
    *,
    font_size: int,
    margin: int = 10,
    line_spacing: float = 1.12,
) -> TextLayout:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return TextLayout(lines=(), font_size=font_size, fits=True)

    line_height = _line_height(measurer, font_size, line_spacing)
    inner_height = max(1, bbox.height - margin * 2)
    max_lines = max(1, int(inner_height // line_height))
    tokens, separator = _tokens_for_wrapping(normalized)

    raw_lines, overflowed = _wrap_tokens(
        tokens,
        separator,
        bbox,
        measurer,
        font_size=font_size,
        line_height=line_height,
        max_lines=max_lines,
        margin=margin,
    )

    total_height = line_height * len(raw_lines)
    y_start = bbox.y + (bbox.height - total_height) / 2
    laid_out: list[TextLine] = []
    width_overflowed = False

    for index, line in enumerate(raw_lines):
        width, height = measurer.measure(line, font_size)
        y = y_start + index * line_height
        center_y = y + line_height / 2
        available_width = oval_width_at_y(bbox, center_y, margin=margin)
        if width > available_width + 0.5:
            width_overflowed = True
        laid_out.append(
            TextLine(
                text=line,
                x=bbox.center_x - width / 2,
                y=y,
                width=width,
                height=height,
                font_size=font_size,
            )
        )

    height_fits = total_height <= inner_height + 0.5
    return TextLayout(
        lines=tuple(laid_out),
        font_size=font_size,
        fits=not overflowed and not width_overflowed and height_fits,
    )


def _line_height(measurer: TextMeasurer, font_size: int, line_spacing: float) -> int:
    _, measured_height = measurer.measure("Ag", font_size)
    return max(1, math.ceil(measured_height * line_spacing))


def _tokens_for_wrapping(text: str) -> tuple[list[str], str]:
    if " " not in text:
        return list(text), ""
    return text.split(" "), " "


def _join(current: str, token: str, separator: str) -> str:
    if not current:
        return token
    return f"{current}{separator}{token}" if separator else f"{current}{token}"


def _wrap_tokens(
    tokens: list[str],
    separator: str,
    bbox: BoundingBox,
    measurer: TextMeasurer,
    *,
    font_size: int,
    line_height: int,
    max_lines: int,
    margin: int,
) -> tuple[list[str], bool]:
    lines: list[str] = []
    mutable_tokens = list(tokens)
    current = ""
    index = 0
    overflowed = False

    while index < len(mutable_tokens):
        if len(lines) >= max_lines:
            overflowed = True
            break

        line_center_y = bbox.y + margin + line_height * (len(lines) + 0.5)
        available_width = oval_width_at_y(bbox, line_center_y, margin=margin)
        token = mutable_tokens[index]
        candidate = _join(current, token, separator)
        candidate_width, _ = measurer.measure(candidate, font_size)

        if candidate_width <= available_width + 0.5:
            current = candidate
            index += 1
            continue

        if current:
            lines.append(current)
            current = ""
            continue

        piece, remainder = _split_token_to_fit(token, available_width, measurer, font_size)
        lines.append(piece)
        if remainder:
            mutable_tokens[index] = remainder
        else:
            index += 1

    if current:
        if len(lines) < max_lines:
            lines.append(current)
        else:
            overflowed = True

    return lines, overflowed


def _split_token_to_fit(
    token: str,
    available_width: float,
    measurer: TextMeasurer,
    font_size: int,
) -> tuple[str, str]:
    if not token:
        return "", ""

    best = token[0]
    for end in range(1, len(token) + 1):
        candidate = token[:end]
        width, _ = measurer.measure(candidate, font_size)
        if width <= available_width + 0.5:
            best = candidate
        else:
            break

    return best, token[len(best) :]
