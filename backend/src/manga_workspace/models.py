from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class Tone(str, Enum):
    CASUAL = "casual"
    FORMAL = "formal"
    NEUTRAL = "neutral"
    SHOUTING = "shouting"
    WHISPERING = "whispering"


@dataclass(frozen=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    def inset(self, margin: int) -> "BoundingBox":
        margin = max(0, margin)
        return BoundingBox(
            self.x + margin,
            self.y + margin,
            max(1, self.width - margin * 2),
            max(1, self.height - margin * 2),
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "BoundingBox":
        return cls(
            x=int(value["x"]),
            y=int(value["y"]),
            width=max(1, int(value["width"])),
            height=max(1, int(value["height"])),
        )


@dataclass
class TextRegion:
    id: str
    bbox: BoundingBox
    confidence: float = 0.0
    source_text: str = ""
    translation: str = ""
    tone: Tone = Tone.CASUAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "sourceText": self.source_text,
            "translation": self.translation,
            "tone": self.tone.value,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TextRegion":
        tone_value = value.get("tone", Tone.CASUAL.value)
        try:
            tone = Tone(tone_value)
        except ValueError:
            tone = Tone.CASUAL

        return cls(
            id=str(value["id"]),
            bbox=BoundingBox.from_mapping(value["bbox"]),
            confidence=float(value.get("confidence", 0.0)),
            source_text=str(value.get("sourceText", value.get("source_text", ""))),
            translation=str(value.get("translation", "")),
            tone=tone,
        )
