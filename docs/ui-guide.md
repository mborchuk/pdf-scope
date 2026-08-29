# User interface guide

The UI is a single page served at `/`. No build step, no external assets: one
HTML file, one CSS file, one JavaScript file, all in
`pdf_decompiler/web/static/`.

- [Layout](#layout)
- [Top bar](#top-bar)
- [Document sidebar](#document-sidebar)
- [Document header](#document-header)
- [Overview tab](#overview-tab)
- [Page tab](#page-tab)
- [Structure tab](#structure-tab)
- [Objects tab](#objects-tab)
- [Metadata tab](#metadata-tab)
- [Fonts tab](#fonts-tab)
- [Text tab](#text-tab)
- [Images tab](#images-tab)
- [Drawings tab](#drawings-tab)
- [Annotations tab](#annotations-tab)
- [Forms tab](#forms-tab)
- [Attachments tab](#attachments-tab)
- [Content stream tab](#content-stream-tab)
- [Not extractable tab](#not-extractable-tab)
- [View, copy, download](#view-copy-download)
- [Download file names](#download-file-names)
- [State kept per document](#state-kept-per-document)
- [Browser support and accessibility](#browser-support-and-accessibility)

## Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ PDF decompiler        [Open PDFs] [Download everything] pool status   │
├───────────────┬──────────────────────────────────────────────────────┤
│ Documents     │ file.pdf · PDF 1.7 · 4 pages · 11 KB · sha256 … · id  │
│ ┌───────────┐ │            [Document JSON] [.txt] [.md] [Images] […]  │
│ │ a.pdf     │ ├──────────────────────────────────────────────────────┤
│ │ ready   4 │ │ Overview │ Page │ Structure │ Objects │ Metadata │ …  │
│ ├───────────┤ ├──────────────────────────────────────────────────────┤
│ │ b.pdf     │ │  « ‹ 2 / 4 › »  [2] zoom ▓▓▓ ☑blocks ☐lines ☑images  │
│ │ analyzing │ │ ┌───────────────────────────┐ ┌────────────────────┐ │
│ └───────────┘ │ │  page 2 + overlays        │ │ element details    │ │
│               │ │ ─ ─ ─ scroll ─ ─ ─ ─ ─ ─ ─│ │ (follows the page  │
│               │ │  page 3 + overlays        │ │  in view)          │ │
│               │ └───────────────────────────┘ └────────────────────┘ │
└───────────────┴──────────────────────────────────────────────────────┘
```

## Top bar

| Control | What it does |
| --- | --- |
| **Open PDFs** | Multi-select file picker. All chosen files upload in one request and are analysed in parallel |
| **Download everything (all documents)** | One zip with a complete extraction of every document that is `ready`, one folder per document |
| Pool status | `N worker processes · M/25 documents open` — how much parallelism is available and how close you are to the limit |

## Document sidebar

One card per open document showing name, size, page count, status chip and
actions.

| Chip | Meaning |
| --- | --- |
| `queued` | Accepted, waiting for a worker |
| `reading document structure` | Document-level analysis running |
| `ready` | Report available; click the card to select it |
| `waiting for password` | Encrypted — click **Unlock** |
| `failed` | Could not be opened; the reason is printed in red on the card |
| `building export bundle` | A complete export is being produced for this document |

Extra lines appear when relevant: *"same bytes as another open document"* when
a file with an identical SHA-256 is already open.

| Action | Effect |
| --- | --- |
| Click the card | Select the document; the whole right side switches to it |
| **Unlock** | Password dialog; on success analysis reruns |
| **Close** | Removes the document and deletes every artifact belonging to it |

The list polls the server roughly once a second while anything is busy, then
settles to a five-second heartbeat.

## Document header

Shows PDF version, page count, file size, number of xref slots, encryption
state, the first 16 hex characters of the SHA-256, and the first 8 characters
of the document id — enough to tell two similar files apart at a glance.

| Button | Result |
| --- | --- |
| **Document JSON** | Downloads the document report |
| **Text (.txt)** | Whole-document plain text |
| **Text (.md)** | Whole-document text with `## Page N` sections |
| **Images (zip)** | Every image of every page, extracting pages first if needed |
| **Download everything** | The complete bundle for this document |

## Overview tab

The first tab, and the one a freshly opened document lands on: what this file is,
before looking at any page.

| Card | Contents |
| --- | --- |
| **File** | Name, size, PDF version, page count, the page sizes in use with how many pages have each, how many pages are rotated, SHA-256, document id |
| **Who made it** | Producer, creator, creation and modification dates, title, author, subject, keywords, language — with a reminder that these are the file's own claims, and the raw Info dictionary and XMP are in the Metadata tab |
| **Contents** | Characters, words, image placements, vector paths, tables detected, annotations, links, form fields, and how many pages have no text layer |
| **Structure and security** | Tagged or not, outline entries, fonts (and how many are embedded), attachments, form fields, optional-content groups, document JavaScript, encryption, repaired-on-open, fast web view, xref slots, object streams |
| **Warnings** | Anything the extractor wants to say about this specific file |
| **Pages** | One row per page: label, size, rotation, and once counted the characters, images, paths, tables and annotations on it, with **Open** to jump straight into the page view |

**How counting works.** Everything except the *Contents* card and the count columns
is already in the document report, so it appears instantly. Counting content means
touching every page: cheap on text pages, seconds on a CAD sheet. So counting
starts on its own in batches of 25 pages, stops after about 8 seconds, and offers
**Continue counting**; documents over 400 pages are only counted on request. The
counts fill in progressively, and the server keeps them for as long as the document
is open, so revisiting the tab is instant.

Table counts can be incomplete by design: on pages with more than 20 000 vector
paths detection is skipped, that page's cell reads *skipped*, and the card says the
total is partial.

## Page tab

Every page of the document is stacked in one continuous scroller, so a document
is read by scrolling exactly like in any PDF viewer. The toolbar buttons and the
page box are shortcuts that scroll the same container; there is no separate
"one page at a time" mode.

The page crossing the middle of the viewport is the **current page**. It drives
the `3 / 47` indicator, the page number box, the highlighted frame, the details
panel, and the page used by the *Text*, *Images*, *Drawings*, *Annotations* and
*Content stream* tabs.

### Lazy loading

Pages start as grey placeholders sized from the document report, so the
scrollbar is correct on a 600-page file without extracting anything. A page is
rendered, extracted and given an overlay shortly before it scrolls into view,
and is released again once it is a few pages behind — at most a handful of
bitmaps and page reports are held at any moment. Placeholders that fail to
render say so in red in place of the page.

### Toolbar

| Control | Notes |
| --- | --- |
| `«` `‹` `›` `»` | First / previous / next / last page — scrolls to that page |
| `3 / 47` indicator | Current page and page count |
| Page number box | Type a page and press Enter to scroll to it |
| **Zoom** slider | 50 %–300 %. The render request uses `dpi = 96 × zoom`, clamped to 400, while the overlay is laid out at `zoom` — so boxes stay aligned and the bitmap stays sharp. Zooming keeps the current page in view |
| Overlay checkboxes | One per element type, see below |
| **Page JSON** / **Page text** / **Copy page text** | Downloads and clipboard for the current page |

### Keyboard

| Key | Effect |
| --- | --- |
| `→` / `Page Down` | Next page |
| `←` / `Page Up` | Previous page |
| `Home` / `End` | First / last page |
| `↑` `↓`, wheel, trackpad, scrollbar | Ordinary scrolling, left to the browser |

Keys are ignored while a text field has focus, and while a tab other than
*Page* is open.

### Overlay colours

| Toggle | Colour | Default | Source of the boxes |
| --- | --- | --- | --- |
| Text blocks | blue | on | `text.structure.blocks[]` |
| Lines | green | off | `blocks[].lines[]` |
| Spans | amber | off | `lines[].spans[]` |
| Characters | purple | off | `spans[].chars[]` — dense on text-heavy pages |
| Images | orange | on | `images.placements[]` |
| Tables | green, dashed | on | `tables.items[]` — detected, not stored in the file. Selecting one shows its grid size, header cells and the table as Markdown, with **Copy table as Markdown** |
| Drawings | teal | off | `drawings[]` |
| Annotations | red | on | `annotations[]` |
| Links | violet | on | `links[]` |
| Form fields | yellow | on | `widgets[]` |

Hovering a box shows a tooltip with its label. Clicking selects it and fills
the details panel.

**Stacked elements.** PDFs routinely put one element exactly on top of another —
two revisions of the same drawing, a stamp over a scan, small icons over a
diagram. Only the topmost box could ever receive a click, so when several boxes
sit under the pointer a small chooser opens listing all of them by kind and
label; pick one to select it. `Esc`, or a click elsewhere, dismisses it.

### Details panel

With nothing selected it shows the summary of the page in view: page xref,
rotation, all five boxes, `page.rect`, the PDF-space rect, the PDF↔MuPDF matrix,
character count, and counts of images, drawings, annotations, links and form
fields. A page with no text layer says so here. Scrolling to another page
replaces the summary with that page's, which also clears the selection.

With an element selected it shows what is relevant to that kind:

| Kind | Extra fields |
| --- | --- |
| Span | font, size, colour, active font flags |
| Image | xref, stored pixel size, DPI, colourspace, bits per component, transparency mask, placement matrix, stored format, plus a thumbnail |
| Drawing | type, stroke and fill colours, width, dashes, number of path items |
| Annotation / widget | xref |

Buttons on the panel: **Copy element JSON**, **Copy text** (text elements),
**Download image** and **Copy image** (images), **Open xref N** (jumps to the
object browser). A collapsible **Raw JSON** section holds the element exactly
as the API returned it.

When the selected element is an image and the page holds more than one, the
panel also shows **Images on this page**: a strip of small previews, current one
highlighted. Clicking one selects that image, which is the reliable way to reach
an image hidden underneath another.

### Stored image vs as on page

A page is a composition. Text and vector graphics are drawn *over* images, so an
image's own pixels are often not what you see on the page — a map image can carry
no place names at all, because the names are page text painted on top of it.

Image previews therefore have two views, switched with the buttons above the
preview and repeated in the viewer's toolbar:

| View | Shows | Download gives |
| --- | --- | --- |
| **Stored image** (default) | Only the image's own pixels, as a PNG re-encode — exactly the content of the stored bytes | The original bytes, in the PDF's own format |
| **As on page** | That rectangle of the page, composited: the image plus every text and vector element drawn over it | That render, as PNG |

The choice applies to the details panel, the *Images* tab and the viewer, and it
stays until changed. Images with no bytes of their own only have the second view.

### Image viewer

Clicking any thumbnail — in the details panel or the Images tab — opens a viewer
that scales the image freely.

| Control | Effect |
| --- | --- |
| `−` / `+`, or `Ctrl`/`Cmd` + wheel | Zoom out / in in 25 % steps |
| **Fit**, or `0` | Whole image in the window, never enlarged past 100 % |
| **1:1**, or `1` | One image pixel per screen pixel |
| **Stored image** / **As on page** | Switch between the image's own pixels and the composited page region (shown only when both are possible) |
| **Download** | Original bytes for a stored image; the region PNG for a rendered one |
| **Copy** | The image on the clipboard as PNG |
| **Close**, or `Esc` | Back to the page |

Zoom is measured against the image's own pixels, so `100 %` means actual size.
Zooming in asks the server for a larger raster rather than stretching the small
one, up to the image's own resolution — past that there is nothing more to
fetch, and above 200 % smoothing is turned off so individual pixels are visible.
Page navigation keys are inert while the viewer is open.

## Structure tab

Cards, each with a **Copy JSON** button:

| Card | Content |
| --- | --- |
| **Catalog** | Every `/Root` entry as a clickable tree, plus the raw catalog source |
| **Page tree** | The `/Pages` walk with `/Count` and inherited MediaBox, CropBox, Resources, Rotate |
| **Structure tree (tagging)** | The `/StructTreeRoot` walk, or a notice that the document is not tagged |
| **Name trees** | `/Dests`, `/JavaScript`, `/EmbeddedFiles` and friends, with their entries |
| **Named destinations** | Resolved destination names |
| **Outline / table of contents** | Bookmarks with their target pages |
| **Object model summary** | xref slots, stream objects, object streams, cross-reference streams, fast web view, repaired-on-open, and the per-`/Type` histogram |
| **Trailer** | Trailer source and the document `/ID` pair |

Any tree node that carries an xref is clickable and opens it in the object
browser.

## Objects tab

The object browser. Type an xref number and press **Load**, or arrive by
clicking a reference anywhere else in the UI. **Catalog** jumps to `/Root`.

For the loaded object you get: type and subtype in the heading, the raw source,
stream sizes (raw and decoded), the decoded stream in a collapsible section,
and a row of buttons for every outgoing reference — `13 0 R` loads object 13.

| Button | Result |
| --- | --- |
| **Copy object** | The object description as JSON |
| **Download JSON** | The same, as a file |
| **Download stream** | The decoded stream bytes (stream objects only) |
| **Download raw stream** | The stored bytes, filters intact |

A stream that MuPDF cannot decode shows the reason instead of empty content.

## Metadata tab

| Card | Content |
| --- | --- |
| **Info dictionary** | Every key as stored |
| **File** | PDF version, pages, page mode and layout, language, `/MarkInfo`, page labels, SHA-256, PyMuPDF and MuPDF versions |
| **Encryption and permissions** | Encrypted or not, method, raw permission bits, and a yes/no table per operation |
| **XMP metadata** | The XMP packet with its object number, or a note that the document has none |
| **Document JavaScript** | Each script with its name and xref, shown as inert text |

## Fonts tab

One row per font: base name, subtype, embedded (with the font-file extension),
subset prefix, encoding, resource name, xref, and the pages it is used on. The
**Object** button opens the font dictionary, from which `/FontDescriptor` and
the embedded font program are one click away.

A note explains what is *not* decoded: glyph outlines, CMaps and `/ToUnicode`
mappings.

## Text tab

For the current page:

- the plain text, with a character and block count, or a notice when there is
  no text layer;
- a card per text block, and inside it a table per line listing each span with
  its text, font, size, colour, active flags, bbox and character count.

Buttons: **Copy page text**, **Download .txt**, **Download .md**, **Whole
document .txt**, **Copy page text JSON**, and **Copy block text** on each
block.

## Images tab

A card per placement on the current page with a thumbnail and the full record:
placement bbox, placement matrix, stored pixel size, DPI, colourspace, bits per
component, format, filters, SMask, stored size.

Every placement on the page gets its own card, including several placements of
the same xref and images that overlap each other, so nothing is hidden.

**Thumbnails are PNG re-encodes, downloads are not.** Images are stored in the
format the PDF used, and scanned files often use JPEG 2000, JBIG2 or CCITT,
which browsers cannot draw. Thumbnails therefore come from
`/images/{xref}/preview.png` while **Download** still gives the original bytes;
the *Format* row and the details panel say which format that is.

**Images with no bytes of their own** — inline images, and any image MuPDF cannot
tie to an xref — are previewed by rendering their rectangle of the page instead.
The details panel says so in its *Preview from* row, and the card offers
**Download region PNG** rather than **Download**, because there is no original
file to hand out.

| Button | Result |
| --- | --- |
| **Download** | The image in its original format, exactly as stored in the PDF |
| **Download region PNG** | For images with no extractable bytes: a high-resolution render of that region of the page |
| **Copy image** | Copies to the clipboard as PNG, going through the preview so JPEG 2000 and region-rendered images work too; if the browser blocks clipboard images, a toast says to use Download |
| **Copy JSON** | The placement record |
| **Object** | Opens the image XObject in the object browser |

Card header actions cover the whole document: **Download all document images
(zip)** and **Copy page image JSON**.

## Drawings tab

One row per vector path: index, type (fill / stroke / fill and stroke / clip),
bounding rect, stroke and fill colours, line width, dash pattern and the number
of path items, with **Copy** for the full path JSON including every coordinate.

**Long pages are read in windows.** CAD sheets routinely hold tens of thousands of
paths — 265 507 on one sheet in testing — so the heading states the real total and
a bar above the table shows which window is on screen
(*Showing 5 001–7 000 of 265 507*) with **first**, **previous** and **next**. The
index column is the path's position on the page, so it does not shift between
windows. Windows are 5 000 paths from the page report and 2 000 per fetch after
that; the whole set is in the page-report download.

## Annotations tab

Two tables: annotations (index, type, rect, xref, contents, author, flags) and
links (index, kind, rect, target URI or destination page), each with **Copy
JSON**.

## Forms tab

The AcroForm summary (is-form flag, AcroForm xref, `/SigFlags`) and a table of
every field in the document: page, name, type, value, rect, xref, and an
**Object** button. A note states that signature validation is out of scope.

## Attachments tab

Embedded files with name, file name, description and size, each with a
**Download** button.

## Content stream tab

The decompiled view of the current page:

- which stream objects make up the page and their filters;
- total decoded byte count and operator count;
- the operator listing — index, byte offset, operator, operands and a
  plain-English meaning — with inline images shown as
  `[inline image, N bytes]`;
- the raw decoded stream text in a collapsible section.

Buttons: **Copy decoded stream**, **Download decoded**, **Download raw**,
**Copy operators JSON**. When the inline copy is truncated the UI says so and
points at the download.

**Operator count and windows.** The page report carries the first 5 000 operators
and does not count the rest, because counting means lexing the whole stream. Until
a window is fetched the tab says *"5 000 shown — this stream holds more; page a
window to count them all"*; pressing **next** fetches a window and then the exact
total is known and displayed (*5 071 999 in total* on the heaviest sheet tested).
Counting a stream that long takes some seconds, so the fetch shows a toast while it
runs. The index column is the operator's position in the stream.

## Not extractable tab

The list of things that exist in PDF files but cannot be reached through
PyMuPDF, plus any warnings raised for this specific document (for example that
it is untagged). Same content as [coverage.md](coverage.md), rendered from the
document report so it can never drift from what the extractor actually does.

## View, copy, download

Every element type supports all three, with an honest fallback where a browser
refuses:

| Element | View | Copy | Download |
| --- | --- | --- | --- |
| Page text | Text tab, Page tab | Per span, block, page | `.txt`, `.md`, per page or whole document |
| Text element | Overlay + details panel | Element JSON, element text | Page JSON |
| Image | Thumbnail, details panel | PNG to clipboard (where supported), placement JSON | Original format, or all as zip |
| Drawing | Drawings tab, overlay | Path JSON with coordinates | Page JSON |
| Annotation / link / widget | Tabs and overlay | JSON | Page JSON |
| Object / dictionary | Objects tab | Object JSON | JSON, decoded stream, raw stream |
| Content stream | Content stream tab | Decoded text, operators JSON | Decoded, raw |
| Metadata | Metadata tab | Info JSON, XMP | Document JSON |
| Structure | Structure tab | Per-card JSON | Document JSON |
| Everything | — | — | Per document zip, or all documents zip |

Copy uses the asynchronous clipboard API and shows a toast on success. If the
browser blocks it (no user gesture, insecure context, permission denied) a
dialog opens with the content in a pre-selected textarea to copy by hand.
Image copy asks the server for the PNG preview of the image, because the
clipboard only accepts PNG and the stored bytes may be a format the browser
cannot decode at all; a canvas transcode still covers inline images. When the
clipboard itself is refused, the toast says to use Download instead.

## Download file names

Every download is prefixed with the source file name and the first eight
characters of the document id, so several open documents never collide:

| File | Example |
| --- | --- |
| Document report | `invoice_2024--905d4d6d--document.json` |
| Page report | `invoice_2024--905d4d6d--page0003.json` |
| Page text | `invoice_2024--905d4d6d--page0003.txt` |
| Content stream | `invoice_2024--905d4d6d--page0003--content-decoded.txt` |
| Object stream | `invoice_2024--905d4d6d--xref11-raw.bin` |
| Image | `invoice_2024--905d4d6d--image-xref11.png` |
| Attachment | `invoice_2024--905d4d6d--data.csv` |
| Bundle | `invoice_2024--905d4d6d--extraction.zip` |
| All documents | `pdf-decompiler-export.zip` |

The prefix is sanitised: only letters, digits, dot, underscore and hyphen
survive, truncated to 60 characters.

## State kept per document

Selecting another document and coming back preserves: scroll position in the
page scroller, current page, zoom, overlay toggles, active tab, the loaded
object in the browser, and the most recently fetched page reports (older ones
are dropped to keep memory bounded). State lives in the browser tab only —
reloading the page starts fresh, and the server keeps the documents themselves.

## Browser support and accessibility

- Any current Firefox, Chrome, Edge or Safari. `<dialog>` and the async
  clipboard API are the only modern features used, and both have fallbacks.
- No external fonts, scripts, styles or images: the page works fully offline.
- The interface is dark-themed with no light variant.
- The layout assumes a reasonably wide window; the sidebar and details panel
  are fixed-width, and narrow screens scroll horizontally.
- All text extracted from a PDF is HTML-escaped before display, and pages are
  shown as raster images, so a hostile document cannot inject markup or script
  into the UI.
