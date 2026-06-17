const DEFAULT_API_BASE = "http://127.0.0.1:8000";
const PROCESS_QUERY = "runOcr=true&translate=true&includeImages=false";

const apiBaseInput = document.querySelector("#apiBaseInput");
const pageLabel = document.querySelector("#pageLabel");
const refreshButton = document.querySelector("#refreshButton");
const healthButton = document.querySelector("#healthButton");
const clearButton = document.querySelector("#clearButton");
const processVisibleButton = document.querySelector("#processVisibleButton");
const imageList = document.querySelector("#imageList");
const statusText = document.querySelector("#statusText");
const progressBar = document.querySelector("#progressBar");

let activeTab = null;
let pageImages = [];
let processingImageId = "";
const processed = new Map();

init();

async function init() {
  const settings = await storageGet({ apiBase: DEFAULT_API_BASE });
  apiBaseInput.value = settings.apiBase || DEFAULT_API_BASE;
  setStatus("Ready.");

  apiBaseInput.addEventListener("change", saveSettings);
  apiBaseInput.addEventListener("blur", saveSettings);
  refreshButton.addEventListener("click", refreshImages);
  healthButton.addEventListener("click", checkBackend);
  clearButton.addEventListener("click", clearOverlays);
  processVisibleButton.addEventListener("click", processVisibleImages);

  chrome.tabs.onActivated.addListener(refreshImages);
  chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
    if (changeInfo.status === "complete") refreshImages();
  });

  await refreshImages();
}

async function saveSettings() {
  const apiBase = normalizedApiBase();
  apiBaseInput.value = apiBase;
  await storageSet({ apiBase });
}

async function refreshImages() {
  setBusy(true);
  setStatus("Scanning page images...");

  try {
    activeTab = await getActiveTab();
    pageLabel.textContent = activeTab?.url ? new URL(activeTab.url).hostname : "No page connected";

    if (!activeTab?.id || !canUseContentScript(activeTab.url)) {
      pageImages = [];
      renderImages();
      setStatus("Open a normal http or https manga page.");
      return;
    }

    const response = await sendTabMessage(activeTab.id, { type: "COMICTRANS_SCAN_IMAGES" });
    pageImages = response?.images ?? [];
    renderImages();
    setStatus(pageImages.length ? `Found ${pageImages.length} candidate image${pageImages.length === 1 ? "" : "s"}.` : "No large page images found.");
  } catch (error) {
    pageImages = [];
    renderImages();
    setStatus(formatError(error));
  } finally {
    setBusy(false);
  }
}

async function checkBackend() {
  setBusy(true);
  setStatus("Checking backend...");

  try {
    const response = await fetch(`${normalizedApiBase()}/health`);
    if (!response.ok) throw new Error(await response.text());
    setStatus("Backend is reachable.");
  } catch (error) {
    setStatus(`Backend check failed: ${formatError(error)}`);
  } finally {
    setBusy(false);
  }
}

async function clearOverlays() {
  if (!activeTab?.id) return;
  await sendTabMessage(activeTab.id, { type: "COMICTRANS_CLEAR_OVERLAYS" });
  processed.clear();
  renderImages();
  setStatus("Cleared translated overlays.");
}

async function processVisibleImages() {
  const visible = pageImages.filter((image) => image.visible);
  const targets = visible.length ? visible : pageImages.slice(0, 1);

  for (let index = 0; index < targets.length; index += 1) {
    setProgress(index, targets.length);
    await processImage(targets[index]);
  }

  setProgress(0, 0);
}

async function processImage(image) {
  if (!image || !activeTab?.id) return;

  processingImageId = image.id;
  renderImages();
  setBusy(true);
  setStatus(`Fetching ${image.naturalWidth}x${image.naturalHeight} image...`);

  try {
    await sendTabMessage(activeTab.id, { type: "COMICTRANS_REVEAL_IMAGE", imageId: image.id });
    const blob = await fetchImageBlob(image);
    setStatus("Running OCR, translation, inpainting, and render...");

    const formData = new FormData();
    formData.append("file", blob, filenameForImage(image.src, blob.type));

    const response = await fetch(`${normalizedApiBase()}/pages/process?${PROCESS_QUERY}`, {
      method: "POST",
      body: formData
    });
    if (!response.ok) throw new Error(await response.text());

    const data = await response.json();
    const previewUrl = absoluteBackendUrl(data.previewUrl);
    await sendTabMessage(activeTab.id, {
      type: "COMICTRANS_APPLY_PREVIEW",
      imageId: image.id,
      previewUrl
    });

    processed.set(image.id, {
      pageId: data.pageId,
      previewUrl,
      bubbles: data.bubbles?.length ?? 0
    });
    setStatus(`Applied translated preview with ${data.bubbles?.length ?? 0} bubble${data.bubbles?.length === 1 ? "" : "s"}.`);
  } catch (error) {
    setStatus(formatError(error));
  } finally {
    processingImageId = "";
    setBusy(false);
    renderImages();
  }
}

async function fetchImageBlob(image) {
  try {
    const response = await fetch(image.src, {
      credentials: "include",
      cache: "force-cache"
    });
    if (!response.ok) throw new Error(`Image fetch failed: ${response.status} ${response.statusText}`);

    const blob = await response.blob();
    if (!blob.type.startsWith("image/")) {
      throw new Error(`Fetched resource is ${blob.type || "not an image"}.`);
    }
    return blob;
  } catch (fetchError) {
    const exported = await sendTabMessage(activeTab.id, {
      type: "COMICTRANS_EXPORT_IMAGE",
      imageId: image.id
    });
    if (exported?.dataUrl) {
      return dataUrlToBlob(exported.dataUrl);
    }
    throw new Error(`${formatError(fetchError)} Canvas fallback failed: ${exported?.error || "unknown error"}.`);
  }
}

function renderImages() {
  imageList.textContent = "";

  if (!pageImages.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No candidate images yet.";
    imageList.append(empty);
    return;
  }

  for (const image of pageImages) {
    const result = processed.get(image.id);
    const card = document.createElement("article");
    card.className = `image-card${image.id === processingImageId ? " active" : ""}`;

    const preview = document.createElement("img");
    preview.className = "image-preview";
    preview.src = result?.previewUrl || image.src;
    preview.alt = image.alt || "";
    preview.loading = "lazy";

    const meta = document.createElement("div");
    meta.className = "image-meta";
    meta.append(textElement("strong", `${image.naturalWidth} x ${image.naturalHeight}`));
    meta.append(textElement("span", image.visible ? "visible" : "offscreen"));

    const actions = document.createElement("div");
    actions.className = "card-actions";

    const revealButton = document.createElement("button");
    revealButton.type = "button";
    revealButton.textContent = "Find";
    revealButton.addEventListener("click", () => {
      if (activeTab?.id) sendTabMessage(activeTab.id, { type: "COMICTRANS_REVEAL_IMAGE", imageId: image.id });
    });

    const processButton = document.createElement("button");
    processButton.type = "button";
    processButton.className = "primary-button";
    processButton.textContent = result ? "Redo" : "Translate";
    processButton.disabled = Boolean(processingImageId);
    processButton.addEventListener("click", () => processImage(image));

    actions.append(revealButton, processButton);
    card.append(preview, meta, actions);

    if (result) {
      const resultMeta = document.createElement("div");
      resultMeta.className = "image-meta";
      resultMeta.append(textElement("span", `${result.bubbles} bubble${result.bubbles === 1 ? "" : "s"}`));
      resultMeta.append(textElement("span", result.pageId.slice(0, 8)));
      card.append(resultMeta);
    }

    imageList.append(card);
  }
}

function normalizedApiBase() {
  return (apiBaseInput.value || DEFAULT_API_BASE).replace(/\/+$/, "");
}

function absoluteBackendUrl(pathOrUrl) {
  return new URL(pathOrUrl, `${normalizedApiBase()}/`).href;
}

function filenameForImage(src, contentType) {
  const extensionByType = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif"
  };

  try {
    const url = new URL(src);
    const name = url.pathname.split("/").filter(Boolean).pop();
    if (name && /\.[a-z0-9]{2,5}$/i.test(name)) return name;
  } catch (_error) {
    // Fall back to content type below.
  }

  return `manga-page${extensionByType[contentType] || ".png"}`;
}

function dataUrlToBlob(dataUrl) {
  const [header, payload] = dataUrl.split(",", 2);
  const match = /^data:([^;]+);base64$/i.exec(header);
  if (!match || !payload) throw new Error("Invalid exported image data.");

  const binary = atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Blob([bytes], { type: match[1] });
}

function textElement(tagName, text) {
  const element = document.createElement(tagName);
  element.textContent = text;
  return element;
}

function setBusy(busy) {
  refreshButton.disabled = busy;
  healthButton.disabled = busy;
  clearButton.disabled = busy;
  processVisibleButton.disabled = busy || !pageImages.length;
}

function setStatus(message) {
  statusText.textContent = message;
}

function setProgress(done, total) {
  if (!total) {
    progressBar.hidden = true;
    progressBar.value = 0;
    return;
  }

  progressBar.hidden = false;
  progressBar.value = Math.round((done / total) * 100);
}

function formatError(error) {
  if (!error) return "Unknown error.";
  return error.message || String(error);
}

function canUseContentScript(url) {
  return /^https?:\/\//i.test(url || "");
}

function getActiveTab() {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const error = chrome.runtime.lastError;
      if (error) reject(error);
      else resolve(tabs[0] || null);
    });
  });
}

function sendTabMessage(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) reject(error);
      else resolve(response);
    });
  });
}

function storageGet(defaults) {
  return new Promise((resolve) => {
    chrome.storage.local.get(defaults, resolve);
  });
}

function storageSet(values) {
  return new Promise((resolve) => {
    chrome.storage.local.set(values, resolve);
  });
}
