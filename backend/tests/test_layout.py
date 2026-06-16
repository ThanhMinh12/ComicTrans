from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from manga_workspace.layout import find_largest_font_layout, layout_text_in_oval, oval_width_at_y
from manga_workspace.models import BoundingBox


class FakeMeasurer:
    def measure(self, text: str, font_size: int) -> tuple[float, float]:
        return max(1, len(text) * font_size * 0.52), font_size


class OvalLayoutTests(unittest.TestCase):
    def test_oval_width_is_largest_at_center(self) -> None:
        bbox = BoundingBox(0, 0, 200, 120)

        top_width = oval_width_at_y(bbox, 14, margin=10)
        center_width = oval_width_at_y(bbox, 60, margin=10)

        self.assertGreater(center_width, top_width)

    def test_binary_search_picks_largest_fitting_size(self) -> None:
        layout = find_largest_font_layout(
            "hello there",
            BoundingBox(0, 0, 180, 90),
            FakeMeasurer(),
            min_size=8,
            max_size=42,
        )

        too_large = layout_text_in_oval(
            "hello there",
            BoundingBox(0, 0, 180, 90),
            FakeMeasurer(),
            font_size=layout.font_size + 1,
        )

        self.assertTrue(layout.fits)
        self.assertFalse(too_large.fits)

    def test_long_text_wraps_to_multiple_lines_inside_oval(self) -> None:
        bbox = BoundingBox(10, 20, 260, 180)
        layout = find_largest_font_layout(
            "This speech bubble has enough words to exercise the oval wrapping algorithm",
            bbox,
            FakeMeasurer(),
            min_size=8,
            max_size=28,
        )

        self.assertTrue(layout.fits)
        self.assertGreater(len(layout.lines), 1)
        for line in layout.lines:
            available = oval_width_at_y(bbox, line.y + line.height / 2, margin=10)
            self.assertLessEqual(line.width, available + 1)

    def test_unspaced_text_can_wrap_character_by_character(self) -> None:
        layout = find_largest_font_layout(
            "supercalifragilistic",
            BoundingBox(0, 0, 180, 130),
            FakeMeasurer(),
            min_size=8,
            max_size=20,
        )

        self.assertTrue(layout.fits)
        self.assertGreater(len(layout.lines), 1)


if __name__ == "__main__":
    unittest.main()
