from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from manga_workspace.detection import DetectionResult
from manga_workspace.models import BoundingBox, TextRegion
from manga_workspace.pipeline import MangaPipeline
import manga_workspace.api as api


class FakeDetector:
    def __init__(self) -> None:
        self.detect_calls = 0
        self.release_calls = 0

    def detect(self, image_path, mask_path) -> DetectionResult:
        self.detect_calls += 1
        Image.new("L", (64, 64), 0).save(mask_path)
        return DetectionResult(
            regions=[
                TextRegion(
                    id="r001",
                    bbox=BoundingBox(x=8, y=8, width=20, height=16),
                    confidence=0.95,
                )
            ],
            mask_path=Path(mask_path),
        )

    def release(self) -> None:
        self.release_calls += 1


class FakeOcrReader:
    def __init__(self) -> None:
        self.read_calls = 0
        self.release_calls = 0

    def read_image(self, image) -> str:
        self.read_calls += 1
        return "制御不可の状況"

    def release(self) -> None:
        self.release_calls += 1


class WarmModelTests(unittest.TestCase):
    def test_pipeline_keeps_detector_and_ocr_warm_between_pages(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.png"
            Image.new("RGB", (64, 64), "white").save(source)
            content = source.read_bytes()

            detector = FakeDetector()
            ocr_reader = FakeOcrReader()
            pipeline = MangaPipeline(temp_dir, detector=detector, ocr_reader=ocr_reader)

            pipeline.analyze_upload("page-1.png", content, run_ocr=True, include_images=False)
            pipeline.analyze_upload("page-2.png", content, run_ocr=True, include_images=False)

            self.assertEqual(detector.detect_calls, 2)
            self.assertEqual(ocr_reader.read_calls, 2)
            self.assertEqual(detector.release_calls, 0)
            self.assertEqual(ocr_reader.release_calls, 0)

            pipeline.release()

            self.assertEqual(detector.release_calls, 1)
            self.assertEqual(ocr_reader.release_calls, 1)

    def test_api_reuses_translator_for_same_engine_and_model(self) -> None:
        api._translator_cache.clear()

        first = api._translator("huggingface", "ignored-model-name")
        second = api._translator("huggingface", "ignored-model-name")
        different_model = api._translator("huggingface", "other-model-name")

        self.assertIs(first, second)
        self.assertIsNot(first, different_model)

        api._translator_cache.clear()


if __name__ == "__main__":
    unittest.main()
