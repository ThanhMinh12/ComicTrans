from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .errors import MangaWorkspaceError, MissingDependencyError
from .models import TextRegion
from .pipeline import MangaPipeline
from .translation import AutoTranslator, HuggingFaceJapaneseEnglishTranslator, OllamaTranslator, translate_regions


DEFAULT_STORAGE = Path(__file__).resolve().parents[2] / "storage"


class RenderRequest(BaseModel):
    page_id: str = Field(alias="pageId")
    bubbles: list[dict]
    base_image: str = Field(default="cleaned", alias="baseImage")
    replace_background: bool = Field(default=False, alias="replaceBackground")


class TranslateRequest(BaseModel):
    page_id: str | None = Field(default=None, alias="pageId")
    bubbles: list[dict]
    engine: str = "auto"
    model: str = "llama3"
    max_words: int = Field(default=14, alias="maxWords")
    render: bool = False
    base_image: str = Field(default="cleaned", alias="baseImage")
    replace_background: bool = Field(default=False, alias="replaceBackground")


app = FastAPI(title="ComicTrans API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = MangaPipeline(Path(os.getenv("MANGA_WORKSPACE_STORAGE", DEFAULT_STORAGE)))
_translator_cache: dict[tuple[str, str], object] = {}
_translator_cache_lock = Lock()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/pages/analyze")
async def analyze_page(
    file: UploadFile = File(...),
    run_ocr: bool = Query(False, alias="runOcr"),
    include_images: bool = Query(True, alias="includeImages"),
    clean_image: bool = Query(True, alias="cleanImage"),
) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file was empty.")

    try:
        return pipeline.analyze_upload(
            file.filename or "page.png",
            content,
            run_ocr=run_ocr,
            include_images=include_images,
            clean_image=clean_image,
        )
    except MissingDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/pages/process")
async def process_page(
    file: UploadFile = File(...),
    run_ocr: bool = Query(True, alias="runOcr"),
    translate: bool = Query(True),
    translation_engine: str = Query("auto", alias="translationEngine"),
    model: str = Query("llama3"),
    max_words: int = Query(14, alias="maxWords"),
    include_images: bool = Query(False, alias="includeImages"),
    base_image: str = Query("cleaned", alias="baseImage"),
    replace_background: bool = Query(False, alias="replaceBackground"),
    clean_image: bool = Query(True, alias="cleanImage"),
) -> dict:
    if base_image not in {"original", "cleaned"}:
        raise HTTPException(status_code=400, detail="baseImage must be 'original' or 'cleaned'.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file was empty.")

    try:
        result = pipeline.analyze_upload(
            file.filename or "page.png",
            content,
            run_ocr=run_ocr,
            include_images=include_images,
            clean_image=clean_image,
        )
        regions = [TextRegion.from_mapping(item) for item in result["bubbles"]]
        if translate:
            translator = _translator(translation_engine, model)
            regions = translate_regions(
                regions,
                translator,
                max_words=max_words,
            )

        result["bubbles"] = [region.to_dict() for region in regions]
        render_base_image = "original" if base_image == "cleaned" and not clean_image else base_image
        render = pipeline.render_page(
            result["pageId"],
            regions,
            base_image=render_base_image,
            replace_background=replace_background or render_base_image == "original",
        )
        result["previewUrl"] = render["previewUrl"]
        if include_images:
            result["preview"] = render["preview"]
        return result
    except MissingDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MangaWorkspaceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Local translation failed. Is Ollama running with model '{model}'? {exc}",
        ) from exc


@app.get("/pages/{page_id}/images/{kind}")
def get_page_image(page_id: str, kind: str) -> FileResponse:
    try:
        return FileResponse(pipeline.image_path(page_id, kind))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MangaWorkspaceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/pages/translate")
def translate_page(request: TranslateRequest) -> dict:
    try:
        regions = [TextRegion.from_mapping(item) for item in request.bubbles]
        translator = _translator(request.engine, request.model)
        regions = translate_regions(
            regions,
            translator,
            max_words=request.max_words,
        )
        response = {
            "pageId": request.page_id,
            "bubbles": [region.to_dict() for region in regions],
        }
        if request.render:
            if not request.page_id:
                raise HTTPException(status_code=400, detail="pageId is required when render is true.")
            if request.base_image not in {"original", "cleaned"}:
                raise HTTPException(status_code=400, detail="baseImage must be 'original' or 'cleaned'.")
            render = pipeline.render_page(
                request.page_id,
                regions,
                base_image=request.base_image,
                replace_background=request.replace_background,
            )
            response["previewUrl"] = render["previewUrl"]
        return response
    except MissingDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Local translation failed. Is Ollama running with model '{request.model}'? {exc}",
        ) from exc


@app.post("/pages/render")
def render_page(request: RenderRequest) -> dict:
    try:
        regions = [TextRegion.from_mapping(item) for item in request.bubbles]
        if request.base_image not in {"original", "cleaned"}:
            raise HTTPException(status_code=400, detail="baseImage must be 'original' or 'cleaned'.")
        return pipeline.render_page(
            request.page_id,
            regions,
            base_image=request.base_image,
            replace_background=request.replace_background,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _translator(engine: str, model: str):
    key = (engine, model)
    with _translator_cache_lock:
        cached = _translator_cache.get(key)
        if cached is not None:
            return cached

        if engine == "ollama":
            translator = OllamaTranslator(model=model)
        elif engine == "huggingface":
            translator = HuggingFaceJapaneseEnglishTranslator()
        elif engine == "auto":
            translator = AutoTranslator(ollama_model=model)
        else:
            raise HTTPException(status_code=400, detail="engine must be 'auto', 'ollama', or 'huggingface'.")

        _translator_cache[key] = translator
        return translator


@app.on_event("shutdown")
def release_warm_models() -> None:
    pipeline.release()
    with _translator_cache_lock:
        translators = list(_translator_cache.values())
        _translator_cache.clear()
    for translator in translators:
        if hasattr(translator, "release"):
            translator.release()
