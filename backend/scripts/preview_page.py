#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from manga_workspace.models import BoundingBox, TextRegion, Tone
from manga_workspace.pipeline import MangaPipeline


def parse_bbox(raw: str) -> BoundingBox:
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be x,y,width,height")
    return BoundingBox(parts[0], parts[1], parts[2], parts[3])


def fallback_box(image_path: Path) -> BoundingBox:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pillow is required. Install backend requirements first.") from exc

    with Image.open(image_path) as image:
        width, height = image.size
    box_width = max(120, round(width * 0.52))
    box_height = max(80, round(height * 0.18))
    return BoundingBox(
        x=max(0, round((width - box_width) / 2)),
        y=max(0, round(height * 0.12)),
        width=min(width, box_width),
        height=min(height, box_height),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze a manga page, render sample translated text, and save a preview image."
    )
    parser.add_argument("input", type=Path, help="Source manga page image.")
    parser.add_argument("output", type=Path, help="Where to write the rendered preview image.")
    parser.add_argument("--text", default="I MADE IT FIT!", help="Translation text to render.")
    parser.add_argument("--tone", choices=[tone.value for tone in Tone], default=Tone.SHOUTING.value)
    parser.add_argument("--bbox", type=parse_bbox, help="Manual x,y,width,height box to render into.")
    parser.add_argument("--storage", type=Path, default=ROOT / "storage")
    args = parser.parse_args()

    pipeline = MangaPipeline(args.storage)
    result = pipeline.analyze_upload(
        args.input.name,
        args.input.read_bytes(),
        run_ocr=False,
        include_images=False,
    )

    regions = [TextRegion.from_mapping(item) for item in result["bubbles"]]
    if args.bbox:
        regions = [TextRegion(id="manual-001", bbox=args.bbox, confidence=1.0)]
    elif not regions:
        regions = [TextRegion(id="fallback-001", bbox=fallback_box(args.input), confidence=1.0)]

    for region in regions:
        region.translation = args.text
        region.tone = Tone(args.tone)

    render = pipeline.render_page(result["pageId"], regions)
    preview_path = pipeline.image_path(render["pageId"], "preview")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(preview_path, args.output)

    print(f"Page id: {result['pageId']}")
    print(f"Detected bubbles: {len(result['bubbles'])}")
    print(f"Rendered regions: {len(regions)}")
    print(f"Wrote preview: {args.output}")


if __name__ == "__main__":
    main()
