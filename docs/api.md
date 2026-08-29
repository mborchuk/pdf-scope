# HTTP API reference

Base URL: `http://127.0.0.1:8000` by default. Interactive documentation
generated from the code is served at `/docs`, the OpenAPI schema at
`/openapi.json`.

- [Conventions](#conventions)
- [Errors](#errors)
- [Document lifecycle](#document-lifecycle)
  - [POST /api/documents](#post-apidocuments)
  - [GET /api/documents](#get-apidocuments)
  - [GET /api/documents/{document_id}](#get-apidocumentsdocument_id)
  - [GET /api/documents/{document_id}/summary](#get-apidocumentsdocument_idsummary)
  - [POST /api/documents/{document_id}/unlock](#post-apidocumentsdocument_idunlock)
  - [DELETE /api/documents/{document_id}](#delete-apidocumentsdocument_id)
  - [GET /api/documents/{document_id}/report.json](#get-apidocumentsdocument_idreportjson)
- [Pages](#pages)
  - [GET /api/documents/{document_id}/pages/{page_number}](#get-apidocumentsdocument_idpagespage_number)
  - [GET .../pages/{page_number}/report.json](#get-pagespage_numberreportjson)
  - [GET .../pages/{page_number}/render.png](#get-pagespage_numberrenderpng)
  - [GET .../pages/{page_number}/drawings](#get-pagespage_numberdrawings)
  - [GET .../pages/{page_number}/operators](#get-pagespage_numberoperators)
  - [GET .../pages/{page_number}/text](#get-pagespage_numbertext)
  - [GET .../pages/{page_number}/content-stream](#get-pagespage_numbercontent-stream)
- [Objects](#objects)
  - [GET /api/documents/{document_id}/objects/{xref}](#get-apidocumentsdocument_idobjectsxref)
  - [GET .../objects/{xref}/stream](#get-objectsxrefstream)
- [Images and attachments](#images-and-attachments)
  - [GET .../images/{filename}](#get-imagesfilename)
  - [GET .../images/{xref}/preview.png](#get-imagesxrefpreviewpng)
  - [GET .../images.zip](#get-imageszip)
  - [GET .../attachments/{index}](#get-attachmentsindex)
- [Whole-document output](#whole-document-output)
  - [GET /api/documents/{document_id}/text](#get-apidocumentsdocument_idtext)
  - [GET /api/documents/{document_id}/export.zip](#get-apidocumentsdocument_idexportzip)
  - [GET /api/export/all.zip](#get-apiexportallzip)
- [Server status](#server-status)
- [Recipes](#recipes)

## Conventions

| | |
| --- | --- |
| Identifiers | `document_id` is a 32-character hex UUID from the upload response |
| Page numbers | Zero-based in every URL and JSON field |
| xrefs | 1 … `xref_length - 1`; object 0 is the free-list head |
| Content type | JSON responses are `application/json`; downloads carry `Content-Disposition: attachment` |
| Encoding | UTF-8 throughout; text extracted from PDFs is transcoded by MuPDF |
| Auth | None. The server is meant for `127.0.0.1` — see [SECURITY.md](../SECURITY.md) |
| CORS | Not enabled; the UI is served from the same origin |
| Caching | Renders and image responses send `Cache-Control: no-store` |

Download file names always identify the source: `<safe-source-stem>--<first 8
of document id>--<what it is>`, for example
`invoice_2024--905d4d6d--page0003.json`. That keeps several open documents
unambiguous in a downloads folder.

## Errors

Errors are FastAPI's standard shape:

```json
{ "detail": "unknown document id 0123456789abcdef0123456789abcdef" }
```

| Status | Meaning | Typical cause |
| --- | --- | --- |
| `400` | Malformed request | Missing multipart field |
| `401` | Password rejected | Wrong password on `/unlock` |
| `404` | Not found | Unknown document id, page, xref, image or attachment |
| `409` | Not ready | Document still `pending`/`analyzing`; or `all.zip` with nothing analysed |
| `422` | Unprocessable | Document failed to open; page, object, render or export failed |
| `423` | Locked | Document needs a password; call `/unlock` first |

Everything that depends on a document calls the same guard: unknown id → 404,
`needs_password` → 423, `error` → 422 with the recorded reason, any other
non-ready status → 409.

## Document lifecycle

### POST /api/documents

Upload one or more PDFs. Each becomes an independent document with its own id;
analysis starts immediately and runs in parallel.

| | |
| --- | --- |
| Body | `multipart/form-data` with one or more `files` parts |
| Success | `201 Created` |

```bash
curl -s -X POST http://127.0.0.1:8000/api/documents \
  -F "files=@invoice.pdf" \
  -F "files=@report.pdf"
```

```json
{
  "documents": [
    {
      "document_id": "905d4d6dbfcc47c8b6495bd00da07213",
      "source_name": "invoice.pdf",
      "size_bytes": 11416,
      "created_at": 1787939494.468,
      "status": "pending",
      "stage": "queued",
      "error": null,
      "page_count": null,
      "sha256": null,
      "duplicate_of": null,
      "file_prefix": "invoice--905d4d6d"
    }
  ],
  "rejected": []
}
```

`rejected` lists files that were not accepted at all, each with a reason:
oversized (see `PDF_DECOMPILER_MAX_UPLOAD_MB`) or the open-document limit
reached. A file that uploads fine but fails to parse is **not** rejected here —
it is created and later marked `status: "error"`.

Poll [`GET /api/documents`](#get-apidocuments) until each document leaves
`pending`/`analyzing`.

**Status values**

| `status` | Meaning | `stage` seen |
| --- | --- | --- |
| `pending` | Accepted, not started | `queued` |
| `analyzing` | Document-level extraction running | `reading document structure`, `building export bundle` |
| `ready` | Report available | `ready` |
| `needs_password` | Encrypted; call `/unlock` | `waiting for password` |
| `error` | Could not be opened; `error` holds the reason | `failed` |

### GET /api/documents

List every open document plus server limits and pool state.

```bash
curl -s http://127.0.0.1:8000/api/documents
```

```json
{
  "documents": [ { "document_id": "905d…", "status": "ready", "page_count": 4, "…": "…" } ],
  "limits": { "max_documents": 25, "max_upload_bytes": 536870912 },
  "pool": { "workers": 4, "running": 0, "started": true }
}
```

`duplicate_of` is set when another open document has the same SHA-256. Both
entries stay independent; nothing is merged.

### GET /api/documents/{document_id}

Summary plus the full document report.

```bash
curl -s http://127.0.0.1:8000/api/documents/905d4d6dbfcc47c8b6495bd00da07213
```

```json
{
  "document": { "document_id": "905d…", "status": "ready", "…": "…" },
  "report": { "schema_version": "1.0", "identity": {}, "file": {}, "…": {} }
}
```

`report` is `null` until the status is `ready`. Its full shape is documented in
[schema.md](schema.md#document-report).

### GET /api/documents/{document_id}/summary

How much of what is in the document: characters, words, image placements, vector
paths, detected tables, annotations, links and form fields, per page and in total.

The document report is cheap because it never touches page content. These counts
do touch every page, and a CAD sheet takes seconds on its own, so a request counts
one range of pages. Results are cached per page for the document's lifetime, and
`totals` and `pages` always cover **everything counted so far** — walk ranges until
`pages_counted` reaches `page_count`.

| Query | Type | Default | Range |
| --- | --- | --- | --- |
| `offset` | int | `0` | ≥ 0 |
| `limit` | int | `25` | 1–200 pages per request |
| `include_tables` | bool | `true` | `false` skips table detection, which is the slowest part |

```bash
curl -s "http://127.0.0.1:8000/api/documents/905d…/summary?offset=0&limit=25"
```

```json
{
  "page_count": 64, "offset": 0, "limit": 25, "pages_counted": 25,
  "complete": false, "pages_without_text_layer": 0,
  "totals": {"characters": 19819, "words": 2189, "images": 25, "drawings": 889,
             "tables": 24, "annotations": 0, "links": 0, "form_fields": 0},
  "partial_totals": [],
  "table_detection_path_guard": 20000,
  "pages": [{"page_number": 0, "characters": 251, "words": 30, "images": 1,
             "drawings": 2, "tables": 0, "annotations": 0, "links": 0,
             "form_fields": 0, "has_text_layer": true}]
}
```

`partial_totals` names the fields whose totals are incomplete because some page
could not supply them — in practice `tables`, on pages above
`table_detection_path_guard` vector paths, where detection is skipped and the
page's `tables` is `null` with `tables_skipped: true`.

### POST /api/documents/{document_id}/unlock

Retry an encrypted document with a password. The password is kept in memory for
the document's lifetime so page extraction can reopen the file; it is never
written to disk and never appears in any report or export.

```bash
curl -s -X POST \
  http://127.0.0.1:8000/api/documents/905d…/unlock \
  -H 'Content-Type: application/json' \
  -d '{"password":"secret"}'
```

| Status | Meaning |
| --- | --- |
| `200` | Unlocked; body is `{"document": {...}}` with `status: "ready"` |
| `401` | Password rejected |
| `404` | Unknown document |

Only the **user** password is needed. Permissions are reported, not enforced —
see [coverage.md](coverage.md#encryption).

### DELETE /api/documents/{document_id}

Close a document and delete its entire directory: source copy, extracted
images, page cache and export bundles.

```bash
curl -s -X DELETE http://127.0.0.1:8000/api/documents/905d…
```

```json
{ "closed": "905d4d6dbfcc47c8b6495bd00da07213" }
```

### GET /api/documents/{document_id}/report.json

The document report as a download (`Content-Disposition: attachment`, indented
JSON). Same content as the `report` field above.

## Pages

### GET /api/documents/{document_id}/pages/{page_number}

The full page report: page dictionary, resources, content stream with the
operator listing, text at every granularity, images, drawings, annotations,
links, widgets, xobjects and fonts.

The first request for a page runs the extraction in a worker and writes
`<workspace>/<id>/cache/page-NNNN.json`; later requests are served from that
cache. Extracted images are written to `<workspace>/<id>/images/` as a side
effect.

```bash
curl -s http://127.0.0.1:8000/api/documents/905d…/pages/0 | jq '.text.plain'
```

Shape: [schema.md](schema.md#page-report).

### GET .../pages/{page_number}/report.json

The same report as a download with an unambiguous file name
(`invoice--905d4d6d--page0001.json`).

### GET .../pages/{page_number}/render.png

Render the page, or one rectangle of it, to PNG.

| Query | Type | Default | Range |
| --- | --- | --- | --- |
| `dpi` | int | `120` | 24–400 (values outside are rejected by validation; the core additionally clamps to 24–400) |
| `clip` | `x0,y0,x1,y1` | whole page | Rectangle in PyMuPDF page points. Normalised, then clamped to `page.rect`. `422` if it is not four numbers or does not intersect the page |

`clip` is how the UI previews an image that has no bytes of its own — an inline
image, or one MuPDF cannot tie to an xref: the pixels come from rasterising that
region of the page. It is also a cheap way to get a detail of a page at high
resolution without rendering the whole sheet.

The response carries `X-Render-Info`, a JSON header with everything needed to
map points to pixels:

```
X-Render-Info: {"dpi":96,"zoom":1.3333333333333333,"pixel_width":794,
                "pixel_height":1123,"point_width":595.0,"point_height":842.0,
                "rotation":0,"origin":"top-left, matching all reported bounding boxes"}
```

Annotations are included in the render. Convert a reported bbox to pixels with:

```
pixel = (point − page.boxes.rect origin) × zoom
```

```bash
curl -s -D headers.txt -o page1.png \
  "http://127.0.0.1:8000/api/documents/905d…/pages/0/render.png?dpi=150"

# just one image's rectangle, at 200 dpi
curl -s -o detail.png \
  "http://127.0.0.1:8000/api/documents/905d…/pages/0/render.png?dpi=200&clip=454,515,548,676"
```

With `clip`, `X-Render-Info` additionally carries `clip` (the rectangle actually
used) and `page_point_size`.

### GET .../pages/{page_number}/drawings

A window of the page's vector paths, with the page's real total. The page report
inlines only the first 5 000 paths, because CAD sheets carry far more — 265 507 on
one sheet in testing, which is 746 MB of JSON if inlined.

| Query | Type | Default | Range |
| --- | --- | --- | --- |
| `offset` | int | `0` | ≥ 0. Beyond the last path returns an empty `items` |
| `limit` | int | `5000` | 1–5000 |

```json
{"items": [{"index": 264000, "type": "s", "rect": [...], "items": [...]}],
 "total": 265507, "offset": 264000, "limit": 50, "truncated": true,
 "page_number": 0}
```

`index` is the path's position on the page, not in the window, so it stays stable
however the page is walked. Same field shapes as
[`drawings`](schema.md#drawings) in the page report.

### GET .../pages/{page_number}/operators

A window of the decompiled operator listing, with the **exact** total. The whole
stream is lexed to count operators — one sheet in testing held 5 071 999 — but only
the window is materialised, so memory stays flat. Expect seconds, not
milliseconds, on such a page.

| Query | Type | Default | Range |
| --- | --- | --- | --- |
| `offset` | int | `0` | ≥ 0 |
| `limit` | int | `2000` | 1–20000 |

```json
{"operators": [{"index": 5000000, "op": "l", "offset": 53526090, "operands": [...]}],
 "operator_counts": {"l": 2987200, "m": 364361, "q": 358078},
 "total": 5071999, "offset": 5000000, "limit": 20, "returned": 20,
 "truncated": true, "bytes_parsed": 61093208, "bytes_total": 61093208,
 "page_number": 0}
```

`operator_counts` always covers the whole stream, not just the window.

### GET .../pages/{page_number}/text

Plain text of one page.

| Query | Values | Default |
| --- | --- | --- |
| `fmt` | `txt`, `md` | `txt` |

`md` wraps the text in a `## Page N` section and substitutes
`_(no text layer on this page)_` when the page has none.

### GET .../pages/{page_number}/content-stream

The page's content stream, concatenated across all `/Contents` streams.

| Query | Values | Default | Result |
| --- | --- | --- | --- |
| `raw` | `true`, `false` | `false` | `false` → MuPDF-decoded text; `true` → the still-encoded bytes as stored (Flate, LZW, …) |

Decoded output is `text/plain; charset=utf-8`; raw output is
`application/octet-stream`. Use this when the inline `content_streams.decoded`
field in the page report is truncated (over 200 000 characters).

## Objects

### GET /api/documents/{document_id}/objects/{xref}

Inspect any indirect object by number.

| Query | Values | Default | Meaning |
| --- | --- | --- | --- |
| `include_stream` | `true`, `false` | `true` | Include up to 200 000 characters of the decoded stream in `stream_decoded` |

```bash
curl -s http://127.0.0.1:8000/api/documents/905d…/objects/11
```

```json
{
  "xref": 11,
  "type": "/XObject",
  "subtype": "/Image",
  "is_stream": true,
  "source": "<<\n  /Type /XObject\n  /Subtype /Image\n  /Filter /FlateDecode\n  …>>",
  "entries": {
    "Type":   { "type": "name",  "value": "/XObject" },
    "Filter": { "type": "name",  "value": "/FlateDecode" },
    "ColorSpace": { "type": "xref", "value": "13 0 R", "xref": 13 }
  },
  "references": [13],
  "stream_raw_bytes": 14,
  "stream_decoded_bytes": 72
}
```

`references` lists every `N 0 R` found in the object source, which is what the
UI turns into clickable navigation. A `404` means the xref is outside
`1 … xref_length - 1`.

### GET .../objects/{xref}/stream

Download a stream object's bytes.

| Query | Values | Default | Result |
| --- | --- | --- | --- |
| `raw` | `true`, `false` | `false` | `false` → decoded by MuPDF; `true` → exactly as stored |

This is how to pull out an embedded font program, an ICC profile, an XMP
packet, or an image in its stored encoding.

## Images and attachments

### GET .../images/{filename}

Serve one extracted image file. Names come from the page report
(`images.placements[].file`, `images.objects[].file`):

| Pattern | Meaning |
| --- | --- |
| `image-xref<N>.<ext>` | Image XObject, stored once per xref |
| `image-inline-p<page>-<n>.<ext>` | Inline image, per occurrence |

Images exist only after the page that uses them has been extracted (or after
`images.zip`, which forces extraction of every page). Path traversal is
rejected.

The bytes are exactly what the PDF stored, in the PDF's own format. That is the
right thing for archiving, but not always something a browser can display —
see the preview endpoint below.

### GET .../images/{xref}/preview.png

The same pixels, decoded by MuPDF and re-encoded as PNG, for display in a
browser. Scanned documents commonly store pages as JPEG 2000 (`.jpx`/`.jp2`),
JBIG2 or CCITT; of those, only JPEG 2000 renders in Safari and none render in
Chrome, Firefox or Edge. The UI uses this endpoint for thumbnails and for
**Copy image**, and keeps the original bytes for **Download**.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `max_side` | `2000` | Longest side of the returned PNG, 16–8000. The image is only ever scaled down, never up |

Response headers carry `X-Image-Preview-Info`:

```
X-Image-Preview-Info: {"xref":126,"original_ext":"jpx","source_pixels":[1654,2338],
                       "preview_pixels":[1414,2000],"colorspace":"DeviceRGB",
                       "has_alpha":false,"max_side":2000}
```

`Cache-Control: no-store`, like page renders. CMYK and other spaces PNG cannot
express are converted to RGB first.

| Status | When |
| --- | --- |
| `404` | The xref does not exist, or exists but is not an image XObject |
| `422` | The image exists but MuPDF could not decode it, or it could not be encoded as PNG |

Inline images (`BI … ID … EI`) have no xref, so they have no preview; use the
stored file for those.

### GET .../images.zip

Extract every page's images if needed, then return them as one archive with
entries under `<file_prefix>/images/`.

### GET .../attachments/{index}

Download one embedded file (`/EmbeddedFiles`). `index` is the position in
`report.attachments`. The download name is
`<file_prefix>--<original filename>`.

## Whole-document output

### GET /api/documents/{document_id}/text

Text of the whole document.

| Query | Values | Default |
| --- | --- | --- |
| `fmt` | `txt`, `md` | `txt` |

`md` produces a title heading plus one `## Page N` section per page.

### GET /api/documents/{document_id}/export.zip

The complete extraction of one document, built on demand in a worker and
streamed from disk.

```
README.txt                     what each folder holds
document.json                  document report
pages/page-0001.json …         one report per page (failures become .error.txt)
text/page-0001.txt …           per-page plain text
text/document.txt              whole document text
text/document.md               whole document text as Markdown
content-streams/page-0001.txt  decoded content stream per page
images/…                       every extracted image in its original format
```

For a large document this takes a while before the download starts; the request
returns only when the bundle is complete.

### GET /api/export/all.zip

The same bundle for **every** document currently `ready`, one folder per
document named by its `file_prefix`. Returns `409` when no analysed document is
open. A document whose bundle fails contributes an `EXPORT-FAILED.txt` instead
of aborting the archive.

## Server status

### GET /api/status

```json
{
  "schema_version": "1.0",
  "documents_open": 3,
  "max_documents": 25,
  "workspace": "/home/you/pdf-decompiler/.workspace",
  "pool": { "workers": 4, "running": 0, "started": true }
}
```

Useful as a readiness probe: it answers as soon as the app has started.

## Recipes

**Upload, wait, dump every page report**

```bash
ID=$(curl -s -F "files=@book.pdf" localhost:8000/api/documents \
     | jq -r '.documents[0].document_id')
until [ "$(curl -s localhost:8000/api/documents/$ID | jq -r .document.status)" = ready ]; do
  sleep 0.5
done
N=$(curl -s localhost:8000/api/documents/$ID | jq -r .document.page_count)
for i in $(seq 0 $((N-1))); do
  curl -s "localhost:8000/api/documents/$ID/pages/$i" > "page-$i.json"
done
```

**Every font used, with the pages it appears on**

```bash
curl -s localhost:8000/api/documents/$ID \
  | jq -r '.report.fonts.items[] | "\(.base_font)\t\(.subtype)\tembedded=\(.embedded)\tpages=\(.used_on_pages|length)"'
```

**Find the operators that draw a page**

```bash
curl -s localhost:8000/api/documents/$ID/pages/0 \
  | jq -r '.content_streams.operators[] | "\(.op)\t\(.description // "")"'
```

**Pull an embedded font program out of the file**

```bash
# 1. find the font's /FontDescriptor, then its FontFile2 xref in the object view
curl -s "localhost:8000/api/documents/$ID/objects/42" | jq .entries
# 2. download the stream
curl -s -o font.ttf "localhost:8000/api/documents/$ID/objects/43/stream"
```

**Check whether a document has a text layer at all**

```bash
curl -s "localhost:8000/api/documents/$ID/pages/0" \
  | jq '{has_text: .text.has_text_layer, note: .text.note, images: (.images.placements|length)}'
```

**Clean up when finished**

```bash
curl -s -X DELETE localhost:8000/api/documents/$ID
```
