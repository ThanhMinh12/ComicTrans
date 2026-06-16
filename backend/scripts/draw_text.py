#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from manga_workspace.models import BoundingBox, TextRegion, Tone
from manga_workspace.rendering import render_regions


def parse_bbox(raw: str) -> BoundingBox:
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be x,y,width,height")
    return BoundingBox(parts[0], parts[1], parts[2], parts[3])


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw translated text into one manga bubble.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("text")
    parser.add_argument("--bbox", type=parse_bbox, default=BoundingBox(80, 80, 220, 140))
    parser.add_argument("--tone", choices=[tone.value for tone in Tone], default=Tone.CASUAL.value)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()

    region = TextRegion(
        id="manual-001",
        bbox=args.bbox,
        translation=args.text,
        tone=Tone(args.tone),
        confidence=1.0,
    )
    render_regions(args.input, [region], args.output, font_path=args.font)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
