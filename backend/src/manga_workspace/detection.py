from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import gc
import sys

from .errors import MissingDependencyError
from .models import BoundingBox, TextRegion


@dataclass(frozen=True)
class DetectionResult:
    regions: list[TextRegion]
    mask_path: Path


class OpenCVTextDetector:
    """A lightweight local fallback detector for early iteration.

    For production quality text stroke masks, swap this adapter for
    comic-text-detector while keeping the same DetectionResult contract.
    """

    def __init__(
        self,
        *,
        min_box_area: int = 80,
        max_page_fraction: float = 0.20,
        merge_padding: int = 18,
    ) -> None:
        self.min_box_area = min_box_area
        self.max_page_fraction = max_page_fraction
        self.merge_padding = merge_padding

    def detect(self, image_path: str | Path, mask_path: str | Path) -> DetectionResult:
        try:
            import cv2
            import numpy as np
        except ModuleNotFoundError as exc:
            raise MissingDependencyError("opencv-python", "pip install opencv-python numpy") from exc

        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"Could not read image: {image_path}")

        height, width = image.shape[:2]
        _, ink = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
        grouped = cv2.dilate(ink, kernel, iterations=2)
        contours, _ = cv2.findContours(grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        boxes: list[BoundingBox] = []
        max_area = width * height * self.max_page_fraction
        for contour in contours:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            area = box_width * box_height
            if area < self.min_box_area or area > max_area:
                continue
            if box_width < 8 or box_height < 8:
                continue
            boxes.append(BoundingBox(x, y, box_width, box_height))

        merged = _merge_boxes(boxes, self.merge_padding)
        merged.sort(key=lambda box: (box.y, box.x))

        mask = np.zeros_like(ink)
        for box in merged:
            mask[box.y : box.bottom, box.x : box.right] = ink[box.y : box.bottom, box.x : box.right]

        output_mask = Path(mask_path)
        output_mask.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_mask), mask)

        page_area = max(1, width * height)
        regions = [
            TextRegion(
                id=f"r{index + 1:03d}",
                bbox=box,
                confidence=min(0.95, max(0.10, (box.width * box.height) / page_area * 12)),
            )
            for index, box in enumerate(merged)
        ]
        return DetectionResult(regions=regions, mask_path=output_mask)


class ComicTextDetector:
    """Adapter around dmMaze/comic-text-detector.

    The upstream package is vendored under backend/vendor/comic-text-detector and
    uses an ONNX model from manga-image-translator's release assets.
    """

    def __init__(
        self,
        *,
        model_path: str | Path,
        repo_path: str | Path,
        fallback: OpenCVTextDetector | None = None,
        refine_mode: int = 1,
        include_english: bool = True,
    ) -> None:
        self.model_path = Path(model_path)
        self.repo_path = Path(repo_path)
        self.fallback = fallback or OpenCVTextDetector()
        self.refine_mode = refine_mode
        self.include_english = include_english
        self._detector = None

    def detect(self, image_path: str | Path, mask_path: str | Path) -> DetectionResult:
        if not self.model_path.exists() or not self.repo_path.exists():
            return self.fallback.detect(image_path, mask_path)

        try:
            import cv2
            import numpy as np
        except ModuleNotFoundError as exc:
            raise MissingDependencyError("opencv-python", "pip install opencv-python numpy") from exc

        detector = self._load_detector()
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not read image: {image_path}")

        mask, refined_mask, blocks = detector(
            image,
            refine_mode=self.refine_mode,
            keep_undetected_mask=True,
        )

        output_mask = Path(mask_path)
        output_mask.parent.mkdir(parents=True, exist_ok=True)
        mask_to_write = refined_mask if refined_mask is not None else mask
        if mask_to_write.dtype != np.uint8:
            mask_to_write = (mask_to_write * 255).astype(np.uint8)
        cv2.imwrite(str(output_mask), mask_to_write)

        regions: list[TextRegion] = []
        height, width = image.shape[:2]
        for block in blocks:
            language = getattr(block, "language", "unknown")
            if language == "eng" and not self.include_english:
                continue
            box = _clip_box(_box_from_xyxy(block.xyxy), width, height)
            if box.width < 4 or box.height < 4:
                continue
            regions.append(
                TextRegion(
                    id=f"r{len(regions) + 1:03d}",
                    bbox=box,
                    confidence=float(getattr(block, "prob", 1.0) or 1.0),
                )
            )

        regions.sort(key=lambda region: (region.bbox.y, region.bbox.x))
        for index, region in enumerate(regions, 1):
            region.id = f"r{index:03d}"
        return DetectionResult(regions=regions, mask_path=output_mask)

    def _load_detector(self):
        if self._detector is None:
            if str(self.repo_path) not in sys.path:
                sys.path.insert(0, str(self.repo_path))
            try:
                from inference import TextDetector
            except ModuleNotFoundError as exc:
                raise MissingDependencyError(
                    "comic-text-detector",
                    "install backend/requirements-detector.txt and clone backend/vendor/comic-text-detector",
                ) from exc
            self._detector = TextDetector(str(self.model_path))
        return self._detector

    def release(self) -> None:
        self._detector = None
        gc.collect()


def create_default_detector() -> ComicTextDetector | OpenCVTextDetector:
    backend_root = Path(__file__).resolve().parents[2]
    model_path = backend_root / "models" / "comictextdetector.pt.onnx"
    repo_path = backend_root / "vendor" / "comic-text-detector"
    return ComicTextDetector(model_path=model_path, repo_path=repo_path)


def _box_from_xyxy(raw: list) -> BoundingBox:
    x1, y1, x2, y2 = [int(value) for value in raw]
    return BoundingBox(x=x1, y=y1, width=max(1, x2 - x1), height=max(1, y2 - y1))


def _clip_box(box: BoundingBox, image_width: int, image_height: int) -> BoundingBox:
    x = min(max(0, box.x), max(0, image_width - 1))
    y = min(max(0, box.y), max(0, image_height - 1))
    right = min(max(x + 1, box.right), image_width)
    bottom = min(max(y + 1, box.bottom), image_height)
    return BoundingBox(x=x, y=y, width=right - x, height=bottom - y)


def _merge_boxes(boxes: list[BoundingBox], padding: int) -> list[BoundingBox]:
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        next_boxes: list[BoundingBox] = []
        while merged:
            current = merged.pop()
            overlap_index = _find_overlapping_box(current, merged, padding)
            if overlap_index is None:
                next_boxes.append(current)
                continue
            other = merged.pop(overlap_index)
            merged.append(_union(current, other))
            changed = True
        merged = next_boxes
    return merged


def _find_overlapping_box(
    target: BoundingBox,
    boxes: list[BoundingBox],
    padding: int,
) -> int | None:
    for index, candidate in enumerate(boxes):
        if _overlaps(target, candidate, padding):
            return index
    return None


def _overlaps(a: BoundingBox, b: BoundingBox, padding: int) -> bool:
    return not (
        a.right + padding < b.x
        or b.right + padding < a.x
        or a.bottom + padding < b.y
        or b.bottom + padding < a.y
    )


def _union(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    x = min(a.x, b.x)
    y = min(a.y, b.y)
    right = max(a.right, b.right)
    bottom = max(a.bottom, b.bottom)
    return BoundingBox(x, y, right - x, bottom - y)
