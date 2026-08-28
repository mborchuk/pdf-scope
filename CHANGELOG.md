# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The extraction result carries its own `schema_version`, versioned separately
from the application: see [docs/schema.md](docs/schema.md#versioning).

## [Unreleased]

### Added

- Page view is now a continuous scroller: all pages of a document are stacked
  and scrolled like in a normal PDF viewer, with lazy rendering so only the
  pages near the viewport are fetched, extracted and overlaid.
- Keyboard page navigation: `←`/`→`, `Page Up`/`Page Down`, `Home`, `End`.
- The page indicator shows `current / total`, and the page in view drives the
  details panel and the page-scoped tabs.
- Scroll position is kept per document, so switching documents and coming back
  returns to the same place.
- `GET /api/documents/{id}/images/{xref}/preview.png?max_side=` — the pixels of
  an image XObject re-encoded as PNG, with `X-Image-Preview-Info` describing what
  was decoded. Backed by `pdf_decompiler.core.image_preview_png`.
- New core error `ImageDecodeError` for images that exist but cannot be decoded.
- The image details panel now reports the stored format of an image.
- `render.png?clip=x0,y0,x1,y1` renders one rectangle of a page, and
  `render_page_png(..., clip=...)` does the same from Python. `X-Render-Info` then
  carries `clip` and `page_point_size`.
- Images with no extractable bytes (inline images, and any image MuPDF cannot tie
  to an xref) are now previewed by rendering their region of the page, and can be
  downloaded as **Download region PNG**.
- A chooser appears when several overlay boxes are stacked under the pointer, so
  an element hidden beneath another can be selected.
- The details panel lists every image on the page as a pickable strip when there
  is more than one.
- Image viewer: clicking any thumbnail opens a scalable preview with zoom in/out,
  fit, 1:1, `Ctrl`/`Cmd` + wheel, keyboard shortcuts, download and copy. Zooming
  in fetches a larger raster instead of stretching the thumbnail, and turns off
  smoothing above 200 %.

### Fixed

- Image thumbnails were blank for documents whose images are in a format
  browsers cannot display — JPEG 2000 scans in particular. Thumbnails and
  **Copy image** now use the PNG preview endpoint, **Download** still returns the
  original bytes, and an undecodable image shows a notice instead of a broken
  image icon.

- The application shell used `min-height` instead of `height`, so panels grew
  the window instead of scrolling inside their own area and the page area never
  became a scroll container.

## [0.1.0] — 2026-08-28

First public release. Extraction core plus web UI.

### Added

**Extraction core** (`pdf_decompiler.core`, no web dependency)

- Document analysis: identity (name, size, SHA-256), PDF version, page/chapter
  /version counts, trailer source and `/ID`, catalog xref, page mode and
  layout, `/MarkInfo`, language, page labels, repaired-on-open and fast web
  view flags.
- Object-model profiling: xref length, per-`/Type` histogram, stream-object
  count, object-stream and cross-reference-stream detection.
- Object access by xref: dictionary entries, raw source, stream raw/decoded
  sizes, decoded stream text and outgoing references.
- Page tree walk with inherited `/MediaBox`, `/CropBox`, `/Resources`,
  `/Rotate`.
- Structure tree (`/StructTreeRoot`) walk with tags, titles, `/Alt`,
  `/ActualText`, language and page links; `/RoleMap`, `/ClassMap`,
  `/ParentTree`.
- Name trees (`/Dests`, `/JavaScript`, `/EmbeddedFiles`, …), named
  destinations, outline/TOC with destinations, document-level JavaScript.
- Per page: all five boxes plus `page.rect`, `/Rotate`, transformation,
  rotation and derotation matrices, complete page dictionary, `/Resources`
  expanded per category for both direct and indirect dictionaries.
- Content streams: per-stream xref, filter and raw/decoded sizes, concatenated
  decoded stream, and an ordered operator listing produced by an in-repo PDF
  content-stream lexer, with operands, byte offsets, human-readable operator
  descriptions and inline-image (`BI … ID … EI`) handling.
- Text at page, block, line, span and character granularity with bounding
  boxes, font name and size, colour, alpha, ascender/descender, font flags
  (bold, italic, serifed, monospaced, superscript) and style flags.
- Images: bytes in the original format, dimensions, DPI, colourspace, bit
  depth, filters, SMask/transparency and xref; deduplicated per xref while
  every placement keeps its own bbox and matrix; inline images stored per
  occurrence.
- Vector graphics: paths with coordinates, stroke and fill colours, width,
  dash pattern, line cap/join, opacity and layer.
- Annotations of every type, links and AcroForm widgets with values.
- Embedded files, optional content groups and layer configurations, XMP
  metadata alongside the Info dictionary.
- Page rendering to PNG with the scale information needed to align overlays.
- Export bundles: complete extraction of a document as a zip, whole-document
  text as `.txt`/`.md`, and a combined JSON of document plus every page.
- Explicit `known_limitations` in every document report for everything that
  exists in PDF files but is not reachable through PyMuPDF.

**Web layer** (`pdf_decompiler.web`)

- FastAPI application with 19 endpoints covering documents, pages, objects,
  images, attachments, text and exports.
- Document registry with UUID identity, per-document artifact directories,
  duplicate detection by SHA-256, password unlock flow and full cleanup on
  close.
- `ProcessPoolExecutor`-based extraction pool with a concurrency cap, matching
  PyMuPDF's guidance against multi-threaded use.
- Page reports cached to disk per document.

**User interface** (`pdf_decompiler/web/static`)

- Multi-document sidebar with per-document status and progress.
- Page view with rendered page and per-element-type bounding-box overlays,
  zoom, element details on click.
- Structure explorer, object browser, and panels for metadata, fonts, text,
  images, drawings, annotations, forms, attachments, content stream and
  "not extractable".
- View / copy / download on every element, with a clipboard fallback and
  unambiguous download names across open documents.

**Project**

- Test suite with programmatically generated fixture PDFs, including a
  concurrency test that proves two documents are processed without
  cross-contamination.
- Ruff lint and format configuration.
- Documentation set under [`docs/`](docs/).

[Unreleased]: https://github.com/mv-borchuk/pdf-decompiler/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mv-borchuk/pdf-decompiler/releases/tag/v0.1.0
