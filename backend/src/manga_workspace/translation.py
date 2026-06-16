from __future__ import annotations

import json
import gc
import urllib.request
from typing import Protocol

from .models import TextRegion, Tone


TONE_GUIDES: dict[Tone, str] = {
    Tone.CASUAL: "Use natural casual English. Keep it punchy and readable in a manga bubble.",
    Tone.FORMAL: "Use polished, formal English without adding extra meaning.",
    Tone.NEUTRAL: "Use clear, neutral English. Preserve the speaker's intent.",
    Tone.SHOUTING: "Use forceful, high-impact English. Use capitalization only when it improves the line.",
    Tone.WHISPERING: "Use soft, understated English. Keep the line quiet and concise.",
}


def build_translation_prompt(source_text: str, tone: Tone, *, max_words: int = 14) -> str:
    tone_guide = TONE_GUIDES.get(tone, TONE_GUIDES[Tone.CASUAL])
    return (
        "You translate Japanese manga dialogue into English.\n"
        "Return only the translated line, no notes.\n"
        f"Tone: {tone.value}.\n"
        f"Style guide: {tone_guide}\n"
        f"Fit the result in at most {max_words} words when possible.\n"
        f"Japanese: {source_text}"
    )


class OllamaTranslator:
    def __init__(
        self,
        *,
        model: str = "llama3",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = 120,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def translate(self, source_text: str, tone: Tone = Tone.CASUAL, *, max_words: int = 14) -> str:
        prompt = build_translation_prompt(source_text, tone, max_words=max_words)
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.35},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str(data.get("response", "")).strip()


class RegionTranslator(Protocol):
    def translate(self, source_text: str, tone: Tone = Tone.CASUAL, *, max_words: int = 14) -> str:
        """Translate one OCR result."""


class HuggingFaceJapaneseEnglishTranslator:
    def __init__(self, *, model_name: str = "Helsinki-NLP/opus-mt-ja-en") -> None:
        self.model_name = model_name
        self._tokenizer = None
        self._model = None

    def translate(self, source_text: str, tone: Tone = Tone.CASUAL, *, max_words: int = 14) -> str:
        tokenizer, model = self._load()
        inputs = tokenizer([source_text], return_tensors="pt", truncation=True)
        outputs = model.generate(**inputs, max_new_tokens=max(12, max_words * 3))
        text = tokenizer.batch_decode(outputs, skip_special_tokens=True)[0].strip()
        if tone == Tone.SHOUTING:
            return text.upper()
        if tone == Tone.WHISPERING:
            return text.lower()
        return text

    def _load(self):
        if self._tokenizer is None or self._model is None:
            try:
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            except ModuleNotFoundError as exc:
                raise RuntimeError("Install transformers to use the Hugging Face translator") from exc
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            self._model.eval()
        return self._tokenizer, self._model

    def release(self) -> None:
        self._tokenizer = None
        self._model = None
        gc.collect()


class AutoTranslator:
    def __init__(
        self,
        *,
        ollama_model: str = "llama3",
        hf_model: str = "Helsinki-NLP/opus-mt-ja-en",
    ) -> None:
        self.ollama = OllamaTranslator(model=ollama_model, timeout_seconds=20)
        self.huggingface = HuggingFaceJapaneseEnglishTranslator(model_name=hf_model)
        self._prefer_huggingface = False

    def translate(self, source_text: str, tone: Tone = Tone.CASUAL, *, max_words: int = 14) -> str:
        if not self._prefer_huggingface:
            try:
                return self.ollama.translate(source_text, tone, max_words=max_words)
            except OSError:
                self._prefer_huggingface = True
        return self.huggingface.translate(source_text, tone, max_words=max_words)

    def release(self) -> None:
        self.huggingface.release()


def has_translatable_text(text: str) -> bool:
    """Return true when OCR output contains something more meaningful than punctuation."""
    for char in text.strip():
        if char.isalnum() or "\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff":
            return True
    return False


def translate_regions(
    regions: list[TextRegion],
    translator: RegionTranslator,
    *,
    max_words: int = 14,
) -> list[TextRegion]:
    for region in regions:
        if region.translation.strip():
            continue
        if not has_translatable_text(region.source_text):
            continue
        region.translation = translator.translate(
            region.source_text,
            region.tone,
            max_words=max_words,
        )
    return regions
