from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .detection import ComicTextDetector, OpenCVTextDetector, create_default_detector
from .imaging import add_bright_text_on_dark_mask, clean_with_local_fill, crop_region, expand_text_mask, image_to_data_url
from .models import TextRegion
from .ocr import MangaOcrReader
from .rendering import render_regions


class MangaPipeline:
    def __init__(
        self,
        storage_dir: str | Path,
        *,
        detector: ComicTextDetector | OpenCVTextDetector | None = None,
        ocr_reader: MangaOcrReader | None = None,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.detector = detector or create_default_detector()
        self.ocr_reader = ocr_reader or MangaOcrReader()

    def analyze_upload(
        self,
        filename: str,
        content: bytes,
        *,
        run_ocr: bool = False,
        include_images: bool = True,
    ) -> dict:
        page_id = uuid4().hex
        page_dir = self._page_dir(page_id)
        page_dir.mkdir(parents=True, exist_ok=True)

        suffix = Path(filename).suffix.lower() or ".png"
        original_path = page_dir / f"original{suffix}"
        original_path.write_bytes(content)

        mask_path = page_dir / "text-mask.png"
        cleaned_path = page_dir / "cleaned.png"
        detection = self.detector.detect(original_path, mask_path)
        expand_text_mask(detection.mask_path, regions=detection.regions)
        add_bright_text_on_dark_mask(original_path, detection.mask_path)
        clean_with_local_fill(original_path, detection.mask_path, cleaned_path)

        regions = detection.regions
        if run_ocr:
            regions = self._read_source_text(original_path, regions)

        response = {
            "pageId": page_id,
            "bubbles": [region.to_dict() for region in regions],
        }
        if include_images:
            response.update(
                {
                    "original": image_to_data_url(original_path),
                    "mask": image_to_data_url(mask_path),
                    "cleaned": image_to_data_url(cleaned_path),
                }
            )
        else:
            response["images"] = {
                "original": f"/pages/{page_id}/images/original",
                "mask": f"/pages/{page_id}/images/mask",
                "cleaned": f"/pages/{page_id}/images/cleaned",
            }
        return response

    def render_page(
        self,
        page_id: str,
        regions: list[TextRegion],
        *,
        base_image: str = "cleaned",
        replace_background: bool = False,
    ) -> dict:
        page_dir = self._page_dir(page_id)
        base_path = self.image_path(page_id, base_image)

        output_path = page_dir / "preview.png"
        render_regions(
            base_path,
            regions,
            output_path,
            replace_background=replace_background,
        )
        return {
            "pageId": page_id,
            "preview": image_to_data_url(output_path),
            "previewUrl": f"/pages/{page_id}/images/preview",
        }

    def image_path(self, page_id: str, kind: str) -> Path:
        page_dir = self._page_dir(page_id)
        if kind == "original":
            matches = sorted(page_dir.glob("original.*"))
            if matches:
                return matches[0]
        elif kind == "mask":
            path = page_dir / "text-mask.png"
            if path.exists():
                return path
        elif kind in {"cleaned", "preview"}:
            path = page_dir / f"{kind}.png"
            if path.exists():
                return path
        raise FileNotFoundError(f"Unknown image '{kind}' for page id: {page_id}")

    def release(self) -> None:
        if hasattr(self.detector, "release"):
            self.detector.release()
        if hasattr(self.ocr_reader, "release"):
            self.ocr_reader.release()

    def _read_source_text(self, original_path: Path, regions: list[TextRegion]) -> list[TextRegion]:
        updated: list[TextRegion] = []
        width, height = _image_size(original_path)
        for region in regions:
            ocr_box = region.bbox
            crop = crop_region(original_path, region.bbox)
            region.source_text = self.ocr_reader.read_image(crop)
            region.bbox = _expand_for_translation_layout(ocr_box, width, height)
            updated.append(region)
        return updated

    def _page_dir(self, page_id: str) -> Path:
        if not page_id.isalnum():
            raise FileNotFoundError(f"Unknown page id: {page_id}")
        return self.storage_dir / page_id


def _image_size(image_path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("pillow", "pip install pillow") from exc

    with Image.open(image_path) as image:
        return image.size


def _expand_for_translation_layout(box, image_width: int, image_height: int):
    from .models import BoundingBox

    pad_x = 16 if box.width >= 18 else 24
    pad_y = 8
    min_width = 54
    min_height = 36

    x = box.x - pad_x
    y = box.y - pad_y
    right = box.right + pad_x
    bottom = box.bottom + pad_y

    if right - x < min_width:
        extra = min_width - (right - x)
        x -= extra // 2
        right += extra - extra // 2
    if bottom - y < min_height:
        extra = min_height - (bottom - y)
        y -= extra // 2
        bottom += extra - extra // 2

    x = max(0, x)
    y = max(0, y)
    right = min(image_width, max(x + 1, right))
    bottom = min(image_height, max(y + 1, bottom))
    return BoundingBox(x=x, y=y, width=right - x, height=bottom - y)
