#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from manga_workspace.models import BoundingBox
from manga_workspace.ocr import MangaOcrReader


def parse_bbox(raw: str) -> BoundingBox:
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be x,y,width,height")
    return BoundingBox(parts[0], parts[1], parts[2], parts[3])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run manga-ocr on an image or cropped bubble.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--bbox", type=parse_bbox, help="Optional x,y,width,height crop before OCR.")
    args = parser.parse_args()

    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pillow is required. Install backend requirements first.") from exc

    image = Image.open(args.image).convert("RGB")
    if args.bbox:
        image = image.crop((args.bbox.x, args.bbox.y, args.bbox.right, args.bbox.bottom))

    text = MangaOcrReader().read_image(image)
    print(text)


if __name__ == "__main__":
    main()
