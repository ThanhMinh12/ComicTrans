const MIN_IMAGE_WIDTH = 240;
const MIN_IMAGE_HEIGHT = 240;
const MIN_IMAGE_AREA = 120000;
const IMAGE_ID_ATTR = "data-comictrans-image-id";

let imageIdCounter = 1;
const overlays = new Map();
let repositionScheduled = false;

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "COMICTRANS_SCAN_IMAGES") {
    sendResponse({ images: scanImages() });
    return false;
  }

  if (message?.type === "COMICTRANS_APPLY_PREVIEW") {
    applyPreviewOverlay(message.imageId, message.previewUrl);
    sendResponse({ ok: true });
    return false;
  }

  if (message?.type === "COMICTRANS_CLEAR_OVERLAYS") {
    clearOverlays(message.imageId);
    sendResponse({ ok: true });
    return false;
  }

  if (message?.type === "COMICTRANS_REVEAL_IMAGE") {
    const image = imageById(message.imageId);
    image?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    sendResponse({ ok: Boolean(image) });
    return false;
  }

  if (message?.type === "COMICTRANS_EXPORT_IMAGE") {
    exportImage(message.imageId)
      .then((dataUrl) => sendResponse({ dataUrl }))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  return false;
});

window.addEventListener("scroll", scheduleOverlayReposition, { passive: true });
window.addEventListener("resize", scheduleOverlayReposition);

const observer = new MutationObserver(scheduleOverlayReposition);
observer.observe(document.documentElement, {
  childList: true,
  subtree: true
});

function scanImages() {
  return Array.from(document.images)
    .map((image) => imageDescriptor(image))
    .filter(Boolean)
    .sort((a, b) => a.top - b.top || a.left - b.left);
}

function imageDescriptor(image) {
  if (!(image instanceof HTMLImageElement)) return null;
  if (!image.currentSrc && !image.src) return null;

  const rect = image.getBoundingClientRect();
  const renderedWidth = Math.round(rect.width);
  const renderedHeight = Math.round(rect.height);
  const naturalWidth = image.naturalWidth || renderedWidth;
  const naturalHeight = image.naturalHeight || renderedHeight;

  if (renderedWidth <= 0 || renderedHeight <= 0) return null;
  if (naturalWidth < MIN_IMAGE_WIDTH || naturalHeight < MIN_IMAGE_HEIGHT) return null;
  if (naturalWidth * naturalHeight < MIN_IMAGE_AREA) return null;
  if (isHidden(image)) return null;

  const id = ensureImageId(image);
  return {
    id,
    src: image.currentSrc || image.src,
    alt: image.alt || "",
    naturalWidth,
    naturalHeight,
    renderedWidth,
    renderedHeight,
    top: Math.round(rect.top + window.scrollY),
    left: Math.round(rect.left + window.scrollX),
    visible: rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth
  };
}

function ensureImageId(image) {
  const existing = image.getAttribute(IMAGE_ID_ATTR);
  if (existing) return existing;

  const id = `ct-${Date.now().toString(36)}-${(imageIdCounter += 1).toString(36)}`;
  image.setAttribute(IMAGE_ID_ATTR, id);
  return id;
}

function imageById(imageId) {
  if (!imageId) return null;
  return document.querySelector(`img[${IMAGE_ID_ATTR}="${CSS.escape(imageId)}"]`);
}

function applyPreviewOverlay(imageId, previewUrl) {
  const image = imageById(imageId);
  if (!image || !previewUrl) return;

  let record = overlays.get(imageId);
  if (!record) {
    const overlay = document.createElement("div");
    overlay.className = "comictrans-preview-overlay";
    overlay.dataset.state = "loading";

    const previewImage = document.createElement("img");
    previewImage.alt = "";
    previewImage.addEventListener("load", () => {
      overlay.dataset.state = "ready";
    });
    overlay.append(previewImage);
    (document.body || document.documentElement).append(overlay);

    record = { image, overlay, previewImage };
    overlays.set(imageId, record);
  }

  record.previewImage.src = previewUrl;
  positionOverlay(record);
}

function clearOverlays(imageId) {
  if (imageId) {
    overlays.get(imageId)?.overlay.remove();
    overlays.delete(imageId);
    return;
  }

  for (const record of overlays.values()) {
    record.overlay.remove();
  }
  overlays.clear();
}

function scheduleOverlayReposition() {
  if (repositionScheduled) return;
  repositionScheduled = true;
  requestAnimationFrame(() => {
    repositionScheduled = false;
    for (const [imageId, record] of overlays) {
      if (!record.image.isConnected) {
        record.overlay.remove();
        overlays.delete(imageId);
        continue;
      }
      positionOverlay(record);
    }
  });
}

function positionOverlay(record) {
  const rect = record.image.getBoundingClientRect();
  const style = record.overlay.style;
  style.left = `${Math.round(rect.left + window.scrollX)}px`;
  style.top = `${Math.round(rect.top + window.scrollY)}px`;
  style.width = `${Math.max(1, Math.round(rect.width))}px`;
  style.height = `${Math.max(1, Math.round(rect.height))}px`;
  style.display = rect.width > 0 && rect.height > 0 ? "block" : "none";
}

async function exportImage(imageId) {
  const image = imageById(imageId);
  if (!image) throw new Error("Image is no longer available on the page.");
  if (!image.complete || !image.naturalWidth || !image.naturalHeight) {
    throw new Error("Image is not fully loaded yet.");
  }

  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;

  const context = canvas.getContext("2d");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob((value) => {
      if (value) resolve(value);
      else reject(new Error("Canvas export failed."));
    }, "image/png");
  });

  return blobToDataUrl(blob);
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("Could not read exported image."));
    reader.readAsDataURL(blob);
  });
}

function isHidden(element) {
  const style = window.getComputedStyle(element);
  return style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0;
}
