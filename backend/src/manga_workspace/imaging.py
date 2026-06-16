from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from .errors import MissingDependencyError
from .models import BoundingBox


def image_to_data_url(path: str | Path) -> str:
    image_path = Path(path)
    content_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def crop_region(image_path: str | Path, bbox: BoundingBox):
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("pillow", "pip install pillow") from exc

    image = Image.open(image_path)
    return image.crop((bbox.x, bbox.y, bbox.right, bbox.bottom))


def inpaint_with_opencv(
    original_path: str | Path,
    mask_path: str | Path,
    output_path: str | Path,
    *,
    radius: int = 5,
    method: str = "telea",
    dilate_iterations: int = 0,
) -> Path:
    try:
        import cv2
        import numpy as np
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("opencv-python", "pip install opencv-python numpy") from exc

    original = cv2.imread(str(original_path), cv2.IMREAD_COLOR)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if original is None:
        raise ValueError(f"Could not read image: {original_path}")
    if mask is None:
        raise ValueError(f"Could not read mask: {mask_path}")

    if dilate_iterations > 0:
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=dilate_iterations)

    algorithm = cv2.INPAINT_TELEA if method.lower() == "telea" else cv2.INPAINT_NS
    cleaned = cv2.inpaint(original, mask, radius, algorithm)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), cleaned)
    return output


def clean_with_local_fill(
    original_path: str | Path,
    mask_path: str | Path,
    output_path: str | Path,
    *,
    ring_padding: int = 4,
) -> Path:
    try:
        import cv2
        import numpy as np
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("opencv-python", "pip install opencv-python numpy") from exc

    original = cv2.imread(str(original_path), cv2.IMREAD_COLOR)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if original is None:
        raise ValueError(f"Could not read image: {original_path}")
    if mask is None:
        raise ValueError(f"Could not read mask: {mask_path}")

    _, mask = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)
    cleaned = original.copy()
    height, width = mask.shape[:2]
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        x1 = max(0, x - ring_padding)
        y1 = max(0, y - ring_padding)
        x2 = min(width, x + box_width + ring_padding)
        y2 = min(height, y + box_height + ring_padding)

        inside_pixels = original[y:y + box_height, x:x + box_width].reshape(-1, 3)
        inside_fill = np.median(inside_pixels, axis=0).astype(np.uint8)

        ring = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
        ring[:, :] = 255
        ring[
            y - y1 : y - y1 + box_height,
            x - x1 : x - x1 + box_width,
        ] = 0
        local_mask = mask[y1:y2, x1:x2]
        sample_pixels = original[y1:y2, x1:x2][(ring > 0) & (local_mask == 0)]
        if sample_pixels.size == 0:
            sample_pixels = original[y1:y2, x1:x2][ring > 0]
        if _is_flat_background(inside_fill):
            fill = _snap_flat_color(inside_fill)
        elif sample_pixels.size == 0:
            fill = _snap_flat_color(inside_fill)
        else:
            fill = _snap_flat_color(np.median(sample_pixels, axis=0).astype(np.uint8))

        region_mask = mask[y:y + box_height, x:x + box_width] > 0
        cleaned_region = cleaned[y:y + box_height, x:x + box_width]
        cleaned_region[region_mask] = fill

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), cleaned)
    return output


def add_bright_text_on_dark_mask(
    original_path: str | Path,
    mask_path: str | Path,
    *,
    padding: int = 2,
) -> Path:
    try:
        import cv2
        import numpy as np
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("opencv-python", "pip install opencv-python numpy") from exc

    original = cv2.imread(str(original_path), cv2.IMREAD_GRAYSCALE)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if original is None:
        raise ValueError(f"Could not read image: {original_path}")
    if mask is None:
        raise ValueError(f"Could not read mask: {mask_path}")

    local_background = cv2.GaussianBlur(original, (21, 21), 0)
    candidates = ((original > 155) & (local_background < 115)).astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    candidates = cv2.morphologyEx(candidates, cv2.MORPH_CLOSE, kernel, iterations=1)
    line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 3))
    candidates = cv2.dilate(candidates, line_kernel, iterations=1)

    height, width = candidates.shape[:2]
    contours, _ = cv2.findContours(candidates, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if area < 4 or box_width < 3 or box_height < 3:
            continue
        if box_width > width * 0.82 or box_height > height * 0.20:
            continue
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(width, x + box_width + padding)
        y2 = min(height, y + box_height + padding)
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, thickness=-1)

    cv2.imwrite(str(mask_path), mask)
    return Path(mask_path)


def _is_flat_background(color) -> bool:
    brightness = int(color.mean())
    return brightness >= 150 or brightness <= 105


def _snap_flat_color(color):
    import numpy as np

    brightness = int(color.mean())
    if brightness >= 150:
        return np.array([255, 255, 255], dtype=np.uint8)
    if brightness <= 105:
        return np.array([0, 0, 0], dtype=np.uint8)
    return color


def expand_text_mask(
    mask_path: str | Path,
    *,
    regions=None,
    padding: int = 3,
    dilate_iterations: int = 3,
    close_iterations: int = 1,
) -> Path:
    try:
        import cv2
        import numpy as np
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("opencv-python", "pip install opencv-python numpy") from exc

    path = Path(mask_path)
    mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ValueError(f"Could not read mask: {mask_path}")

    _, mask = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)

    if regions:
        height, width = mask.shape[:2]
        for region in regions:
            box = region.bbox
            x1 = max(0, box.x - padding)
            y1 = max(0, box.y - padding)
            x2 = min(width, box.right + padding)
            y2 = min(height, box.bottom + padding)
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, thickness=-1)

    if close_iterations > 0:
        close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=close_iterations)

    if dilate_iterations > 0:
        dilate_kernel = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, dilate_kernel, iterations=dilate_iterations)

    cv2.imwrite(str(path), mask)
    return path
