/* PDF decompiler UI.
 *
 * Vanilla JS, no build step. The server owns all PDF logic; this file only
 * fetches JSON, draws it, and wires up view / download / copy for every
 * element it shows.
 *
 * Overlay geometry: every bounding box the API returns is in PDF points in
 * PyMuPDF space (origin top-left of page.rect). The rendered page covers
 * exactly page.rect, so a box maps to pixels as
 *     left = (x0 - rect.x0) * scale,  top = (y0 - rect.y1_origin) * scale
 * with scale = zoom. Raster resolution (dpi) is chosen independently, so the
 * overlay stays aligned at any zoom.
 */

const OVERLAY_KINDS = [
  { key: "block", label: "Text blocks", on: true },
  { key: "line", label: "Lines", on: false },
  { key: "span", label: "Spans", on: false },
  { key: "char", label: "Characters", on: false },
  { key: "image", label: "Images", on: true },
  { key: "drawing", label: "Drawings", on: false },
  { key: "annotation", label: "Annotations", on: true },
  { key: "link", label: "Links", on: true },
  { key: "widget", label: "Form fields", on: true },
];

const state = {
  documents: [],
  selected: null,
  docState: new Map(),
  polling: null,
};

const el = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ utils */

function api(path, options) {
  return fetch(path, options).then(async (response) => {
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = body.detail || detail;
      } catch (err) {
        /* response was not JSON */
      }
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return response;
  });
}

const apiJson = (path, options) => api(path, options).then((r) => r.json());

function toast(message, isError) {
  const node = el("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  node.style.borderColor = isError ? "var(--err)" : "var(--accent)";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.add("hidden"), 2600);
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`${label || "Content"} copied to clipboard`);
  } catch (err) {
    const dialog = el("copy-fallback");
    el("copy-fallback-text").value = text;
    dialog.showModal();
    el("copy-fallback-text").select();
  }
}

async function copyImage(url, label) {
  try {
    const blob = await fetch(url).then((r) => r.blob());
    if (!window.ClipboardItem || !navigator.clipboard.write) {
      throw new Error("unsupported");
    }
    let payload = blob;
    if (blob.type !== "image/png") {
      payload = await transcodeToPng(blob);
    }
    await navigator.clipboard.write([new ClipboardItem({ "image/png": payload })]);
    toast(`${label} copied to clipboard as PNG`);
  } catch (err) {
    toast("Browser blocked image copy — use Download instead", true);
  }
}

function transcodeToPng(blob) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      canvas.getContext("2d").drawImage(image, 0, 0);
      canvas.toBlob((out) => (out ? resolve(out) : reject(new Error("encode failed"))), "image/png");
    };
    image.onerror = () => reject(new Error("decode failed"));
    image.src = URL.createObjectURL(blob);
  });
}

function download(url) {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function downloadBlob(text, filename, mediaType) {
  const url = URL.createObjectURL(new Blob([text], { type: mediaType }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);

const pretty = (value) => JSON.stringify(value, null, 2);

function formatBytes(size) {
  if (size == null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
}

function roundList(values, digits = 2) {
  if (!Array.isArray(values)) return "—";
  return values.map((v) => (typeof v === "number" ? v.toFixed(digits) : v)).join(", ");
}

/* Buttons that give every rendered element view / copy / download. */
function actionBar(items) {
  return `<span class="actions">${items
    .map(
      (item) =>
        `<button class="button small" data-act="${item.act}" ${
          item.data || ""
        }>${escapeHtml(item.label)}</button>`
    )
    .join("")}</span>`;
}

/* ------------------------------------------------------------ image previews
 *
 * Extracted images keep the format the PDF used, which is what a download
 * should give but not always something a browser can draw: scanned files often
 * use JPEG 2000, JBIG2 or CCITT, and only Safari renders JPEG 2000 at all.
 * On-screen previews therefore come from the server's PNG re-encode
 * (`/images/{xref}/preview.png`), while downloads keep the original bytes.
 * Inline images have no xref to decode, so those still use the stored file.
 */

const BROWSER_IMAGE_FORMATS = new Set(["png", "jpeg", "jpg", "gif", "bmp", "webp", "avif"]);

const imagePreviewUrl = (xref, maxSide) =>
  `/api/documents/${state.selected}/images/${xref}/preview.png${
    maxSide ? `?max_side=${maxSide}` : ""
  }`;

const storedImageUrl = (file) =>
  `/api/documents/${state.selected}/images/${encodeURIComponent(file)}`;

/* Region render of one placement, used when an image has no bytes of its own:
   inline images, and images MuPDF cannot tie to an xref, still have a position
   on the page, so the page itself is rasterised inside that rectangle. */
function regionPreviewUrl(placement, pageIndex, maxSide) {
  const [x0, y0, x1, y1] = placement.bbox;
  const longestPoints = Math.max(x1 - x0, y1 - y0, 1);
  const dpi = Math.max(24, Math.min(400, Math.round((72 * (maxSide || 600)) / longestPoints)));
  const clip = [x0, y0, x1, y1].map((value) => value.toFixed(2)).join(",");
  return `/api/documents/${state.selected}/pages/${pageIndex}/render.png?dpi=${dpi}&clip=${clip}`;
}

/* Where a placement's preview pixels come from. */
function previewSource(placement) {
  if (placement.xref) return "stored";
  if (placement.file) return "file";
  return Array.isArray(placement.bbox) ? "region" : "none";
}

function placementPreviewUrl(placement, pageIndex, maxSide) {
  switch (previewSource(placement)) {
    case "stored":
      return imagePreviewUrl(placement.xref, maxSide);
    case "file":
      return storedImageUrl(placement.file);
    case "region":
      return regionPreviewUrl(placement, pageIndex, maxSide);
    default:
      return null;
  }
}

const PLACEMENT_LABEL = (placement) =>
  placement.xref
    ? `Image xref ${placement.xref}`
    : `Inline image ${placement.index ?? 0}`;

/* The format the bytes are stored in, from the page report's image objects. */
function storedImageFormat(page, placement) {
  if (!page || !placement || !placement.xref) return null;
  const object = (page.images.objects || []).find((item) => item.xref === placement.xref);
  return object ? object.ext || null : null;
}

/* One thumbnail. Clicking it opens the scalable viewer, which needs to know
   where to get bigger pixels from, hence the data attributes. */
/* Which pixels an image preview shows.
 *
 * A page is a composition: text and vector graphics are painted over images. A
 * map image, for example, can carry no place names at all because the names are
 * page text drawn on top of it. Showing only the stored bytes is correct but
 * surprising, so both views are offered:
 *   "stored" — the image's own pixels, i.e. exactly what a download contains;
 *   "page"   — that rectangle of the page, composited as the reader sees it.
 * Images with no bytes of their own can only ever be shown the second way. */
let imageViewMode = "stored";

/* Does this placement have its own bytes, so that both views are possible? */
const hasOwnPixels = (placement) => ["stored", "file"].includes(previewSource(placement));

function effectivePreviewUrl(placement, pageIndex, maxSide) {
  if (imageViewMode === "page" && Array.isArray(placement.bbox) && placement.bbox.length === 4) {
    return regionPreviewUrl(placement, pageIndex, maxSide);
  }
  return placementPreviewUrl(placement, pageIndex, maxSide);
}

/* One thumbnail. Clicking it opens the scalable viewer, which needs to know
   where to get bigger pixels from, hence the data attributes. */
function thumbHtml(placement, page, alt, maxSide) {
  const pageIndex = page ? page.page_number : 0;
  const source = previewSource(placement);
  const url = effectivePreviewUrl(placement, pageIndex, maxSide);
  if (!url) {
    return `<p class="notice small">No pixels available for this image: it has no xref and no
      position on the page, so neither its bytes nor a region render can be produced.</p>`;
  }
  return `<img class="thumb" alt="${escapeHtml(alt)}" src="${url}"
    data-fallback="${source === "file" ? "stored" : "preview"}"
    data-viewer="open"
    data-source="${source}"
    data-mode="${hasOwnPixels(placement) ? imageViewMode : "page"}"
    data-label="${escapeHtml(PLACEMENT_LABEL(placement))}"
    data-page="${pageIndex}"
    data-xref="${placement.xref || ""}"
    data-file="${escapeHtml(placement.file || "")}"
    data-bbox="${(placement.bbox || []).join(",")}"
    data-pixels="${placement.width || ""}x${placement.height || ""}" />`;
}

/* Switch between the two views. Only shown when both are possible. */
function imageModeToggleHtml(placement) {
  const canRegion = Array.isArray(placement.bbox) && placement.bbox.length === 4;
  if (!hasOwnPixels(placement) || !canRegion) return "";
  const button = (mode, label, title) =>
    `<button class="button small${imageViewMode === mode ? " primary" : ""}"
      data-image-mode="${mode}" title="${escapeHtml(title)}">${label}</button>`;
  return `<span class="mode-toggle">
    ${button("stored", "Stored image", "The image's own pixels — what a download contains")}
    ${button("page", "As on page", "This region of the page, with text and graphics drawn over the image")}
  </span>`;
}

const IMAGE_MODE_NOTE = {
  stored: `Showing the image's own pixels. Anything the page draws over it — text
    labels, vector graphics — is not part of the image; switch to <em>As on page</em>
    to see the composited result.`,
  page: `Showing this region of the page, so text and vector graphics drawn over
    the image are included. Switch to <em>Stored image</em> for the image's own
    pixels.`,
};

/* Every image on the page as a pickable strip. Overlapping images (a scan under
   a stamp, two revisions of a drawing on top of each other) cannot all be
   reached by clicking the page, so they are listed here as well. */
function imageChoicesHtml(page, current) {
  const placements = (page && page.images.placements) || [];
  if (placements.length < 2) return "";
  const items = placements
    .map((placement, index) => {
      const url = effectivePreviewUrl(placement, page.page_number, 120);
      const selected = placement === current ? " current" : "";
      const label = placement.xref ? `xref ${placement.xref}` : `inline ${index}`;
      return `<div class="image-choice${selected}" data-choice="${index}" title="${escapeHtml(
        PLACEMENT_LABEL(placement)
      )} — ${placement.width || "?"} × ${placement.height || "?"} px">
        ${url ? `<img src="${url}" alt="${escapeHtml(label)}" data-fallback="preview" />` : ""}
        <span class="label">${escapeHtml(label)}</span>
      </div>`;
    })
    .join("");
  return `<h3>Images on this page (${placements.length})</h3>
    <div class="image-choices">${items}</div>`;
}

/* `error` does not bubble, but it does reach capture-phase listeners, so one
   handler covers every thumbnail the UI ever renders. */
document.addEventListener(
  "error",
  (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement) || !image.dataset.fallback) return;
    const note = document.createElement("p");
    note.className = "notice small";
    note.textContent =
      image.dataset.fallback === "preview"
        ? "This image could not be decoded for display. Download keeps the original bytes."
        : "This browser cannot display the stored image format. Use Download instead.";
    image.replaceWith(note);
  },
  true
);

/* ------------------------------------------------------------- image viewer
 *
 * A thumbnail is too small to judge a scan by, so clicking one opens a viewer
 * that scales freely. Zoom is expressed against the image's own pixels: 100 %
 * means one image pixel per CSS pixel. When the display size grows past the
 * raster that was fetched, a larger one is requested, so zooming in shows more
 * detail rather than a blurrier bitmap.
 */

const VIEWER_MIN_ZOOM = 0.05;
const VIEWER_MAX_ZOOM = 8;
const VIEWER_MAX_RASTER = 4000;

const viewer = {
  target: null, // {label, pixels, source, urlFor(maxSide), downloadUrl, copyUrl, note}
  zoom: null, // null means "fit to window"
  raster: 0, // longest side of the raster currently loaded
};

/* Build a viewer target from the data attributes of a thumbnail. The target can
   show either the stored pixels or the page region, whichever the thumbnail was
   showing, and can switch between them while open. */
function viewerTargetFromThumb(image) {
  const xref = image.dataset.xref ? Number(image.dataset.xref) : null;
  const file = image.dataset.file || null;
  const pageIndex = Number(image.dataset.page || 0);
  const bbox = (image.dataset.bbox || "")
    .split(",")
    .filter((part) => part !== "")
    .map(Number);
  const [width, height] = (image.dataset.pixels || "").split("x").map(Number);
  const placement = { xref, file, bbox, index: 0 };
  const canStored = previewSource(placement) !== "region" && (xref || file);
  const canPage = bbox.length === 4;

  return {
    label: image.dataset.label || "Image",
    pixels: [width || 0, height || 0],
    mode: image.dataset.mode === "page" || !canStored ? "page" : "stored",
    modes: { stored: Boolean(canStored), page: canPage },
    get source() {
      return this.mode === "page" ? "region" : "stored";
    },
    urlFor(maxSide) {
      return this.mode === "page"
        ? regionPreviewUrl(placement, pageIndex, maxSide)
        : placementPreviewUrl(placement, pageIndex, maxSide);
    },
    get downloadUrl() {
      if (this.mode === "page") return regionPreviewUrl(placement, pageIndex, VIEWER_MAX_RASTER);
      return file ? storedImageUrl(file) : imagePreviewUrl(xref, VIEWER_MAX_RASTER);
    },
    get copyUrl() {
      if (this.mode === "page") return regionPreviewUrl(placement, pageIndex, VIEWER_MAX_RASTER);
      return xref ? imagePreviewUrl(xref) : storedImageUrl(file);
    },
    get note() {
      if (this.mode === "page") {
        return this.modes.stored
          ? "Showing this region of the page: text and vector graphics drawn over the image are included. Download gives this render as PNG."
          : "These pixels are a render of this region of the page: the image itself has no extractable bytes, so there is nothing to download in its original format.";
      }
      return "Showing the image's own pixels, as a PNG re-encode. Anything the page draws over the image is not part of it. Download gives the original bytes, in the format the PDF used.";
    },
  };
}

function openImageViewer(target) {
  viewer.target = target;
  viewer.zoom = null;
  viewer.raster = 0;
  el("viewer-title").textContent = target.label;
  syncViewerChrome();
  const dialog = el("image-viewer");
  if (!dialog.open) dialog.showModal();
  applyViewerZoom();
}

/* Labels, note and the mode buttons, which only appear when both views exist. */
function syncViewerChrome() {
  const target = viewer.target;
  el("viewer-meta").textContent = target.pixels[0]
    ? `${target.pixels[0]} × ${target.pixels[1]} px image`
    : "";
  el("viewer-note").textContent = target.note;
  const both = target.modes.stored && target.modes.page;
  el("viewer-modes").classList.toggle("hidden", !both);
  el("viewer-modes")
    .querySelectorAll("[data-viewer-mode]")
    .forEach((button) => {
      button.classList.toggle("primary", button.dataset.viewerMode === target.mode);
    });
}

function setViewerMode(mode) {
  const target = viewer.target;
  if (!target || target.mode === mode || !target.modes[mode]) return;
  target.mode = mode;
  viewer.raster = 0;
  syncViewerChrome();
  applyViewerZoom();
}

/* Fit means: whole image inside the body, never enlarged past 100 %. */
function viewerFitZoom() {
  const body = el("viewer-body");
  const [width, height] = viewer.target.pixels;
  if (!width || !height) return 1;
  const available = Math.max(1, body.clientWidth - 24);
  const availableHeight = Math.max(1, body.clientHeight - 24);
  return Math.min(1, available / width, availableHeight / height);
}

function applyViewerZoom() {
  if (!viewer.target) return;
  const image = el("viewer-image");
  const [width, height] = viewer.target.pixels;
  const zoom = viewer.zoom === null ? viewerFitZoom() : viewer.zoom;
  el("viewer-zoom").textContent = `${Math.round(zoom * 100)}%`;

  if (width && height) {
    image.style.width = `${Math.max(1, Math.round(width * zoom))}px`;
    image.style.height = "auto";
  } else {
    image.style.width = "auto";
  }
  /* Past 200 % the point is to inspect individual pixels, so stop smoothing. */
  image.style.imageRendering = zoom >= 2 ? "pixelated" : "auto";

  /* Ask for a raster at least as large as the pixels being shown, in steps so
     that dragging the zoom does not trigger a request per frame. Stored images
     are never re-requested beyond their own resolution, since the server does
     not upscale; region renders are, because the page's vector content keeps
     gaining detail. */
  const shown = Math.max(width * zoom, height * zoom, 1);
  const ceiling =
    viewer.target.source === "region" || !width || !height
      ? VIEWER_MAX_RASTER
      : Math.min(VIEWER_MAX_RASTER, Math.max(width, height));
  const wanted = Math.min(ceiling, Math.max(400, Math.ceil(shown / 400) * 400));
  if (wanted > viewer.raster) {
    viewer.raster = wanted;
    image.src = viewer.target.urlFor(wanted);
  }
}

function setViewerZoom(zoom) {
  viewer.zoom = Math.max(VIEWER_MIN_ZOOM, Math.min(VIEWER_MAX_ZOOM, zoom));
  applyViewerZoom();
}

function stepViewerZoom(factor) {
  const current = viewer.zoom === null ? viewerFitZoom() : viewer.zoom;
  setViewerZoom(current * factor);
}

el("image-viewer").addEventListener("click", (event) => {
  const modeButton = event.target.closest("[data-viewer-mode]");
  if (modeButton) {
    setViewerMode(modeButton.dataset.viewerMode);
    return;
  }
  const action = event.target.dataset.viewer;
  if (!action || !viewer.target) return;
  if (action === "in") stepViewerZoom(1.25);
  else if (action === "out") stepViewerZoom(1 / 1.25);
  else if (action === "fit") {
    viewer.zoom = null;
    applyViewerZoom();
  } else if (action === "actual") setViewerZoom(1);
  else if (action === "download") download(viewer.target.downloadUrl);
  else if (action === "copy") copyImage(viewer.target.copyUrl, viewer.target.label);
  else if (action === "close") el("image-viewer").close();
});

el("image-viewer").addEventListener("keydown", (event) => {
  if (!viewer.target) return;
  const steps = { "+": 1.25, "=": 1.25, "-": 1 / 1.25 };
  if (event.key in steps) {
    event.preventDefault();
    stepViewerZoom(steps[event.key]);
  } else if (event.key === "0") {
    viewer.zoom = null;
    applyViewerZoom();
  } else if (event.key === "1") {
    setViewerZoom(1);
  }
});

/* Ctrl/Cmd + wheel zooms, plain wheel scrolls the oversized image. */
el("viewer-body").addEventListener(
  "wheel",
  (event) => {
    if (!viewer.target || !(event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    stepViewerZoom(event.deltaY < 0 ? 1.1 : 1 / 1.1);
  },
  { passive: false }
);

window.addEventListener("resize", () => {
  if (el("image-viewer").open && viewer.zoom === null) applyViewerZoom();
});

/* Any thumbnail opens the viewer. */
document.addEventListener("click", (event) => {
  const image = event.target.closest('img.thumb[data-viewer="open"]');
  if (!image) return;
  openImageViewer(viewerTargetFromThumb(image));
});

/* ---------------------------------------------------------------- documents */

function currentDoc() {
  return state.selected ? state.docState.get(state.selected) : null;
}

function currentSummary() {
  return state.documents.find((d) => d.document_id === state.selected) || null;
}

async function refreshDocuments() {
  const data = await apiJson("/api/documents");
  state.documents = data.documents;
  el("pool-status").textContent = `${data.pool.workers} worker processes · ${data.documents.length}/${data.limits.max_documents} documents open`;
  renderDocumentList();

  for (const summary of state.documents) {
    if (summary.status === "ready" && !state.docState.has(summary.document_id)) {
      await loadDocumentReport(summary.document_id);
    }
  }
  if (!state.selected) {
    const ready = state.documents.find((d) => d.status === "ready");
    if (ready) selectDocument(ready.document_id);
  }
  const busy = state.documents.some((d) => d.status === "pending" || d.status === "analyzing");
  clearTimeout(state.polling);
  if (busy) state.polling = setTimeout(refreshDocuments, 900);
}

async function loadDocumentReport(documentId) {
  const data = await apiJson(`/api/documents/${documentId}`);
  state.docState.set(documentId, {
    report: data.report,
    pageIndex: 0,
    pages: new Map(),
    elementsByPage: new Map(),
    drawingsWindow: null,
    operatorsWindow: null,
    scrollTop: 0,
    zoom: 1,
    tab: "page",
    toggles: Object.fromEntries(OVERLAY_KINDS.map((k) => [k.key, k.on])),
    object: null,
  });
}

function renderDocumentList() {
  const list = el("document-list");
  el("document-empty").classList.toggle("hidden", state.documents.length > 0);
  list.innerHTML = state.documents
    .map((doc) => {
      const selected = doc.document_id === state.selected ? " selected" : "";
      const duplicate = doc.duplicate_of
        ? `<div class="small muted">same bytes as another open document</div>`
        : "";
      const error = doc.error ? `<div class="small error-text">${escapeHtml(doc.error)}</div>` : "";
      return `<li class="document-item${selected}" data-doc="${doc.document_id}">
        <div class="name">${escapeHtml(doc.source_name)}</div>
        <div class="meta"><span>${formatBytes(doc.size_bytes)}</span><span>${
        doc.page_count == null ? "—" : `${doc.page_count} pages`
      }</span></div>
        ${duplicate}${error}
        <div class="row">
          <span class="status ${doc.status}">${escapeHtml(doc.stage || doc.status)}</span>
          <span class="actions">
            ${
              doc.status === "needs_password"
                ? `<button class="button small" data-unlock="${doc.document_id}">Unlock</button>`
                : ""
            }
            <button class="button small" data-close="${doc.document_id}">Close</button>
          </span>
        </div>
      </li>`;
    })
    .join("");
}

function selectDocument(documentId) {
  state.selected = documentId;
  renderDocumentList();
  renderDocument();
}

/* ------------------------------------------------------------------ layout */

function renderDocument() {
  const doc = currentDoc();
  const summary = currentSummary();
  const hasDoc = Boolean(doc && summary);
  el("document-header").classList.toggle("hidden", !hasDoc);
  el("tabs").classList.toggle("hidden", !hasDoc);
  el("no-selection").classList.toggle("hidden", hasDoc);
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
  if (!hasDoc) {
    teardownPageView();
    el("page-canvas").replaceChildren();
    return;
  }

  const report = doc.report;
  el("document-title").textContent = summary.source_name;
  el("document-subtitle").innerHTML = [
    escapeHtml(report.file.pdf_version || "unknown version"),
    `${report.file.page_count} pages`,
    formatBytes(report.identity.source_size_bytes),
    `${report.file.xref.xref_length || 0} xref slots`,
    report.encryption.is_encrypted ? "encrypted" : "not encrypted",
    `sha256 ${report.identity.sha256.slice(0, 16)}…`,
    `id ${summary.document_id.slice(0, 8)}`,
  ].join(" · ");

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === doc.tab);
  });
  const panel = document.querySelector(`.panel[data-panel="${doc.tab}"]`);
  panel.classList.add("active");
  renderPanel(doc.tab, panel, doc, report);
}

function renderPanel(tab, panel, doc, report) {
  switch (tab) {
    case "page":
      renderPagePanel(doc);
      break;
    case "structure":
      panel.innerHTML = structureHtml(report);
      break;
    case "objects":
      panel.innerHTML = objectsHtml(doc);
      break;
    case "metadata":
      panel.innerHTML = metadataHtml(report);
      break;
    case "fonts":
      panel.innerHTML = fontsHtml(report);
      break;
    case "text":
      renderPageDependentPanel(panel, doc, textHtml);
      break;
    case "images":
      renderPageDependentPanel(panel, doc, imagesHtml);
      break;
    case "drawings":
      renderPageDependentPanel(panel, doc, drawingsHtml);
      break;
    case "annotations":
      renderPageDependentPanel(panel, doc, annotationsHtml);
      break;
    case "stream":
      renderPageDependentPanel(panel, doc, streamHtml);
      break;
    case "forms":
      panel.innerHTML = formsHtml(report);
      break;
    case "attachments":
      panel.innerHTML = attachmentsHtml(report);
      break;
    case "limits":
      panel.innerHTML = limitsHtml(report);
      break;
    default:
      panel.innerHTML = "";
  }
}

async function renderPageDependentPanel(panel, doc, builder) {
  panel.innerHTML = `<p class="muted">Extracting page ${doc.pageIndex + 1}…</p>`;
  try {
    const page = await ensurePage(doc, doc.pageIndex);
    panel.innerHTML = builder(page, doc);
  } catch (error) {
    panel.innerHTML = `<p class="error-text">Page extraction failed: ${escapeHtml(error.message)}</p>`;
  }
}

async function ensurePage(doc, pageIndex) {
  if (doc.pages.has(pageIndex)) return doc.pages.get(pageIndex);
  const page = await apiJson(`/api/documents/${state.selected}/pages/${pageIndex}`);
  doc.pages.set(pageIndex, page);
  return page;
}

/* -------------------------------------------------------------- page panel
 *
 * The page view is a continuous scroller: one slot per page, stacked in
 * document order, so a document is read by scrolling like in any PDF viewer.
 * The toolbar keeps first / previous / next / last and the page jump; those
 * scroll the container instead of swapping a single image.
 *
 * Slots start as placeholders sized from the document report
 * (page.rect x zoom), so the scrollbar is correct without touching one page.
 * Only pages near the viewport get a render, a page report and an overlay;
 * slots that drift away are unloaded again. A 500-page document therefore
 * costs the same as a 5-page one until it is actually scrolled.
 */

const PAGE_LOAD_WINDOW = 2; // pages kept rendered on each side of the current page
const MAX_PAGE_REPORTS = 12; // page reports cached per document
const A4_POINTS = [595.28, 841.89]; // fallback when a page summary carries an error
const SCROLL_MARGIN = 12; // px kept above a page when scrolled to

/* Live state of the scroller for the selected document. Rebuilt when the
   document changes; only resized on zoom, so scroll position survives. */
const pageView = {
  documentId: null,
  zoom: null,
  slots: [],
  loaded: new Set(),
  loadObserver: null,
  currentObserver: null,
  visible: new Set(),
  currentSlot: -1,
  scrollFrame: null,
};

const renderDpi = (zoom) => Math.max(48, Math.min(400, Math.round(96 * zoom)));

const pageRenderUrl = (documentId, index, zoom) =>
  `/api/documents/${documentId}/pages/${index}/render.png?dpi=${renderDpi(zoom)}`;

/* Page size in points, taken from the document report so no page has to be
   extracted before the scroller can be laid out. */
function pagePointSize(doc, index) {
  const summary = (doc.report.pages || [])[index] || {};
  if (Array.isArray(summary.rect)) {
    return [summary.rect[2] - summary.rect[0], summary.rect[3] - summary.rect[1]];
  }
  if (summary.width && summary.height) return [summary.width, summary.height];
  return A4_POINTS;
}

function pageSlotLabel(doc, index, total) {
  const summary = (doc.report.pages || [])[index] || {};
  const label =
    summary.label && summary.label !== String(index + 1) ? ` · label ${summary.label}` : "";
  return `Page ${index + 1} of ${total}${label}`;
}

function placeholderNode(index) {
  const node = document.createElement("div");
  node.className = "page-placeholder";
  node.textContent = `Page ${index + 1}`;
  return node;
}

async function renderPagePanel(doc) {
  const total = doc.report.file.page_count;
  el("page-jump").max = String(total);
  el("zoom-label").textContent = `${Math.round(doc.zoom * 100)}%`;
  el("overlay-toggles").innerHTML = OVERLAY_KINDS.map(
    (kind) =>
      `<label><input type="checkbox" data-toggle="${kind.key}" ${
        doc.toggles[kind.key] ? "checked" : ""
      } /> <span class="box-key ${kind.key}">${kind.label}</span></label>`
  ).join("");

  const canvas = el("page-canvas");
  if (pageView.documentId !== state.selected) {
    buildPageView(doc);
    canvas.scrollTo({ top: doc.scrollTop || 0, behavior: "auto" });
  } else if (pageView.zoom !== doc.zoom) {
    resizePageView(doc);
  } else {
    /* The panel may have been hidden while another tab was active; the
       browser keeps scrollTop, but restore it defensively. */
    canvas.scrollTo({ top: doc.scrollTop || 0, behavior: "auto" });
  }

  syncPageToolbar(doc);
  markCurrentSlot(doc);
  ensureWindowLoaded(doc);
  showPageDetails(doc, doc.pageIndex);
}

function buildPageView(doc) {
  const canvas = el("page-canvas");
  teardownPageView();

  const total = doc.report.file.page_count;
  const scroller = document.createElement("div");
  scroller.className = "page-scroll";
  const slots = [];
  for (let index = 0; index < total; index += 1) {
    const slot = document.createElement("div");
    slot.className = "page-slot";
    slot.dataset.page = String(index);

    const label = document.createElement("div");
    label.className = "page-slot-label";
    label.textContent = pageSlotLabel(doc, index, total);

    const stage = document.createElement("div");
    stage.className = "page-stage";
    stage.appendChild(placeholderNode(index));
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    stage.appendChild(overlay);

    slot.append(label, stage);
    scroller.appendChild(slot);
    slots.push(slot);
  }

  canvas.replaceChildren(scroller);
  pageView.documentId = state.selected;
  pageView.zoom = doc.zoom;
  pageView.slots = slots;
  applySlotSizes(doc);

  /* Loading observer: a page is loaded slightly before it scrolls into view. */
  pageView.loadObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) loadSlot(Number(entry.target.dataset.page));
      });
    },
    { root: canvas, rootMargin: "300px 0px" }
  );
  /* Current-page observer: a thin band across the middle of the viewport.
     Whatever page crosses that band is the page the user is looking at, which
     avoids doing scroll arithmetic over hundreds of slots. */
  pageView.currentObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const index = Number(entry.target.dataset.page);
        if (entry.isIntersecting) pageView.visible.add(index);
        else pageView.visible.delete(index);
      });
      const active = currentDoc();
      if (!active || pageView.documentId !== state.selected || !pageView.visible.size) return;
      setCurrentPage(active, Math.min(...pageView.visible), { scroll: false });
    },
    { root: canvas, rootMargin: "-45% 0px -45% 0px" }
  );
  slots.forEach((slot) => {
    pageView.loadObserver.observe(slot);
    pageView.currentObserver.observe(slot);
  });
}

function teardownPageView() {
  if (pageView.loadObserver) pageView.loadObserver.disconnect();
  if (pageView.currentObserver) pageView.currentObserver.disconnect();
  pageView.loadObserver = null;
  pageView.currentObserver = null;
  pageView.documentId = null;
  pageView.zoom = null;
  pageView.slots = [];
  pageView.loaded = new Set();
  pageView.visible = new Set();
  pageView.currentSlot = -1;
}

/* Placeholder geometry uses the document report; once a page report is cached
   its own page.rect is used, which is the value the overlay is placed against. */
function applySlotSizes(doc) {
  pageView.slots.forEach((slot, index) => {
    const page = doc.pages.get(index);
    const [width, height] = page
      ? [
          page.page.boxes.rect[2] - page.page.boxes.rect[0],
          page.page.boxes.rect[3] - page.page.boxes.rect[1],
        ]
      : pagePointSize(doc, index);
    const stage = slot.querySelector(".page-stage");
    stage.style.width = `${width * doc.zoom}px`;
    stage.style.height = `${height * doc.zoom}px`;
  });
}

/* Zoom keeps the scroller in place: slots are resized, loaded pages are
   re-requested at the new dpi and their overlays redrawn at the new scale. */
function resizePageView(doc) {
  pageView.zoom = doc.zoom;
  applySlotSizes(doc);
  pageView.loaded.forEach((index) => {
    const stage = pageView.slots[index].querySelector(".page-stage");
    const image = stage.querySelector("img");
    if (image) image.src = pageRenderUrl(state.selected, index, doc.zoom);
    const page = doc.pages.get(index);
    if (page) applyPageOverlay(doc, index, page);
  });
  scrollToPage(doc, doc.pageIndex, "auto");
}

async function loadSlot(index) {
  const doc = currentDoc();
  if (!doc || pageView.documentId !== state.selected) return;
  const slot = pageView.slots[index];
  if (!slot || pageView.loaded.has(index)) return;
  pageView.loaded.add(index);

  const stage = slot.querySelector(".page-stage");
  const image = document.createElement("img");
  image.alt = `rendered page ${index + 1}`;
  image.decoding = "async";
  image.onload = () => {
    const placeholder = stage.querySelector(".page-placeholder");
    if (placeholder) placeholder.remove();
  };
  image.onerror = () => failSlot(slot, `Page ${index + 1} could not be rendered`);
  image.src = pageRenderUrl(state.selected, index, doc.zoom);
  stage.insertBefore(image, stage.firstChild);

  try {
    const page = await ensurePage(doc, index);
    if (pageView.documentId !== state.selected || !pageView.loaded.has(index)) return;
    applyPageOverlay(doc, index, page);
  } catch (error) {
    failSlot(slot, `Page ${index + 1}: ${error.message}`);
  }
}

function unloadSlot(doc, index) {
  const slot = pageView.slots[index];
  if (!slot || !pageView.loaded.has(index)) return;
  pageView.loaded.delete(index);
  const stage = slot.querySelector(".page-stage");
  stage.querySelectorAll("img").forEach((image) => {
    image.onload = null;
    image.onerror = null;
    image.remove();
  });
  const overlay = stage.querySelector(".overlay");
  if (overlay) overlay.replaceChildren();
  if (!stage.querySelector(".page-placeholder")) {
    stage.insertBefore(placeholderNode(index), stage.firstChild);
  }
  doc.elementsByPage.delete(index);
}

function failSlot(slot, message) {
  const stage = slot.querySelector(".page-stage");
  let placeholder = stage.querySelector(".page-placeholder");
  if (!placeholder) {
    placeholder = placeholderNode(Number(slot.dataset.page));
    stage.insertBefore(placeholder, stage.firstChild);
  }
  placeholder.classList.add("error");
  placeholder.textContent = message;
}

function ensureWindowLoaded(doc) {
  const total = doc.report.file.page_count;
  for (let offset = -PAGE_LOAD_WINDOW; offset <= PAGE_LOAD_WINDOW; offset += 1) {
    const index = doc.pageIndex + offset;
    if (index >= 0 && index < total) loadSlot(index);
  }
}

/* Bound both memory costs: rendered bitmaps in the DOM, and cached page
   reports (a text-heavy page report can be several megabytes). */
function pruneLoadedPages(doc) {
  Array.from(pageView.loaded).forEach((index) => {
    if (Math.abs(index - doc.pageIndex) > PAGE_LOAD_WINDOW + 1) unloadSlot(doc, index);
  });
  if (doc.pages.size <= MAX_PAGE_REPORTS) return;
  /* Oldest first (Map keeps insertion order); never drop a report a loaded
     slot still needs. */
  Array.from(doc.pages.keys()).forEach((index) => {
    if (doc.pages.size <= MAX_PAGE_REPORTS) return;
    if (index === doc.pageIndex || pageView.loaded.has(index)) return;
    doc.pages.delete(index);
  });
}

function applyPageOverlay(doc, index, page) {
  const slot = pageView.slots[index];
  if (!slot) return;
  const stage = slot.querySelector(".page-stage");
  const rect = page.page.boxes.rect;
  const scale = doc.zoom;
  /* The report's own page.rect is authoritative: the render covers exactly
     this rect, so overlay boxes and bitmap share one coordinate system. */
  stage.style.width = `${(rect[2] - rect[0]) * scale}px`;
  stage.style.height = `${(rect[3] - rect[1]) * scale}px`;
  drawOverlay(stage.querySelector(".overlay"), page, doc, index, rect, scale);
}

function redrawOverlays(doc) {
  pageView.loaded.forEach((index) => {
    const page = doc.pages.get(index);
    if (page) applyPageOverlay(doc, index, page);
  });
}

function syncPageToolbar(doc) {
  const total = doc.report.file.page_count;
  el("page-indicator").textContent = `${doc.pageIndex + 1} / ${total}`;
  const jump = el("page-jump");
  if (document.activeElement !== jump) jump.value = String(doc.pageIndex + 1);
}

function markCurrentSlot(doc) {
  if (pageView.currentSlot === doc.pageIndex) return;
  const previous = pageView.slots[pageView.currentSlot];
  if (previous) previous.classList.remove("current");
  const slot = pageView.slots[doc.pageIndex];
  if (slot) slot.classList.add("current");
  pageView.currentSlot = doc.pageIndex;
}

function scrollToPage(doc, index, behavior = "smooth") {
  const canvas = el("page-canvas");
  const slot = pageView.slots[index];
  if (!slot) return;
  const top =
    canvas.scrollTop +
    (slot.getBoundingClientRect().top - canvas.getBoundingClientRect().top) -
    SCROLL_MARGIN;
  canvas.scrollTo({ top: Math.max(0, top), behavior });
  doc.scrollTop = Math.max(0, top);
}

function setCurrentPage(doc, index, options = {}) {
  const total = doc.report.file.page_count;
  const next = Math.min(Math.max(0, index), total - 1);
  const changed = next !== doc.pageIndex;
  doc.pageIndex = next;
  if (changed) {
    /* Windowed lists belong to a page. */
    doc.drawingsWindow = null;
    doc.operatorsWindow = null;
  }
  syncPageToolbar(doc);
  markCurrentSlot(doc);
  if (options.scroll) scrollToPage(doc, next, options.behavior);
  ensureWindowLoaded(doc);
  pruneLoadedPages(doc);
  if (changed) showPageDetails(doc, next);
}

/* The details panel follows the page in view unless the user has an element
   selected on that same page. */
async function showPageDetails(doc, index) {
  const details = el("element-details");
  doc.selectedElement = null;
  if (doc.pages.has(index)) {
    details.innerHTML = pageSummaryHtml(doc.pages.get(index));
    return;
  }
  details.innerHTML = `<p class="muted small">Extracting page ${index + 1}…</p>`;
  try {
    const page = await ensurePage(doc, index);
    if (doc !== currentDoc() || doc.pageIndex !== index) return;
    details.innerHTML = pageSummaryHtml(page);
  } catch (error) {
    if (doc !== currentDoc() || doc.pageIndex !== index) return;
    details.innerHTML = `<p class="error-text">${escapeHtml(error.message)}</p>`;
  }
}

function collectElements(page) {
  const items = [];
  const push = (kind, label, bbox, payload) => {
    if (!Array.isArray(bbox)) return;
    items.push({ kind, label, bbox, payload });
  };

  (page.text.structure.blocks || []).forEach((block) => {
    if (block.type === "text") {
      push("block", `Text block ${block.index}`, block.bbox, block);
      (block.lines || []).forEach((line) => {
        push("line", `Block ${block.index} line ${line.index}`, line.bbox, line);
        (line.spans || []).forEach((span) => {
          push("span", `Span "${(span.text || "").slice(0, 24)}"`, span.bbox, span);
          (span.chars || []).forEach((char) =>
            push("char", `Char "${char.c}"`, char.bbox, char)
          );
        });
      });
    }
  });

  (page.images.placements || []).forEach((placement) =>
    push(
      "image",
      placement.xref ? `Image xref ${placement.xref}` : `Inline image ${placement.index}`,
      placement.bbox,
      placement
    )
  );
  (page.drawings || []).forEach((path) =>
    push("drawing", `Path ${path.index} (${path.type_label || path.type})`, path.rect, path)
  );
  (page.annotations || []).forEach((annot) =>
    push("annotation", `${annot.type} annotation (xref ${annot.xref})`, annot.rect, annot)
  );
  (page.links || []).forEach((link) =>
    push("link", `Link ${link.index}`, link.rect, link)
  );
  (page.widgets || []).forEach((widget) =>
    push("widget", `Field ${widget.field_name || widget.index}`, widget.rect, widget)
  );
  return items;
}

function drawOverlay(overlay, page, doc, pageIndex, rect, scale) {
  if (!overlay) return;
  const fragment = document.createDocumentFragment();
  const elements = collectElements(page);
  doc.elementsByPage.set(pageIndex, elements);

  elements.forEach((item, index) => {
    if (!doc.toggles[item.kind]) return;
    const [x0, y0, x1, y1] = item.bbox;
    const node = document.createElement("div");
    node.className = `box ${item.kind}`;
    node.style.left = `${(x0 - rect[0]) * scale}px`;
    node.style.top = `${(y0 - rect[1]) * scale}px`;
    node.style.width = `${Math.max(1, (x1 - x0) * scale)}px`;
    node.style.height = `${Math.max(1, (y1 - y0) * scale)}px`;
    node.title = item.label;
    node.dataset.page = String(pageIndex);
    node.dataset.element = String(index);
    fragment.appendChild(node);
  });
  overlay.replaceChildren(fragment);
}

function pageSummaryHtml(page) {
  const text = page.text;
  const boxes = page.page.boxes;
  const warning = text.has_text_layer
    ? ""
    : `<div class="notice">${escapeHtml(text.note)}</div>`;
  return `
    <h3>Page ${page.page_number + 1}</h3>
    ${warning}
    <dl class="kv">
      <dt>Page xref</dt><dd>${page.page.xref}</dd>
      <dt>Rotation</dt><dd>${page.page.rotation}°</dd>
      <dt>Rect (points)</dt><dd>${roundList(boxes.rect)}</dd>
      <dt>MediaBox</dt><dd>${roundList(boxes.mediabox)}</dd>
      <dt>CropBox</dt><dd>${roundList(boxes.cropbox)}</dd>
      <dt>TrimBox</dt><dd>${roundList(boxes.trimbox)}</dd>
      <dt>BleedBox</dt><dd>${roundList(boxes.bleedbox)}</dd>
      <dt>ArtBox</dt><dd>${roundList(boxes.artbox)}</dd>
      <dt>PDF-space rect</dt><dd>${roundList(page.page.rect_in_pdf_space)}</dd>
      <dt>PDF↔MuPDF matrix</dt><dd>${roundList(page.page.transformation_matrix, 3)}</dd>
      <dt>Characters</dt><dd>${text.character_count}</dd>
      <dt>Images</dt><dd>${(page.images.placements || []).length} placements</dd>
      <dt>Drawings</dt><dd>${(page.drawings || []).length}</dd>
      <dt>Annotations</dt><dd>${(page.annotations || []).length}</dd>
      <dt>Links</dt><dd>${(page.links || []).length}</dd>
      <dt>Form fields</dt><dd>${(page.widgets || []).length}</dd>
    </dl>
    <p class="muted small">
      All coordinates are PDF points with the origin at the top-left of the page rect
      (PyMuPDF space). The PDF-space rect above uses the file's own bottom-left origin.
    </p>
    ${actionBar([
      { act: "copy-page-json", label: "Copy page JSON" },
      { act: "download-page-json", label: "Download page JSON" },
    ])}`;
}

function elementDetailsHtml(item, page) {
  const [x0, y0, x1, y1] = item.bbox;
  const extra = [];
  if (item.kind === "span") {
    extra.push(
      ["Font", item.payload.font],
      ["Size", item.payload.size],
      ["Colour", item.payload.color ? item.payload.color.hex : "—"],
      [
        "Flags",
        Object.entries(item.payload.font_flags || {})
          .filter(([, on]) => on)
          .map(([name]) => name)
          .join(", ") || "none",
      ]
    );
  }
  if (item.kind === "image") {
    const placement = item.payload;
    extra.push(
      ["xref", placement.xref ?? "inline"],
      ["Pixels", `${placement.width} × ${placement.height}`],
      ["DPI", `${placement.xres} × ${placement.yres}`],
      ["Colourspace", placement.colorspace_name || placement.colorspace_components],
      ["Bits/component", placement.bits_per_component],
      ["Transparency mask", placement.has_mask ? "yes" : "no"],
      ["Matrix", roundList(placement.transform, 3)]
    );
  }
  if (item.kind === "drawing") {
    extra.push(
      ["Type", item.payload.type_label],
      ["Stroke", item.payload.stroke ? item.payload.stroke.hex : "none"],
      ["Fill", item.payload.fill ? item.payload.fill.hex : "none"],
      ["Width", item.payload.width],
      ["Dashes", item.payload.dashes],
      ["Path items", (item.payload.items || []).length]
    );
  }
  if (item.kind === "annotation" || item.kind === "widget") {
    extra.push(["xref", item.payload.xref]);
  }

  const imageFile = item.kind === "image" ? item.payload.file : null;
  const imagePreview =
    item.kind === "image" ? thumbHtml(item.payload, page, "image preview", 800) : "";
  const imageChoices = item.kind === "image" ? imageChoicesHtml(page, item.payload) : "";
  if (item.kind === "image") {
    const stored = storedImageFormat(page, item.payload);
    if (stored) {
      extra.push([
        "Stored format",
        BROWSER_IMAGE_FORMATS.has(stored)
          ? stored
          : `${stored} — shown as PNG, downloads keep ${stored}`,
      ]);
    }
    extra.push([
      "Preview from",
      previewSource(item.payload) === "region"
        ? "page region render — this image has no extractable bytes"
        : "the image's own stored bytes",
    ]);
  }

  return `
    <h3>${escapeHtml(item.label)}</h3>
    ${item.kind === "image" ? imageModeToggleHtml(item.payload) : ""}
    ${imagePreview}
    ${
      imagePreview
        ? `<p class="muted small">Click the preview to open it at any size. ${
            hasOwnPixels(item.payload) &&
            Array.isArray(item.payload.bbox) &&
            item.payload.bbox.length === 4
              ? IMAGE_MODE_NOTE[imageViewMode]
              : ""
          }</p>`
        : ""
    }
    ${imageChoices}
    <dl class="kv">
      <dt>Kind</dt><dd>${item.kind}</dd>
      <dt>bbox (points)</dt><dd>${roundList(item.bbox)}</dd>
      <dt>Size</dt><dd>${(x1 - x0).toFixed(2)} × ${(y1 - y0).toFixed(2)}</dd>
      ${extra
        .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value ?? "—")}</dd>`)
        .join("")}
    </dl>
    ${
      item.payload.text !== undefined
        ? `<pre>${escapeHtml(item.payload.text)}</pre>`
        : ""
    }
    ${actionBar(
      [
        { act: "copy-element", label: "Copy element JSON" },
        item.payload.text !== undefined ? { act: "copy-element-text", label: "Copy text" } : null,
        imageFile ? { act: "download-element-image", label: "Download image" } : null,
        imageFile || item.payload.xref
          ? { act: "copy-element-image", label: "Copy image" }
          : null,
        item.payload.xref ? { act: "open-object", label: `Open xref ${item.payload.xref}` } : null,
      ].filter(Boolean)
    )}
    <details><summary class="muted small">Raw JSON</summary><pre>${escapeHtml(
      pretty(item.payload)
    )}</pre></details>`;
}

/* --------------------------------------------------------------- structure */

function treeNode(label, detail, children, meta) {
  const kids = children && children.length ? `<ul class="tree">${children.join("")}</ul>` : "";
  const data = meta ? ` data-xref="${meta}"` : "";
  return `<li><span class="node"${data}><span class="tag">${escapeHtml(label)}</span>${
    detail ? ` ${escapeHtml(detail)}` : ""
  }</span>${kids}</li>`;
}

function pageTreeHtml(node) {
  if (!node) return "";
  const kids = (node.kids || []).map(pageTreeHtml);
  const inherited = Object.entries(node.inherited || {})
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  return treeNode(
    `${node.type || "?"} ${node.xref}`,
    [node.count ? `Count ${node.count}` : "", inherited].filter(Boolean).join(" · "),
    kids,
    node.xref
  );
}

function structTreeHtml(node) {
  if (!node) return "";
  const kids = (node.kids || []).map(structTreeHtml);
  const detail = [node.title, node.alt, node.actual_text].filter(Boolean).join(" · ");
  return treeNode(`${node.tag || node.type || "node"} ${node.xref}`, detail, kids, node.xref);
}

function structureHtml(report) {
  const structure = report.structure;
  const catalogEntries = Object.entries(structure.catalog.entries || {}).map(([key, value]) =>
    treeNode(`/${key}`, value.value, [], value.xref)
  );

  const nameTrees = Object.entries(structure.name_trees.trees || {}).map(([name, tree]) =>
    treeNode(
      `/${name}`,
      `${tree.entries.length} entries`,
      tree.entries
        .slice(0, 200)
        .map((entry) => treeNode(entry.key, entry.value, [], null))
    )
  );

  const outline = structure.outline.map((item) =>
    treeNode(
      `${"·".repeat(Math.max(0, item.level - 1))} ${item.title}`,
      item.page == null ? "" : `page ${item.page + 1}`,
      []
    )
  );

  const destinations = Object.entries(structure.named_destinations || {})
    .slice(0, 300)
    .map(([name, value]) => treeNode(name, JSON.stringify(value), []));

  const structTree = structure.struct_tree_root
    ? `<ul class="tree">${structTreeHtml(structure.struct_tree_root.tree)}</ul>`
    : `<div class="notice">This document has no /StructTreeRoot: it is not tagged, so no
       logical structure tree exists in the file.</div>`;

  return `
    <div class="card">
      <div class="card-head"><h2>Catalog (xref ${report.file.catalog_xref})</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="structure.catalog"` }])}
      </div>
      <ul class="tree">${catalogEntries.join("")}</ul>
      <details><summary class="muted small">Catalog source</summary><pre>${escapeHtml(
        structure.catalog.source || ""
      )}</pre></details>
    </div>

    <div class="card">
      <div class="card-head"><h2>Page tree</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="structure.page_tree"` }])}
      </div>
      <ul class="tree">${pageTreeHtml(structure.page_tree.root)}</ul>
    </div>

    <div class="card">
      <div class="card-head"><h2>Structure tree (tagging)</h2>
        ${actionBar([
          { act: "copy-json", label: "Copy JSON", data: `data-key="structure.struct_tree_root"` },
        ])}
      </div>
      ${structTree}
    </div>

    <div class="card">
      <div class="card-head"><h2>Name trees</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="structure.name_trees"` }])}
      </div>
      ${nameTrees.length ? `<ul class="tree">${nameTrees.join("")}</ul>` : `<p class="muted small">No /Names entries.</p>`}
    </div>

    <div class="card">
      <h2>Named destinations</h2>
      ${destinations.length ? `<ul class="tree">${destinations.join("")}</ul>` : `<p class="muted small">None.</p>`}
    </div>

    <div class="card">
      <div class="card-head"><h2>Outline / table of contents</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="structure.outline"` }])}
      </div>
      ${outline.length ? `<ul class="tree">${outline.join("")}</ul>` : `<p class="muted small">No outline.</p>`}
    </div>

    <div class="card">
      <h2>Object model summary</h2>
      <dl class="kv">
        <dt>xref slots</dt><dd>${report.file.xref.xref_length}</dd>
        <dt>Stream objects</dt><dd>${report.file.xref.stream_objects}</dd>
        <dt>Object streams</dt><dd>${
          report.file.xref.uses_object_streams
            ? report.file.xref.object_streams.join(", ")
            : "not used"
        }</dd>
        <dt>Cross-reference streams</dt><dd>${
          report.file.xref.uses_cross_reference_streams
            ? report.file.xref.cross_reference_streams.join(", ")
            : "not used (classic xref table)"
        }</dd>
        <dt>Fast web view</dt><dd>${report.file.is_linearized_fast_web_view ? "yes" : "no"}</dd>
        <dt>Repaired on open</dt><dd>${report.file.is_repaired ? "yes — file was damaged" : "no"}</dd>
      </dl>
      <table>
        <thead><tr><th>Object type</th><th>Count</th></tr></thead>
        <tbody>${Object.entries(report.file.xref.type_counts)
          .map(([type, count]) => `<tr><td class="mono">${escapeHtml(type)}</td><td>${count}</td></tr>`)
          .join("")}</tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-head"><h2>Trailer</h2>
        ${actionBar([{ act: "copy-trailer", label: "Copy trailer" }])}
      </div>
      <pre>${escapeHtml(report.file.trailer || "")}</pre>
      <dl class="kv"><dt>Document /ID</dt><dd>${escapeHtml(
        (report.file.document_id || []).join(" · ") || "none"
      )}</dd></dl>
    </div>`;
}

/* ----------------------------------------------------------------- objects */

function objectsHtml(doc) {
  const object = doc.object;
  const body = object
    ? `
      <div class="card">
        <div class="card-head">
          <h2>Object ${object.xref} ${escapeHtml(object.type || "")} ${escapeHtml(
        object.subtype || ""
      )}</h2>
          ${actionBar([
            { act: "copy-object", label: "Copy object" },
            { act: "download-object-json", label: "Download JSON" },
            object.is_stream ? { act: "download-object-stream", label: "Download stream" } : null,
            object.is_stream
              ? { act: "download-object-stream-raw", label: "Download raw stream" }
              : null,
          ].filter(Boolean))}
        </div>
        <pre>${escapeHtml(object.source || "")}</pre>
        ${
          object.is_stream
            ? `<dl class="kv">
                 <dt>Raw stream bytes</dt><dd>${object.stream_raw_bytes ?? "—"}</dd>
                 <dt>Decoded bytes</dt><dd>${object.stream_decoded_bytes ?? "—"}</dd>
               </dl>
               ${
                 object.stream_decode_error
                   ? `<div class="notice">${escapeHtml(object.stream_decode_error)}</div>`
                   : `<details><summary class="muted small">Decoded stream${
                       object.stream_truncated ? " (truncated)" : ""
                     }</summary><pre>${escapeHtml(object.stream_decoded || "")}</pre></details>`
               }`
            : ""
        }
        <h3>References</h3>
        <div class="actions">${
          (object.references || [])
            .map((ref) => `<button class="button small" data-goto-xref="${ref}">${ref} 0 R</button>`)
            .join("") || `<span class="muted small">none</span>`
        }</div>
      </div>`
    : `<p class="muted">Enter an xref number to inspect any object in the file.</p>`;

  return `
    <div class="card">
      <div class="card-head">
        <h2>Object browser</h2>
        <span class="actions">
          <input id="xref-input" type="number" min="1" max="${
            doc.report.file.xref.xref_length - 1
          }" placeholder="xref" />
          <button class="button small" data-act="load-xref">Load</button>
          <button class="button small" data-goto-xref="${doc.report.file.catalog_xref}">Catalog</button>
        </span>
      </div>
      <p class="muted small">
        The file holds ${doc.report.file.xref.xref_length - 1} objects. Any reference shown in an
        object can be followed with one click.
      </p>
    </div>
    ${body}`;
}

/* ---------------------------------------------------------------- metadata */

function metadataHtml(report) {
  const info = report.metadata.info || {};
  const xmp = report.metadata.xmp || {};
  const permissions = report.encryption.permissions.allowed;
  return `
    <div class="card">
      <div class="card-head"><h2>Info dictionary</h2>
        ${actionBar([
          { act: "copy-json", label: "Copy JSON", data: `data-key="metadata"` },
          { act: "download-doc-json", label: "Download document JSON" },
        ])}
      </div>
      <table><tbody>${Object.entries(info)
        .map(
          ([key, value]) =>
            `<tr><th>${escapeHtml(key)}</th><td class="mono">${escapeHtml(value ?? "")}</td></tr>`
        )
        .join("")}</tbody></table>
    </div>

    <div class="card">
      <h2>File</h2>
      <dl class="kv">
        <dt>PDF version</dt><dd>${escapeHtml(report.file.pdf_version || "—")}</dd>
        <dt>Pages</dt><dd>${report.file.page_count}</dd>
        <dt>Page mode / layout</dt><dd>${escapeHtml(report.file.page_mode)} / ${escapeHtml(
    report.file.page_layout
  )}</dd>
        <dt>Language</dt><dd>${escapeHtml(report.file.language || "—")}</dd>
        <dt>MarkInfo</dt><dd>${escapeHtml(pretty(report.file.mark_info))}</dd>
        <dt>Page labels</dt><dd>${escapeHtml(pretty(report.file.page_labels))}</dd>
        <dt>SHA-256</dt><dd>${escapeHtml(report.identity.sha256)}</dd>
        <dt>Extractor</dt><dd>PyMuPDF ${escapeHtml(
          report.extractor.pymupdf_version
        )} / MuPDF ${escapeHtml(report.extractor.mupdf_version)}</dd>
      </dl>
    </div>

    <div class="card">
      <h2>Encryption and permissions</h2>
      <dl class="kv">
        <dt>Encrypted</dt><dd>${report.encryption.is_encrypted ? "yes" : "no"}</dd>
        <dt>Method</dt><dd>${escapeHtml(report.encryption.method || "none")}</dd>
        <dt>Permission bits</dt><dd>${report.encryption.permissions.raw}</dd>
      </dl>
      <table><thead><tr><th>Operation</th><th>Allowed</th></tr></thead><tbody>
      ${Object.entries(permissions)
        .map(
          ([name, allowed]) =>
            `<tr><td>${escapeHtml(name)}</td><td>${allowed ? "yes" : "no"}</td></tr>`
        )
        .join("")}
      </tbody></table>
    </div>

    <div class="card">
      <div class="card-head"><h2>XMP metadata</h2>
        ${xmp.present ? actionBar([{ act: "copy-xmp", label: "Copy XMP" }]) : ""}
      </div>
      ${
        xmp.present
          ? `<p class="muted small">Stored in object ${xmp.xref}.</p><pre>${escapeHtml(
              xmp.xml || ""
            )}</pre>`
          : `<p class="muted small">This document carries no XMP metadata stream.</p>`
      }
    </div>

    <div class="card">
      <div class="card-head"><h2>Document JavaScript</h2></div>
      ${
        report.javascript.length
          ? report.javascript
              .map(
                (item) =>
                  `<h3>${escapeHtml(item.name)} (xref ${item.xref})</h3><pre>${escapeHtml(
                    item.script || ""
                  )}</pre>`
              )
              .join("")
          : `<p class="muted small">No document-level JavaScript.</p>`
      }
    </div>`;
}

/* ------------------------------------------------------------------- fonts */

function fontsHtml(report) {
  const fonts = report.fonts.items;
  if (!fonts.length) return `<p class="muted">No fonts are referenced by this document.</p>`;
  return `
    <div class="card">
      <div class="card-head"><h2>Fonts (${fonts.length})</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="fonts"` }])}
      </div>
      ${
        report.fonts.scan_truncated
          ? `<div class="notice">Only the first ${report.fonts.pages_scanned} pages were scanned for fonts.</div>`
          : ""
      }
      <table>
        <thead><tr>
          <th>Base font</th><th>Subtype</th><th>Embedded</th><th>Subset</th>
          <th>Encoding</th><th>Resource</th><th>xref</th><th>Pages</th><th></th>
        </tr></thead>
        <tbody>${fonts
          .map(
            (font) => `<tr>
              <td class="mono">${escapeHtml(font.base_font)}</td>
              <td>${escapeHtml(font.subtype)}</td>
              <td>${font.embedded ? `yes (${escapeHtml(font.font_file_extension)})` : "no"}</td>
              <td class="mono">${escapeHtml(font.subset_prefix || "—")}</td>
              <td>${escapeHtml(font.encoding || "—")}</td>
              <td class="mono">${escapeHtml(font.resource_name || "—")}</td>
              <td>${font.xref}</td>
              <td>${formatPages(font.used_on_pages)}</td>
              <td>${actionBar([
                { act: "goto-xref", label: "Object", data: `data-xref="${font.xref}"` },
              ])}</td>
            </tr>`
          )
          .join("")}</tbody>
      </table>
      <p class="muted small">
        Embedded font programs can be downloaded from the object browser via the font's
        /FontDescriptor stream. Glyph outlines and CMaps are not decoded.
      </p>
    </div>`;
}

function formatPages(pages) {
  if (!pages || !pages.length) return "—";
  const shown = pages.slice(0, 8).map((p) => p + 1).join(", ");
  return pages.length > 8 ? `${shown} …(+${pages.length - 8})` : shown;
}

/* -------------------------------------------------------------------- text */

function textHtml(page) {
  const structure = page.text.structure;
  const blocks = (structure.blocks || []).filter((block) => block.type === "text");
  const header = `
    <div class="card">
      <div class="card-head"><h2>Text — page ${page.page_number + 1}</h2>
        ${actionBar([
          { act: "copy-page-text", label: "Copy page text" },
          { act: "download-page-text", label: "Download .txt" },
          { act: "download-page-md", label: "Download .md" },
          { act: "download-doc-text", label: "Whole document .txt" },
          { act: "copy-json", label: "Copy page text JSON", data: `data-key="page.text"` },
        ])}
      </div>
      ${
        page.text.has_text_layer
          ? `<p class="muted small">${page.text.character_count} characters in ${blocks.length} blocks, reading order preserved.</p>`
          : `<div class="notice">${escapeHtml(page.text.note)}</div>`
      }
      <pre>${escapeHtml(page.text.plain)}</pre>
    </div>`;

  const tree = blocks
    .map(
      (block) => `
      <div class="card">
        <div class="card-head">
          <h3>Block ${block.index} · ${roundList(block.bbox)}</h3>
          ${actionBar([
            { act: "copy-block-text", label: "Copy block text", data: `data-block="${block.index}"` },
          ])}
        </div>
        ${block.lines
          .map(
            (line) => `
          <div style="margin:6px 0 6px 10px">
            <div class="muted small">Line ${line.index} · ${roundList(line.bbox)} · direction ${roundList(
              line.direction,
              2
            )}</div>
            <table><tbody>${line.spans
              .map(
                (span) => `<tr>
                  <td class="mono">${escapeHtml(span.text)}</td>
                  <td class="mono small">${escapeHtml(span.font)} ${Number(span.size).toFixed(
                  2
                )}pt ${span.color ? span.color.hex : ""}
                    ${Object.entries(span.font_flags)
                      .filter(([, on]) => on)
                      .map(([name]) => name)
                      .join(",")}</td>
                  <td class="mono small">${roundList(span.bbox)}</td>
                  <td>${span.chars.length} chars</td>
                </tr>`
              )
              .join("")}</tbody></table>
          </div>`
          )
          .join("")}
      </div>`
    )
    .join("");

  return header + tree;
}

/* ------------------------------------------------------------------ images */

function imagesHtml(page) {
  const placements = page.images.placements || [];
  const objects = page.images.objects || [];
  if (!placements.length) {
    return `<p class="muted">No images are placed on page ${page.page_number + 1}.</p>
      ${actionBar([{ act: "download-doc-images", label: "Download all document images (zip)" }])}`;
  }
  const cards = placements
    .map((placement, index) => {
      const object = objects.find((item) => item.xref === placement.xref);
      const file = placement.file;
      const url = file ? storedImageUrl(file) : null;
      return `
      <div class="card">
        ${thumbHtml(placement, page, `image ${index}`, 600)}
        <div class="card-head">
          <h3>${placement.xref ? `xref ${placement.xref}` : "inline image"}</h3>
        </div>
        <dl class="kv">
          <dt>Placement bbox</dt><dd>${roundList(placement.bbox)}</dd>
          <dt>Matrix</dt><dd>${roundList(placement.transform, 3)}</dd>
          <dt>Pixels</dt><dd>${placement.width} × ${placement.height}</dd>
          <dt>DPI</dt><dd>${placement.xres} × ${placement.yres}</dd>
          <dt>Colourspace</dt><dd>${escapeHtml(placement.colorspace_name || "—")}</dd>
          <dt>Bits/component</dt><dd>${placement.bits_per_component}</dd>
          <dt>Format</dt><dd>${escapeHtml(object ? object.ext || "—" : "—")}</dd>
          <dt>Filters</dt><dd>${escapeHtml(object && object.object ? object.object.Filter || "—" : "—")}</dd>
          <dt>SMask</dt><dd>${object && object.smask_xref ? object.smask_xref : "none"}</dd>
          <dt>Stored size</dt><dd>${formatBytes(object ? object.byte_size : placement.stored_size)}</dd>
        </dl>
        ${
          object && object.error
            ? `<div class="notice">${escapeHtml(object.error)}</div>`
            : ""
        }
        ${actionBar(
          [
            url ? { act: "download-image", label: "Download", data: `data-file="${file}"` } : null,
            previewSource(placement) === "region"
              ? {
                  act: "download-region",
                  label: "Download region PNG",
                  data: `data-page="${page.page_number}" data-bbox="${(placement.bbox || []).join(
                    ","
                  )}"`,
                }
              : null,
            previewSource(placement) !== "none"
              ? {
                  act: "copy-image",
                  label: "Copy image",
                  data: `data-file="${file || ""}" data-xref="${
                    placement.xref || ""
                  }" data-page="${page.page_number}" data-bbox="${(placement.bbox || []).join(
                    ","
                  )}"`,
                }
              : null,
            { act: "copy-image-json", label: "Copy JSON", data: `data-index="${index}"` },
            placement.xref
              ? { act: "goto-xref", label: "Object", data: `data-xref="${placement.xref}"` }
              : null,
          ].filter(Boolean)
        )}
      </div>`;
    })
    .join("");

  return `
    <div class="card">
      <div class="card-head"><h2>Images — page ${page.page_number + 1}</h2>
        ${actionBar([
          { act: "download-doc-images", label: "Download all document images (zip)" },
          { act: "copy-json", label: "Copy page image JSON", data: `data-key="page.images"` },
        ])}
      </div>
      <p class="muted small">
        Thumbnails show ${
          imageViewMode === "page"
            ? "each image's region of the page, including text and graphics drawn over it"
            : "each image's own stored pixels, without anything the page draws over them"
        }.
        ${imageModeToggleHtml({ xref: 1, bbox: [0, 0, 1, 1] })}
      </p>
      <p class="muted small">
        Image XObjects are stored once per xref and reused for every placement; each placement
        keeps its own bbox and matrix.
      </p>
    </div>
    <div class="grid">${cards}</div>`;
}

/* ---------------------------------------------------------------- drawings */

/* Window controls for lists too long to inline: "showing a–b of n" with paging.
   `act` is the action prefix whose handler fetches the next window. */
function windowBarHtml(act, offset, returned, total, limit) {
  const first = returned ? offset + 1 : 0;
  const last = offset + returned;
  const known = typeof total === "number";
  const hasPrev = offset > 0;
  const hasNext = known ? last < total : returned >= limit;
  return `<p class="muted small window-bar">
    Showing ${first.toLocaleString()}–${last.toLocaleString()} of
    ${known ? total.toLocaleString() : "an unknown number of"} —
    ${limit.toLocaleString()} per window
    <button class="button small" data-act="${act}-first" ${hasPrev ? "" : "disabled"}>&laquo; first</button>
    <button class="button small" data-act="${act}-prev" ${hasPrev ? "" : "disabled"}>&lsaquo; previous</button>
    <button class="button small" data-act="${act}-next" ${hasNext ? "" : "disabled"}>next &rsaquo;</button>
  </p>`;
}

function drawingsHtml(page, doc) {
  const window = doc.drawingsWindow;
  const paths = (window && window.items) || page.drawings || [];
  const info = window || page.drawings_info || {};
  const total = info.total ?? paths.length;
  const offset = info.offset ?? 0;
  const limit = info.limit ?? paths.length;
  if (!total) return `<p class="muted">No vector graphics on page ${page.page_number + 1}.</p>`;
  return `
    <div class="card">
      <div class="card-head"><h2>Vector graphics (${Number(total).toLocaleString()})</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="page.drawings"` }])}
      </div>
      ${
        total > paths.length || offset > 0
          ? windowBarHtml("drawings", offset, paths.length, total, limit) +
            `<p class="muted small">This page holds more paths than any single report should
             carry, so they are read in windows. "Copy JSON" copies the window in view; the
             whole set is in the page report download.</p>`
          : ""
      }
      <table>
        <thead><tr><th>#</th><th>Type</th><th>Rect</th><th>Stroke</th><th>Fill</th><th>Width</th><th>Dashes</th><th>Items</th><th></th></tr></thead>
        <tbody>${paths
          .map(
            (path) => `<tr>
              <td>${path.index}</td>
              <td>${escapeHtml(path.type_label || path.type)}</td>
              <td class="mono small">${roundList(path.rect)}</td>
              <td class="mono small">${path.stroke ? escapeHtml(path.stroke.hex) : "—"}</td>
              <td class="mono small">${path.fill ? escapeHtml(path.fill.hex) : "—"}</td>
              <td>${path.width ?? "—"}</td>
              <td class="mono small">${escapeHtml(path.dashes || "—")}</td>
              <td>${(path.items || []).length}</td>
              <td>${actionBar([
                { act: "copy-drawing", label: "Copy", data: `data-index="${path.index}"` },
              ])}</td>
            </tr>`
          )
          .join("")}</tbody>
      </table>
    </div>`;
}

/* ------------------------------------------------------- annotations/forms */

function annotationsHtml(page) {
  const annots = page.annotations || [];
  const links = page.links || [];
  return `
    <div class="card">
      <div class="card-head"><h2>Annotations (${annots.length})</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="page.annotations"` }])}
      </div>
      ${
        annots.length
          ? `<table><thead><tr><th>#</th><th>Type</th><th>Rect</th><th>xref</th><th>Contents</th><th>Author</th><th>Flags</th></tr></thead>
            <tbody>${annots
              .map(
                (annot) => `<tr>
                  <td>${annot.index}</td>
                  <td>${escapeHtml(annot.type)}</td>
                  <td class="mono small">${roundList(annot.rect)}</td>
                  <td>${annot.xref}</td>
                  <td>${escapeHtml((annot.info || {}).content || "")}</td>
                  <td>${escapeHtml((annot.info || {}).title || "")}</td>
                  <td>${annot.flags}</td>
                </tr>`
              )
              .join("")}</tbody></table>`
          : `<p class="muted small">No annotations on this page.</p>`
      }
    </div>
    <div class="card">
      <div class="card-head"><h2>Links (${links.length})</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="page.links"` }])}
      </div>
      ${
        links.length
          ? `<table><thead><tr><th>#</th><th>Kind</th><th>Rect</th><th>Target</th></tr></thead>
            <tbody>${links
              .map(
                (link) => `<tr>
                  <td>${link.index}</td>
                  <td>${escapeHtml(link.kind)}</td>
                  <td class="mono small">${roundList(link.rect)}</td>
                  <td class="mono small">${escapeHtml(link.uri || (link.page != null ? `page ${link.page + 1}` : "—"))}</td>
                </tr>`
              )
              .join("")}</tbody></table>`
          : `<p class="muted small">No links on this page.</p>`
      }
    </div>`;
}

function formsHtml(report) {
  const form = report.form || {};
  const fields = form.fields || [];
  return `
    <div class="card">
      <div class="card-head"><h2>AcroForm</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="form"` }])}
      </div>
      <dl class="kv">
        <dt>Is form PDF</dt><dd>${form.is_form_pdf ? "yes" : "no"}</dd>
        <dt>AcroForm xref</dt><dd>${form.acroform_xref ?? "—"}</dd>
        <dt>SigFlags</dt><dd>${form.sig_flags}</dd>
      </dl>
      ${
        fields.length
          ? `<table><thead><tr><th>Page</th><th>Name</th><th>Type</th><th>Value</th><th>Rect</th><th>xref</th><th></th></tr></thead>
            <tbody>${fields
              .map(
                (field) => `<tr>
                  <td>${field.page != null ? field.page + 1 : "—"}</td>
                  <td class="mono">${escapeHtml(field.field_name || "")}</td>
                  <td>${escapeHtml(field.field_type_string || "")}</td>
                  <td class="mono">${escapeHtml(String(field.field_value ?? ""))}</td>
                  <td class="mono small">${roundList(field.rect)}</td>
                  <td>${field.xref ?? "—"}</td>
                  <td>${
                    field.xref
                      ? actionBar([{ act: "goto-xref", label: "Object", data: `data-xref="${field.xref}"` }])
                      : ""
                  }</td>
                </tr>`
              )
              .join("")}</tbody></table>`
          : `<p class="muted small">This document has no form fields.</p>`
      }
      <p class="muted small">
        Signature validation is out of scope: PyMuPDF reports signature widgets and /SigFlags,
        but does not verify signatures or decode certificate chains.
      </p>
    </div>`;
}

function attachmentsHtml(report) {
  const items = report.attachments || [];
  if (!items.length) return `<p class="muted">No embedded files.</p>`;
  return `
    <div class="card">
      <div class="card-head"><h2>Embedded files (${items.length})</h2>
        ${actionBar([{ act: "copy-json", label: "Copy JSON", data: `data-key="attachments"` }])}
      </div>
      <table>
        <thead><tr><th>Name</th><th>File name</th><th>Description</th><th>Size</th><th></th></tr></thead>
        <tbody>${items
          .map(
            (item) => `<tr>
              <td class="mono">${escapeHtml(item.name)}</td>
              <td class="mono">${escapeHtml(item.filename || "")}</td>
              <td>${escapeHtml(item.description || "")}</td>
              <td>${formatBytes(item.size)}</td>
              <td>${actionBar([
                { act: "download-attachment", label: "Download", data: `data-index="${item.index}"` },
              ])}</td>
            </tr>`
          )
          .join("")}</tbody>
      </table>
    </div>`;
}

/* ---------------------------------------------------------- content stream */

function streamHtml(page, doc) {
  const streams = page.content_streams;
  if (streams.error) return `<div class="notice">${escapeHtml(streams.error)}</div>`;
  const window = doc.operatorsWindow;
  const operators = (window && window.operators) || streams.operators || [];
  const offset = window ? window.offset : 0;
  const limit = (window && window.limit) || operators.length;
  /* The page report does not count the whole stream — that means lexing it all —
     so the total is only known once a window has been fetched. */
  const total = window ? window.total : streams.operators_truncated ? null : operators.length;
  return `
    <div class="card">
      <div class="card-head"><h2>Content stream — page ${page.page_number + 1}</h2>
        ${actionBar([
          { act: "copy-stream", label: "Copy decoded stream" },
          { act: "download-stream", label: "Download decoded" },
          { act: "download-stream-raw", label: "Download raw" },
          { act: "copy-json", label: "Copy operators JSON", data: `data-key="page.content_streams"` },
        ])}
      </div>
      <dl class="kv">
        <dt>Stream objects</dt><dd>${(streams.streams || [])
          .map((s) => `${s.xref}${s.filter ? ` (${escapeHtml(s.filter)})` : ""}`)
          .join(", ")}</dd>
        <dt>Decoded bytes</dt><dd>${streams.total_decoded_bytes}</dd>
        <dt>Operators</dt><dd>${
          total === null
            ? `${operators.length.toLocaleString()} shown — this stream holds more; page a window to count them all`
            : `${Number(total).toLocaleString()} in total`
        }</dd>
      </dl>
      ${
        streams.decoded_truncated
          ? `<div class="notice">The decoded stream shown below is truncated; use “Download decoded” for the whole stream.</div>`
          : ""
      }
      ${
        total === null || total > operators.length || offset > 0
          ? windowBarHtml("operators", offset, operators.length, total, limit)
          : ""
      }
      <details open><summary class="muted small">Decompiled operator listing</summary>
        <table>
          <thead><tr><th>#</th><th>Offset</th><th>Operator</th><th>Operands</th><th>Meaning</th></tr></thead>
          <tbody>${operators
            .map(
              (op, index) => `<tr>
                <td>${op.index ?? offset + index}</td>
                <td class="mono small">${op.offset}</td>
                <td class="mono">${escapeHtml(op.op)}</td>
                <td class="mono small">${escapeHtml(
                  (op.operands || []).map(formatOperand).join(" ")
                )}${op.inline_image ? ` [inline image, ${op.inline_image.data_bytes} bytes]` : ""}</td>
                <td class="muted small">${escapeHtml(op.description || "")}</td>
              </tr>`
            )
            .join("")}</tbody>
        </table>
      </details>
      <details><summary class="muted small">Raw decoded text</summary><pre>${escapeHtml(
        streams.decoded || ""
      )}</pre></details>
    </div>`;
}

function formatOperand(operand) {
  if (operand === null || operand === undefined) return "null";
  if (typeof operand === "object") {
    if ("name" in operand) return operand.name;
    if ("string" in operand) return `(${operand.string})`;
    if ("hex_string" in operand) return `<${operand.hex_string}>`;
    if ("array" in operand) return `[${operand.array.map(formatOperand).join(" ")}]`;
    if ("dict" in operand) return `<<${operand.dict.map(formatOperand).join(" ")}>>`;
  }
  return String(operand);
}

/* ------------------------------------------------------------ limitations */

function limitsHtml(report) {
  return `
    <div class="card">
      <h2>What this tool cannot extract</h2>
      <p class="muted small">
        Everything below exists in PDF files but is not reachable through PyMuPDF/MuPDF's API,
        or would need a different tool. It is listed here rather than silently omitted.
      </p>
      ${report.known_limitations
        .map(
          (item) =>
            `<h3>${escapeHtml(item.topic)}</h3><p class="small">${escapeHtml(item.detail)}</p>`
        )
        .join("")}
      ${
        report.warnings.length
          ? `<h3>Warnings for this document</h3>${report.warnings
              .map((warning) => `<div class="notice">${escapeHtml(warning)}</div>`)
              .join("")}`
          : ""
      }
    </div>`;
}

/* ----------------------------------------------------------------- actions */

function docUrl(suffix) {
  return `/api/documents/${state.selected}${suffix}`;
}

/* Windowed lists. The page report inlines only the first slice of the vector
   paths and of the operator listing, because CAD sheets carry hundreds of
   thousands of paths and millions of operators. Paging fetches the rest from the
   range endpoints, one window at a time. */
const LIST_WINDOW = { drawings: 2000, operators: 2000 };

function listWindowState(doc, kind) {
  return kind === "drawings" ? doc.drawingsWindow : doc.operatorsWindow;
}

function listWindowLength(doc, kind, page) {
  const current = listWindowState(doc, kind);
  if (current) return (kind === "drawings" ? current.items : current.operators).length;
  if (!page) return 0;
  return kind === "drawings"
    ? (page.drawings || []).length
    : ((page.content_streams || {}).operators || []).length;
}

async function fetchListWindow(doc, kind, direction) {
  const page = doc.pages.get(doc.pageIndex);
  const limit = LIST_WINDOW[kind];
  const current = listWindowState(doc, kind);
  const offset = current ? current.offset : 0;
  const shown = listWindowLength(doc, kind, page);

  let target = 0;
  if (direction === "prev") target = Math.max(0, offset - limit);
  else if (direction === "next") target = offset + shown;

  if (kind === "operators") toast("Counting the operators in this stream…");
  try {
    const data = await apiJson(
      docUrl(`/pages/${doc.pageIndex}/${kind}?offset=${target}&limit=${limit}`)
    );
    if (kind === "drawings") doc.drawingsWindow = data;
    else doc.operatorsWindow = data;
  } catch (error) {
    toast(error.message, true);
    return;
  }
  renderDocument();
}

function pathValue(root, path) {
  return path.split(".").reduce((value, key) => (value == null ? value : value[key]), root);
}

async function handleAction(act, target) {
  const doc = currentDoc();
  if (!doc) return;
  const page = doc.pages.get(doc.pageIndex);
  const pageIndex = doc.pageIndex;

  switch (act) {
    case "download-doc-json":
      download(docUrl("/report.json"));
      break;
    case "download-doc-text":
      download(docUrl("/text?fmt=txt"));
      break;
    case "download-doc-md":
      download(docUrl("/text?fmt=md"));
      break;
    case "download-doc-images":
      toast("Collecting images…");
      download(docUrl("/images.zip"));
      break;
    case "download-doc-bundle":
      toast("Building the complete export — this can take a while for large files");
      download(docUrl("/export.zip"));
      break;
    case "download-page-json":
      download(docUrl(`/pages/${pageIndex}/report.json`));
      break;
    case "download-page-text":
      download(docUrl(`/pages/${pageIndex}/text?fmt=txt`));
      break;
    case "download-page-md":
      download(docUrl(`/pages/${pageIndex}/text?fmt=md`));
      break;
    case "download-stream":
      download(docUrl(`/pages/${pageIndex}/content-stream`));
      break;
    case "download-stream-raw":
      download(docUrl(`/pages/${pageIndex}/content-stream?raw=true`));
      break;
    case "copy-page-text":
      if (page) copyText(page.text.plain, "Page text");
      break;
    case "copy-page-json":
      if (page) copyText(pretty(page), "Page JSON");
      break;
    case "copy-stream":
      if (page) copyText(page.content_streams.decoded || "", "Content stream");
      break;
    case "copy-trailer":
      copyText(doc.report.file.trailer || "", "Trailer");
      break;
    case "copy-xmp":
      copyText(doc.report.metadata.xmp.xml || "", "XMP");
      break;
    case "copy-json": {
      const key = target.dataset.key;
      const root = key.startsWith("page.") ? page : doc.report;
      const value = key.startsWith("page.")
        ? pathValue(page, key.slice(5))
        : pathValue(root, key);
      copyText(pretty(value), "JSON");
      break;
    }
    case "copy-block-text": {
      const block = page.text.structure.blocks.find(
        (item) => String(item.index) === target.dataset.block
      );
      const text = (block.lines || [])
        .map((line) => line.spans.map((span) => span.text).join(""))
        .join("\n");
      copyText(text, "Block text");
      break;
    }
    case "copy-drawing": {
      const pool = doc.drawingsWindow ? doc.drawingsWindow.items : page.drawings;
      copyText(
        pretty((pool || []).find((path) => String(path.index) === target.dataset.index)),
        "Path JSON"
      );
      break;
    }
    case "drawings-first":
    case "drawings-prev":
    case "drawings-next":
      await fetchListWindow(doc, "drawings", act.split("-")[1]);
      break;
    case "operators-first":
    case "operators-prev":
    case "operators-next":
      await fetchListWindow(doc, "operators", act.split("-")[1]);
      break;
    case "copy-image-json":
      copyText(pretty(page.images.placements[Number(target.dataset.index)]), "Image JSON");
      break;
    case "download-image":
      download(docUrl(`/images/${encodeURIComponent(target.dataset.file)}`));
      break;
    case "copy-image": {
      /* Copy goes through a PNG the server produced: the clipboard only takes
         PNG, the stored bytes may be a format the browser cannot decode, and an
         image without bytes of its own is copied as a region render. */
      const bbox = (target.dataset.bbox || "")
        .split(",")
        .filter((part) => part !== "")
        .map(Number);
      let url;
      if (target.dataset.xref) url = imagePreviewUrl(Number(target.dataset.xref));
      else if (target.dataset.file) url = storedImageUrl(target.dataset.file);
      else if (bbox.length === 4)
        url = regionPreviewUrl({ bbox }, Number(target.dataset.page || 0), 2000);
      if (url) copyImage(url, "Image");
      break;
    }
    case "download-region": {
      const bbox = (target.dataset.bbox || "")
        .split(",")
        .filter((part) => part !== "")
        .map(Number);
      if (bbox.length === 4) {
        download(regionPreviewUrl({ bbox }, Number(target.dataset.page || 0), 4000));
      }
      break;
    }
    case "download-attachment":
      download(docUrl(`/attachments/${target.dataset.index}`));
      break;
    case "goto-xref":
      await openObject(Number(target.dataset.xref));
      break;
    case "load-xref": {
      const input = el("xref-input");
      if (input && input.value) await openObject(Number(input.value));
      break;
    }
    case "copy-object":
      copyText(pretty(doc.object), "Object JSON");
      break;
    case "download-object-json":
      downloadBlob(
        pretty(doc.object),
        `${currentSummary().file_prefix}--xref${doc.object.xref}.json`,
        "application/json"
      );
      break;
    case "download-object-stream":
      download(docUrl(`/objects/${doc.object.xref}/stream`));
      break;
    case "download-object-stream-raw":
      download(docUrl(`/objects/${doc.object.xref}/stream?raw=true`));
      break;
    case "copy-element":
      copyText(pretty(doc.selectedElement.payload), "Element JSON");
      break;
    case "copy-element-text":
      copyText(doc.selectedElement.payload.text || "", "Text");
      break;
    case "download-element-image":
      download(docUrl(`/images/${encodeURIComponent(doc.selectedElement.payload.file)}`));
      break;
    case "copy-element-image":
      copyImage(
        doc.selectedElement.payload.xref
          ? imagePreviewUrl(doc.selectedElement.payload.xref)
          : docUrl(`/images/${encodeURIComponent(doc.selectedElement.payload.file)}`),
        "Image"
      );
      break;
    case "open-object":
      await openObject(Number(doc.selectedElement.payload.xref));
      break;
    default:
      break;
  }
}

async function openObject(xref) {
  const doc = currentDoc();
  if (!doc || !Number.isFinite(xref)) return;
  doc.tab = "objects";
  try {
    doc.object = await apiJson(docUrl(`/objects/${xref}`));
  } catch (error) {
    toast(error.message, true);
    return;
  }
  renderDocument();
}

/* ------------------------------------------------------------------ events */

el("file-input").addEventListener("change", async (event) => {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  event.target.value = "";
  toast(`Uploading ${files.length} file(s)…`);
  try {
    const result = await apiJson("/api/documents", { method: "POST", body: form });
    (result.rejected || []).forEach((item) =>
      toast(`${item.source_name}: ${item.error}`, true)
    );
  } catch (error) {
    toast(error.message, true);
  }
  refreshDocuments();
});

el("download-all").addEventListener("click", () => {
  toast("Building the export for every open document…");
  download("/api/export/all.zip");
});

el("document-list").addEventListener("click", async (event) => {
  const closeId = event.target.dataset.close;
  if (closeId) {
    event.stopPropagation();
    await api(`/api/documents/${closeId}`, { method: "DELETE" });
    state.docState.delete(closeId);
    if (state.selected === closeId) state.selected = null;
    await refreshDocuments();
    renderDocument();
    return;
  }
  const unlockId = event.target.dataset.unlock;
  if (unlockId) {
    event.stopPropagation();
    promptPassword(unlockId);
    return;
  }
  const item = event.target.closest(".document-item");
  if (!item) return;
  const documentId = item.dataset.doc;
  const summary = state.documents.find((d) => d.document_id === documentId);
  if (summary && summary.status === "needs_password") {
    promptPassword(documentId);
    return;
  }
  if (!state.docState.has(documentId)) {
    if (!summary || summary.status !== "ready") return;
    await loadDocumentReport(documentId);
  }
  selectDocument(documentId);
});

function promptPassword(documentId) {
  const summary = state.documents.find((d) => d.document_id === documentId);
  el("password-target").textContent = summary ? summary.source_name : documentId;
  const dialog = el("password-dialog");
  el("password-input").value = "";
  dialog.returnValue = "";
  dialog.showModal();
  dialog.addEventListener(
    "close",
    async () => {
      if (dialog.returnValue !== "ok") return;
      try {
        await apiJson(`/api/documents/${documentId}/unlock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: el("password-input").value }),
        });
        toast("Document unlocked");
      } catch (error) {
        toast(error.message, true);
      }
      await refreshDocuments();
    },
    { once: true }
  );
}

el("tabs").addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  const doc = currentDoc();
  if (!tab || !doc) return;
  doc.tab = tab.dataset.tab;
  renderDocument();
});

document.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-act]");
  if (actionButton) {
    handleAction(actionButton.dataset.act, actionButton);
    return;
  }
  const xrefButton = event.target.closest("[data-goto-xref]");
  if (xrefButton) {
    openObject(Number(xrefButton.dataset.gotoXref));
    return;
  }
  const treeNodeEl = event.target.closest(".tree .node[data-xref]");
  if (treeNodeEl) {
    openObject(Number(treeNodeEl.dataset.xref));
  }
});

/* Select one overlay box and show it in the details panel. */
function selectOverlayBox(box) {
  const doc = currentDoc();
  if (!doc || !box) return;
  const pageIndex = Number(box.dataset.page);
  const item = (doc.elementsByPage.get(pageIndex) || [])[Number(box.dataset.element)];
  if (!item) return;
  document.querySelectorAll(".box.selected").forEach((node) => node.classList.remove("selected"));
  box.classList.add("selected");
  doc.selectedElement = item;
  el("element-details").innerHTML = elementDetailsHtml(item, doc.pages.get(pageIndex));
}

function closeBoxPicker() {
  const existing = document.querySelector(".box-picker");
  if (existing) existing.remove();
}

/* Elements can sit exactly on top of each other — two revisions of the same
   drawing, or a stamp over a scan. Only the topmost box would ever receive the
   click, so when several are stacked the user gets to choose. */
function showBoxPicker(boxes, x, y) {
  closeBoxPicker();
  const doc = currentDoc();
  if (!doc) return;
  const picker = document.createElement("div");
  picker.className = "box-picker";
  picker.innerHTML =
    `<div class="head">${boxes.length} elements here — pick one</div>` +
    boxes
      .map((box, index) => {
        const item = (doc.elementsByPage.get(Number(box.dataset.page)) || [])[
          Number(box.dataset.element)
        ];
        if (!item) return "";
        return `<button data-pick="${index}"><span class="kind">${escapeHtml(
          item.kind
        )}</span><br />${escapeHtml(item.label)}</button>`;
      })
      .join("");
  document.body.appendChild(picker);
  picker.style.left = `${Math.min(x, window.innerWidth - picker.offsetWidth - 8)}px`;
  picker.style.top = `${Math.min(y, window.innerHeight - picker.offsetHeight - 8)}px`;

  picker.addEventListener("click", (event) => {
    const button = event.target.closest("[data-pick]");
    if (!button) return;
    selectOverlayBox(boxes[Number(button.dataset.pick)]);
    closeBoxPicker();
  });
}

/* Overlay boxes live in every loaded slot, so selection is delegated from the
   scroller and carries the page the box belongs to. */
el("page-canvas").addEventListener("click", (event) => {
  closeBoxPicker();
  const box = event.target.closest(".box");
  if (!box || !currentDoc()) return;
  const stacked = document
    .elementsFromPoint(event.clientX, event.clientY)
    .filter((node) => node.classList && node.classList.contains("box"));
  if (stacked.length > 1) {
    showBoxPicker(stacked, event.clientX + 6, event.clientY + 6);
    return;
  }
  selectOverlayBox(box);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeBoxPicker();
});

/* Clicking anywhere else dismisses the picker. */
document.addEventListener("click", (event) => {
  if (!event.target.closest(".box-picker") && !event.target.closest(".box")) closeBoxPicker();
});

/* Switching between stored pixels and the composited page region. */
function setImageViewMode(mode) {
  if (imageViewMode === mode) return;
  imageViewMode = mode;
  const doc = currentDoc();
  if (!doc) return;
  if (doc.tab === "images") {
    renderDocument();
    return;
  }
  if (doc.selectedElement && doc.selectedElement.kind === "image") {
    el("element-details").innerHTML = elementDetailsHtml(
      doc.selectedElement,
      doc.pages.get(doc.pageIndex)
    );
  }
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-image-mode]");
  if (button) setImageViewMode(button.dataset.imageMode);
});

/* Picking an image from the strip in the details panel: select its overlay box
   when one is on screen, otherwise just show its details. */
el("element-details").addEventListener("click", (event) => {
  const choice = event.target.closest("[data-choice]");
  const doc = currentDoc();
  if (!choice || !doc) return;
  const page = doc.pages.get(doc.pageIndex);
  if (!page) return;
  const placement = (page.images.placements || [])[Number(choice.dataset.choice)];
  if (!placement) return;

  const elements = doc.elementsByPage.get(doc.pageIndex) || [];
  const elementIndex = elements.findIndex(
    (item) => item.kind === "image" && item.payload === placement
  );
  const box = document.querySelector(
    `.page-slot[data-page="${doc.pageIndex}"] .box[data-element="${elementIndex}"]`
  );
  if (box) {
    selectOverlayBox(box);
    return;
  }
  /* The Images overlay may be switched off, or the page not loaded: show the
     details without an overlay selection. */
  const item = elements[elementIndex] || {
    kind: "image",
    label: PLACEMENT_LABEL(placement),
    bbox: placement.bbox,
    payload: placement,
  };
  doc.selectedElement = item;
  el("element-details").innerHTML = elementDetailsHtml(item, page);
});

/* Keep this document's scroll position so switching documents and coming back
   returns to the same place. */
el("page-canvas").addEventListener(
  "scroll",
  () => {
    const doc = currentDoc();
    if (!doc || pageView.documentId !== state.selected) return;
    if (pageView.scrollFrame) return;
    pageView.scrollFrame = requestAnimationFrame(() => {
      pageView.scrollFrame = null;
      doc.scrollTop = el("page-canvas").scrollTop;
    });
  },
  { passive: true }
);

el("overlay-toggles").addEventListener("change", (event) => {
  const doc = currentDoc();
  if (!doc || !event.target.dataset.toggle) return;
  doc.toggles[event.target.dataset.toggle] = event.target.checked;
  redrawOverlays(doc);
});

el("zoom").addEventListener("input", (event) => {
  const doc = currentDoc();
  if (!doc) return;
  doc.zoom = Number(event.target.value) / 100;
  el("zoom-label").textContent = `${Math.round(doc.zoom * 100)}%`;
  resizePageView(doc);
});

el("page-jump").addEventListener("change", (event) => {
  const doc = currentDoc();
  if (!doc) return;
  setCurrentPage(doc, Number(event.target.value) - 1, { scroll: true });
});

document.querySelector(".page-toolbar").addEventListener("click", (event) => {
  const doc = currentDoc();
  const action = event.target.dataset.action;
  if (!doc || !action) return;
  const total = doc.report.file.page_count;
  const targets = {
    "page-first": 0,
    "page-prev": doc.pageIndex - 1,
    "page-next": doc.pageIndex + 1,
    "page-last": total - 1,
  };
  if (!(action in targets)) return;
  setCurrentPage(doc, targets[action], { scroll: true });
});

/* Keyboard navigation while the page tab is open. Up/down and the wheel are
   left to the browser so ordinary scrolling keeps working. */
document.addEventListener("keydown", (event) => {
  const doc = currentDoc();
  if (!doc || doc.tab !== "page") return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  /* The image viewer owns the keyboard while it is open. */
  if (el("image-viewer").open) return;
  const tag = (event.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  const total = doc.report.file.page_count;
  const steps = {
    ArrowRight: doc.pageIndex + 1,
    PageDown: doc.pageIndex + 1,
    ArrowLeft: doc.pageIndex - 1,
    PageUp: doc.pageIndex - 1,
    Home: 0,
    End: total - 1,
  };
  if (!(event.key in steps)) return;
  event.preventDefault();
  setCurrentPage(doc, steps[event.key], { scroll: true });
});

document.querySelector(".document-actions").addEventListener("click", (event) => {
  const action = event.target.dataset.action;
  if (action) handleAction(action, event.target);
});

document.querySelector(".page-downloads").addEventListener("click", (event) => {
  const action = event.target.dataset.action;
  if (action) handleAction(action, event.target);
});

refreshDocuments();
setInterval(() => {
  if (!state.polling) refreshDocuments();
}, 5000);
