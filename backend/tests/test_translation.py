from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from manga_workspace.models import BoundingBox, TextRegion, Tone
from manga_workspace.translation import has_translatable_text, translate_regions


class FakeTranslator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def translate(self, source_text: str, tone: Tone = Tone.CASUAL, *, max_words: int = 14) -> str:
        self.calls.append(source_text)
        return f"translated:{source_text}"


class FakeBatchTranslator(FakeTranslator):
    def __init__(self) -> None:
        super().__init__()
        self.batch_calls: list[list[str]] = []

    def translate_many(self, items: list[tuple[str, Tone]], *, max_words: int = 14) -> list[str]:
        source_texts = [source_text for source_text, _tone in items]
        self.batch_calls.append(source_texts)
        return [f"batch:{source_text}" for source_text in source_texts]


class TranslationTests(unittest.TestCase):
    def test_punctuation_only_ocr_is_not_translatable(self) -> None:
        self.assertFalse(has_translatable_text("．．．"))
        self.assertTrue(has_translatable_text("子供"))

    def test_translate_regions_fills_empty_translation_only(self) -> None:
        regions = [
            TextRegion(id="a", bbox=BoundingBox(0, 0, 10, 10), source_text="子供"),
            TextRegion(id="b", bbox=BoundingBox(0, 0, 10, 10), source_text="．．．"),
            TextRegion(id="c", bbox=BoundingBox(0, 0, 10, 10), source_text="村", translation="Village"),
        ]
        translator = FakeTranslator()

        translate_regions(regions, translator)  # type: ignore[arg-type]

        self.assertEqual(regions[0].translation, "translated:子供")
        self.assertEqual(regions[1].translation, "")
        self.assertEqual(regions[2].translation, "Village")
        self.assertEqual(translator.calls, ["子供"])

    def test_translate_regions_uses_batch_translator_when_available(self) -> None:
        regions = [
            TextRegion(id="a", bbox=BoundingBox(0, 0, 10, 10), source_text="子供"),
            TextRegion(id="b", bbox=BoundingBox(0, 0, 10, 10), source_text="村"),
        ]
        translator = FakeBatchTranslator()

        translate_regions(regions, translator)  # type: ignore[arg-type]

        self.assertEqual([region.translation for region in regions], ["batch:子供", "batch:村"])
        self.assertEqual(translator.batch_calls, [["子供", "村"]])
        self.assertEqual(translator.calls, [])


if __name__ == "__main__":
    unittest.main()
