from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .errors import MissingDependencyError
from .layout import TextMeasurer, find_largest_font_layout
from .models import BoundingBox, TextRegion, Tone


class PillowTextMeasurer(TextMeasurer):
    def __init__(self, font_path: str | Path | None = None) -> None:
        self.font_path = Path(font_path) if font_path else None

    def measure(self, text: str, font_size: int) -> tuple[float, float]:
        font = self.load_font(font_size)
        bbox = font.getbbox(text or " ")
        return float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])

    def load_font(self, font_size: int):
        try:
            from PIL import ImageFont  # noqa: F401
        except ModuleNotFoundError as exc:
            raise MissingDependencyError("pillow", "pip install pillow") from exc

        if self.font_path:
            return _load_font(str(self.font_path), font_size)

        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ):
            if Path(candidate).exists():
                return _load_font(candidate, font_size)

        try:
            return _load_default_font(font_size)
        except TypeError:
            return _load_default_font(0)


@lru_cache(maxsize=128)
def _load_font(font_path: str, font_size: int):
    from PIL import ImageFont

    return ImageFont.truetype(font_path, font_size)


@lru_cache(maxsize=64)
def _load_default_font(font_size: int):
    from PIL import ImageFont

    if font_size > 0:
        return ImageFont.load_default(size=font_size)
    return ImageFont.load_default()


def render_regions(
    base_image_path: str | Path,
    regions: list[TextRegion],
    output_path: str | Path,
    *,
    font_path: str | Path | None = None,
    max_font_size: int = 46,
    margin: int = 10,
    replace_background: bool = False,
) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("pillow", "pip install pillow") from exc

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.open(base_image_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    measurer = PillowTextMeasurer(font_path)

    if replace_background:
        for region in regions:
            if _text_for_region(region):
                box = region.bbox
                draw.rectangle(
                    (box.x, box.y, box.right, box.bottom),
                    fill=(255, 255, 255, 255),
                    outline=(26, 26, 26, 255),
                    width=1,
                )

    for region in regions:
        text = _text_for_region(region)
        if not text:
            continue

        if replace_background:
            lines = _layout_text_in_rectangle(
                text,
                region.bbox,
                measurer,
                min_size=6,
                max_size=max_font_size,
                margin=margin,
            )
        else:
            layout = find_largest_font_layout(
                text,
                region.bbox,
                measurer,
                min_size=8,
                max_size=max_font_size,
                margin=margin,
            )
            lines = layout.lines

        for line in lines:
            font = measurer.load_font(line.font_size)
            fill, stroke_fill, stroke_width = _style_for_tone(region.tone, line.font_size)
            draw.text(
                (round(line.x), round(line.y)),
                line.text,
                font=font,
                fill=fill,
                stroke_fill=stroke_fill,
                stroke_width=stroke_width,
            )

    image.convert("RGB").save(output)
    return output


def _layout_text_in_rectangle(
    text: str,
    bbox: BoundingBox,
    measurer: PillowTextMeasurer,
    *,
    min_size: int,
    max_size: int,
    margin: int,
):
    from .layout import TextLine

    available_width = max(1, bbox.width - margin * 2)
    available_height = max(1, bbox.height - margin * 2)

    for font_size in range(max_size, min_size - 1, -1):
        line_height = max(1, int(measurer.measure("Ag", font_size)[1] * 1.18))
        raw_lines = _wrap_for_width(text, available_width, measurer, font_size)
        total_height = len(raw_lines) * line_height
        widest = max((measurer.measure(line, font_size)[0] for line in raw_lines), default=0)
        if total_height <= available_height and widest <= available_width:
            return _position_rect_lines(raw_lines, bbox, measurer, font_size, line_height)

    line_height = max(1, int(measurer.measure("Ag", min_size)[1] * 1.18))
    raw_lines = _wrap_for_width(text, available_width, measurer, min_size)
    max_lines = max(1, available_height // line_height)
    return _position_rect_lines(raw_lines[:max_lines], bbox, measurer, min_size, line_height)


def _wrap_for_width(
    text: str,
    available_width: float,
    measurer: PillowTextMeasurer,
    font_size: int,
) -> list[str]:
    tokens = text.split()
    separator = " "
    if not tokens:
        tokens = list(text)
        separator = ""

    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = token if not current else f"{current}{separator}{token}"
        width, _ = measurer.measure(candidate, font_size)
        if width <= available_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        token_width, _ = measurer.measure(token, font_size)
        if token_width <= available_width:
            current = token
        else:
            pieces = _split_long_token(token, available_width, measurer, font_size)
            lines.extend(pieces[:-1])
            current = pieces[-1] if pieces else ""
    if current:
        lines.append(current)
    return lines or [text]


def _split_long_token(
    token: str,
    available_width: float,
    measurer: PillowTextMeasurer,
    font_size: int,
) -> list[str]:
    pieces: list[str] = []
    current = ""
    for char in token:
        candidate = f"{current}{char}"
        width, _ = measurer.measure(candidate, font_size)
        if width <= available_width or not current:
            current = candidate
        else:
            pieces.append(current)
            current = char
    if current:
        pieces.append(current)
    return pieces


def _position_rect_lines(
    raw_lines: list[str],
    bbox: BoundingBox,
    measurer: PillowTextMeasurer,
    font_size: int,
    line_height: int,
):
    from .layout import TextLine

    total_height = len(raw_lines) * line_height
    y = bbox.y + max(2, (bbox.height - total_height) / 2)
    positioned: list[TextLine] = []
    for line in raw_lines:
        width, height = measurer.measure(line, font_size)
        positioned.append(
            TextLine(
                text=line,
                x=bbox.x + (bbox.width - width) / 2,
                y=y,
                width=width,
                height=height,
                font_size=font_size,
            )
        )
        y += line_height
    return positioned


def _text_for_region(region: TextRegion) -> str:
    text = (region.translation or region.source_text).strip()
    if region.tone == Tone.SHOUTING:
        return text.upper()
    if region.tone == Tone.WHISPERING:
        return text.lower()
    return text


def _style_for_tone(tone: Tone, font_size: int) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], int]:
    if tone == Tone.WHISPERING:
        return (54, 61, 73, 220), (255, 255, 255, 180), max(1, font_size // 22)
    if tone == Tone.SHOUTING:
        return (8, 10, 13, 255), (255, 255, 255, 255), max(2, font_size // 10)
    return (16, 18, 22, 255), (255, 255, 255, 230), max(1, font_size // 16)
