from __future__ import annotations

import os
from pathlib import Path
import gc

from .errors import MissingDependencyError


class MangaOcrReader:
    """Lazy manga-ocr adapter so the backend can boot without loading PyTorch."""

    def __init__(self) -> None:
        self._reader = None

    def read_image(self, image) -> str:
        if self._reader is None:
            try:
                from manga_ocr import MangaOcr
            except ModuleNotFoundError as exc:
                raise MissingDependencyError(
                    "manga-ocr",
                    ".venv/bin/pip install -r requirements-ocr.txt",
                ) from exc
            self._reader = MangaOcr(_model_path())
        return str(self._reader(image)).strip()

    def release(self) -> None:
        self._reader = None
        gc.collect()


def _model_path() -> str:
    configured = os.getenv("MANGA_OCR_MODEL")
    if configured:
        return configured

    cache_root = Path.home() / ".cache/huggingface/hub/models--kha-white--manga-ocr-base/snapshots"
    if cache_root.exists():
        for snapshot in sorted(cache_root.iterdir(), reverse=True):
            if (snapshot / "pytorch_model.bin").exists() and (snapshot / "preprocessor_config.json").exists():
                return str(snapshot)

    return "kha-white/manga-ocr-base"
