import { useEffect, useMemo, useRef, useState } from "react";
import { Download, RefreshCcw, Upload } from "lucide-react";

const DEFAULT_API_BASE = "http://127.0.0.1:8000";
const TONES = ["casual", "formal", "neutral", "shouting", "whispering"];

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [pageId, setPageId] = useState("");
  const [imageSrc, setImageSrc] = useState("");
  const [cleanedSrc, setCleanedSrc] = useState("");
  const [previewSrc, setPreviewSrc] = useState("");
  const [bubbles, setBubbles] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [draftBox, setDraftBox] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const pageImage = useLoadedImage(imageSrc);
  const previewImage = useLoadedImage(previewSrc || cleanedSrc);
  const canvasRef = useRef(null);
  const previewCanvasRef = useRef(null);
  const canvasMetricsRef = useRef(null);
  const dragRef = useRef(null);

  const selectedBubble = useMemo(
    () => bubbles.find((bubble) => bubble.id === selectedId),
    [bubbles, selectedId]
  );

  useEffect(() => {
    const draw = () => {
      canvasMetricsRef.current = drawWorkspaceCanvas(
        canvasRef.current,
        pageImage,
        bubbles,
        selectedId,
        draftBox
      );
      drawPreviewCanvas(previewCanvasRef.current, previewImage);
    };

    draw();
    const resizeObserver = new ResizeObserver(draw);
    if (canvasRef.current?.parentElement) resizeObserver.observe(canvasRef.current.parentElement);
    if (previewCanvasRef.current?.parentElement) resizeObserver.observe(previewCanvasRef.current.parentElement);
    return () => resizeObserver.disconnect();
  }, [pageImage, previewImage, bubbles, selectedId, draftBox]);

  useEffect(() => {
    if (!pageId || !cleanedSrc) return;

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(`${apiBase}/pages/render`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pageId, bubbles }),
          signal: controller.signal
        });
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const data = await response.json();
        setPreviewSrc(data.preview);
      } catch (renderError) {
        if (renderError.name !== "AbortError") {
          setError(renderError.message);
        }
      }
    }, 350);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [apiBase, pageId, cleanedSrc, bubbles]);

  async function analyzeFile(file) {
    if (!file) return;
    setBusy(true);
    setError("");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${apiBase}/pages/analyze?runOcr=false`, {
        method: "POST",
        body: formData
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const data = await response.json();
      setPageId(data.pageId);
      setImageSrc(data.original);
      setCleanedSrc(data.cleaned);
      setPreviewSrc(data.cleaned);
      setBubbles(data.bubbles ?? []);
      setSelectedId(data.bubbles?.[0]?.id ?? "");
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setBusy(false);
    }
  }

  function updateBubble(id, patch) {
    setBubbles((current) =>
      current.map((bubble) => (bubble.id === id ? { ...bubble, ...patch } : bubble))
    );
  }

  function handlePointerDown(event) {
    if (!pageImage || !canvasMetricsRef.current) return;
    const point = eventToImagePoint(event, canvasRef.current, canvasMetricsRef.current);
    if (!point) return;

    if (event.shiftKey) {
      event.currentTarget.setPointerCapture(event.pointerId);
      dragRef.current = { start: point, pointerId: event.pointerId };
      setDraftBox(bboxFromPoints(point, point, pageImage));
      return;
    }

    const hit = findBubbleAtPoint(bubbles, point);
    setSelectedId(hit?.id ?? "");
  }

  function handlePointerMove(event) {
    const drag = dragRef.current;
    if (!drag || !pageImage || !canvasMetricsRef.current) return;
    const point = eventToImagePoint(event, canvasRef.current, canvasMetricsRef.current);
    if (!point) return;
    setDraftBox(bboxFromPoints(drag.start, point, pageImage));
  }

  function handlePointerUp(event) {
    const drag = dragRef.current;
    if (!drag || !draftBox) return;
    event.currentTarget.releasePointerCapture(drag.pointerId);

    if (draftBox.width >= 12 && draftBox.height >= 12) {
      const bubble = {
        id: `manual-${String(bubbles.length + 1).padStart(3, "0")}`,
        bbox: draftBox,
        confidence: 1,
        sourceText: "",
        translation: "",
        tone: "casual"
      };
      setBubbles((current) => [...current, bubble]);
      setSelectedId(bubble.id);
    }

    dragRef.current = null;
    setDraftBox(null);
  }

  function resetPreview() {
    setPreviewSrc(cleanedSrc);
  }

  function downloadPreview() {
    if (!previewSrc) return;
    const link = document.createElement("a");
    link.href = previewSrc;
    link.download = `${pageId || "comictrans-page"}-preview.png`;
    link.click();
  }

  return (
    <main className="app-shell">
      <section className="pane canvas-pane">
        <header className="toolbar">
          <label className="command-button" title="Upload page">
            <Upload size={18} aria-hidden="true" />
            <span>Upload</span>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => analyzeFile(event.target.files?.[0])}
            />
          </label>
          <input
            className="api-input"
            value={apiBase}
            onChange={(event) => setApiBase(event.target.value)}
            aria-label="API base URL"
          />
          <span className="status-chip">{busy ? "Analyzing" : `${bubbles.length} bubbles`}</span>
        </header>
        <div className="canvas-surface">
          <canvas
            ref={canvasRef}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            title="Shift-drag to add a bubble"
          />
          {!imageSrc && <p className="empty-state">No page loaded</p>}
        </div>
      </section>

      <section className="pane text-pane">
        <header className="toolbar">
          <h1>Dialogue</h1>
          <span className="status-chip selected">{selectedBubble?.id ?? "None"}</span>
        </header>
        <div className="bubble-list">
          {bubbles.map((bubble) => (
            <article
              className={`text-card ${bubble.id === selectedId ? "active" : ""}`}
              key={bubble.id}
              onClick={() => setSelectedId(bubble.id)}
            >
              <div className="card-row">
                <strong>{bubble.id}</strong>
                <span>{Math.round((bubble.confidence ?? 0) * 100)}%</span>
              </div>
              <label>
                <span>Source</span>
                <textarea
                  value={bubble.sourceText ?? ""}
                  onChange={(event) => updateBubble(bubble.id, { sourceText: event.target.value })}
                  rows={2}
                />
              </label>
              <label>
                <span>Tone</span>
                <select
                  value={bubble.tone ?? "casual"}
                  onChange={(event) => updateBubble(bubble.id, { tone: event.target.value })}
                >
                  {TONES.map((tone) => (
                    <option key={tone} value={tone}>
                      {tone}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Translation</span>
                <textarea
                  value={bubble.translation ?? ""}
                  onChange={(event) => updateBubble(bubble.id, { translation: event.target.value })}
                  rows={3}
                />
              </label>
            </article>
          ))}
        </div>
      </section>

      <section className="pane preview-pane">
        <header className="toolbar">
          <h2>Preview</h2>
          <button className="icon-button" onClick={resetPreview} title="Reset preview" type="button">
            <RefreshCcw size={18} aria-hidden="true" />
          </button>
          <button className="icon-button" onClick={downloadPreview} title="Download preview" type="button">
            <Download size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="canvas-surface">
          <canvas ref={previewCanvasRef} />
          {!previewSrc && <p className="empty-state">Preview</p>}
        </div>
        {error && <pre className="error-box">{error}</pre>}
      </section>
    </main>
  );
}

function useLoadedImage(src) {
  const [image, setImage] = useState(null);

  useEffect(() => {
    if (!src) {
      setImage(null);
      return;
    }
    const imageElement = new Image();
    imageElement.onload = () => setImage(imageElement);
    imageElement.onerror = () => setImage(null);
    imageElement.src = src;
  }, [src]);

  return image;
}

function drawWorkspaceCanvas(canvas, image, bubbles, selectedId, draftBox) {
  const metrics = drawBaseImage(canvas, image);
  if (!canvas || !image || !metrics) return metrics;

  const context = canvas.getContext("2d");
  bubbles.forEach((bubble) => drawBubble(context, metrics, bubble, bubble.id === selectedId));
  if (draftBox) {
    drawBubble(context, metrics, { bbox: draftBox }, true, true);
  }
  return metrics;
}

function drawPreviewCanvas(canvas, image) {
  drawBaseImage(canvas, image);
}

function drawBaseImage(canvas, image) {
  if (!canvas) return null;

  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));

  const context = canvas.getContext("2d");
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  context.clearRect(0, 0, rect.width, rect.height);
  context.fillStyle = "#e8ecef";
  context.fillRect(0, 0, rect.width, rect.height);

  if (!image) return null;

  const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
  const drawWidth = image.naturalWidth * scale;
  const drawHeight = image.naturalHeight * scale;
  const offsetX = (rect.width - drawWidth) / 2;
  const offsetY = (rect.height - drawHeight) / 2;
  context.drawImage(image, offsetX, offsetY, drawWidth, drawHeight);

  return { scale, offsetX, offsetY, width: image.naturalWidth, height: image.naturalHeight };
}

function drawBubble(context, metrics, bubble, selected, dashed = false) {
  const box = bubble.bbox;
  const x = metrics.offsetX + box.x * metrics.scale;
  const y = metrics.offsetY + box.y * metrics.scale;
  const width = box.width * metrics.scale;
  const height = box.height * metrics.scale;

  context.save();
  context.lineWidth = selected ? 2.5 : 1.5;
  context.strokeStyle = selected ? "#c94d35" : "#147f82";
  context.fillStyle = selected ? "rgba(201, 77, 53, 0.12)" : "rgba(20, 127, 130, 0.10)";
  context.setLineDash(dashed ? [8, 6] : []);
  context.fillRect(x, y, width, height);
  context.strokeRect(x, y, width, height);
  context.restore();
}

function eventToImagePoint(event, canvas, metrics) {
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left - metrics.offsetX) / metrics.scale;
  const y = (event.clientY - rect.top - metrics.offsetY) / metrics.scale;
  if (x < 0 || y < 0 || x > metrics.width || y > metrics.height) return null;
  return { x, y };
}

function bboxFromPoints(start, end, image) {
  const left = Math.max(0, Math.min(start.x, end.x));
  const top = Math.max(0, Math.min(start.y, end.y));
  const right = Math.min(image.naturalWidth, Math.max(start.x, end.x));
  const bottom = Math.min(image.naturalHeight, Math.max(start.y, end.y));
  return {
    x: Math.round(left),
    y: Math.round(top),
    width: Math.round(right - left),
    height: Math.round(bottom - top)
  };
}

function findBubbleAtPoint(bubbles, point) {
  for (let index = bubbles.length - 1; index >= 0; index -= 1) {
    const bubble = bubbles[index];
    const box = bubble.bbox;
    if (
      point.x >= box.x &&
      point.x <= box.x + box.width &&
      point.y >= box.y &&
      point.y <= box.y + box.height
    ) {
      return bubble;
    }
  }
  return null;
}
