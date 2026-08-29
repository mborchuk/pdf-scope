# Troubleshooting

Symptoms, causes and fixes. If nothing here matches, open an issue with the
information listed in [CONTRIBUTING.md](../CONTRIBUTING.md#reporting-bugs).

- [Install and startup](#install-and-startup)
- [Opening documents](#opening-documents)
- [Empty or wrong extraction](#empty-or-wrong-extraction)
- [Overlay and rendering](#overlay-and-rendering)
- [Copy and download](#copy-and-download)
- [Performance](#performance)
- [Multi-document oddities](#multi-document-oddities)
- [API errors](#api-errors)
- [Diagnosing a document from the shell](#diagnosing-a-document-from-the-shell)

## Install and startup

**`ModuleNotFoundError: No module named 'pymupdf'`**
The virtual environment is not active or the dependencies are not installed.
Use the interpreter inside it explicitly:

```bash
.venv/bin/pip install -r requirements.txt && .venv/bin/python -m pdf_decompiler
```

**`ERROR: Could not find a version that satisfies the requirement pymupdf==1.28.2`**
Your Python is older than 3.10, or the platform has no wheel. Check with
`python3 --version`. On unusual platforms PyMuPDF may need to build from
source, which requires a C/C++ toolchain.

**`[Errno 48] Address already in use`**
Another process holds the port. Use `--port 8001`, or find the holder with
`lsof -i :8000`.

**The server starts but `/` is blank or 404**
The static files are missing from the package. Reinstall from a complete
checkout; `pdf_decompiler/web/static/` must contain `index.html`, `app.js` and
`style.css`.

**Startup deleted files I had in the working directory**
The workspace directory is emptied on every start. If you pointed
`PDF_DECOMPILER_WORKSPACE` at a directory holding other data, that is the
cause. Always give it a directory of its own.

## Opening documents

**A document sits at `queued` forever**
The process pool did not start, or every worker is busy with something large.
Check `GET /api/status`: `pool.started` must be `true`, and `pool.running`
shows work in flight. On restricted systems where `multiprocessing` cannot
spawn processes, the server log shows the failure.

**`failed` with "Failed to open file … as type pdf"**
MuPDF could not parse the file at all. It may be truncated, not a PDF, or
encrypted with an unsupported scheme. Confirm with:

```bash
head -c 8 suspect.pdf   # should start with %PDF-1.x
```

**`waiting for password` although I know the password**
Use the **user** password, not the owner password, and check for a leading or
trailing space. A wrong password returns 401 from `/unlock` and the document
stays locked.

**"same bytes as another open document"**
Informational only: another open document has the same SHA-256. Both remain
fully independent.

**Upload rejected: "limit of 25 open documents reached"**
Close some documents. Every close deletes that document's artifacts.

**Upload rejected: "file exceeds the 512 MB limit"**
Raise `PDF_DECOMPILER_MAX_UPLOAD_MB` and restart, and raise the body-size limit
in any reverse proxy in front.

**The document opened but `is_repaired` is true**
MuPDF had to rebuild the cross-reference table. The file is damaged; object
numbers may not match what other tools report, and some objects may be missing.
Extraction still works on whatever survived.

## Empty or wrong extraction

**No text at all, `has_text_layer: false`**
The page has no text operators — almost always a scan. `text.note` says so.
There is no OCR in this tool; run OCR elsewhere first if you need the text.

**Text extracts as mojibake or `??????`**
The font has no usable `/ToUnicode` CMap, so the character codes cannot be
mapped to Unicode. Check `fonts.items[].to_unicode_xref`: `null` explains it.
The glyphs render correctly because drawing does not need Unicode. Nothing can
be done without heuristics or OCR.

**Text order looks scrambled**
Extraction follows MuPDF's block order, which follows the content stream.
Multi-column layouts, tables and figures often interleave. The structure tree
(if the document is tagged) is the only authoritative reading order; the
**Structure** tab shows whether one exists.

**Spans split in odd places**
A span breaks whenever the font, size, colour or style changes, and MuPDF also
splits on large positioning jumps. Join spans within a line to reconstruct
sentences.

**A font is listed that I cannot see on the page**
Resources may include fonts that are never actually drawn, especially after
editing. `used_on_pages` reflects the resource dictionary, not the operators.
The **Content stream** tab shows which fonts are really selected with `Tf`.

**An image has DPI 96 everywhere**
96 is MuPDF's fallback when the image carries no resolution information. The
meaningful number is the ratio between stored pixels and the placement
rectangle, both of which are reported.

**`images.placements` is empty but I can see pictures**
The page may draw a form XObject that contains the image, or the "image" may be
vector art. Check the **Drawings** tab and the operator listing for `Do`.

**`decode_error` on a stream**
MuPDF refused that filter chain, or the stream is damaged. The raw bytes are
still downloadable with `?raw=true`.

**Structure tree missing**
Most PDFs are not tagged. The document report says so in `warnings` and the
**Structure** tab shows a notice. There is nothing to recover; the information
was never in the file.

## Overlay and rendering

**Boxes are offset from the content**
Check that `page.boxes.rect` does not start at `(0, 0)` — a CropBox with a
non-zero origin must be subtracted before scaling. The UI does this; a custom
client must too:
`pixel = (point − rect_origin) × zoom`.

**Boxes are offset only on rotated pages**
Use `page.rect`, not `/MediaBox`, as the frame. `page.rect` already has
`/Rotate` applied, and so does the render. Reported bounding boxes are in that
same space.

**The render is blurry at high zoom**
Raster resolution is `dpi = 96 × zoom`, capped at 400. Beyond that the bitmap
is upscaled by the browser. The cap keeps memory bounded — a 400 dpi A4 page is
already ~3300 × 4700 pixels.

**The Overview tab shows no content counts, or says the total is partial**
Counting reads every page, so it runs in batches and pauses after about 8 seconds;
press **Continue counting**. Documents over 400 pages are only counted on request.
A partial `tables` total means detection was skipped on at least one page — that
happens above 20 000 vector paths, where it would take tens of seconds; those pages
show *skipped* in the table column.

**A table I can see is not detected, or one I cannot see is**
PDF has no table object. Tables are reconstructed from ruling lines and text
alignment, so a borderless table with irregular spacing can be missed, and a ruled
form or a title block can be reported as a table — one CAD sheet in testing yielded
a 12 × 2 "table" that is really the drawing's title block. Treat row and column
counts as an interpretation; the *Text* tab shows what is actually on the page.

**The drawings list or the operator listing stops before the end**
Both are read in windows. A CAD sheet can hold hundreds of thousands of paths and
millions of operators, so a page report inlines the first 5 000 of each and the tab
shows *Showing a–b of n* with **first / previous / next**. Nothing is unreachable:
`GET .../pages/{n}/drawings?offset=&limit=` and `.../operators?offset=&limit=` walk
the whole page, and the page-report download contains the complete set. The
operator total appears only after the first window is fetched, because counting
requires lexing the whole stream.

**A CAD page takes ten seconds or more to open**
That is the extraction, not the UI. The heaviest sheet tested — 265 507 vector
paths — needs about 11 s for its page report and about 16 s to count its 5 071 999
operators. Both are cached afterwards (the page report on disk, the operator window
in the tab). The page render itself is fast, so scrolling stays responsive while the
report is still being built.

**The preview does not show what I can see on the page**
Images are only one layer. Text and vector graphics are drawn over them, so an
image's own pixels often lack what the page shows: a map image typically has no
place names, because the names are page text on top of it. Switch the preview to
**As on page** to see the composited region, and back to **Stored image** for the
bytes themselves. If the thing you are looking for appears in neither, it is not
an image at all — turn on the *Drawings* overlay, or open the *Drawings* and
*Text* tabs. Road signs, arrows, frames and logos are frequently vector paths.

**The page clearly holds two images on top of each other, but only one can be selected**
Clicking the page can only reach the topmost box. When boxes are stacked a
chooser lists every element under the pointer — pick the one you want. The
details panel also shows an **Images on this page** strip when a page holds more
than one image, and the *Images* tab always lists every placement separately.

**A page shows several images but only one has a preview**
Inline images (`BI … ID … EI`) and images MuPDF cannot tie to an xref have no
extractable bytes, so there is nothing to serve as a file. Those are previewed by
rendering their rectangle of the page instead
(`render.png?clip=x0,y0,x1,y1`), which the details panel reports in its *Preview
from* row. If an image has neither bytes nor a bounding box, the panel says so
rather than showing an empty frame.

**An image thumbnail is blank, or says the format cannot be displayed**
Check the *Format* row on the image card. Scanned documents often store pages as
JPEG 2000 (`jpx`/`jp2`), JBIG2 or CCITT, and browsers cannot draw those — only
Safari handles JPEG 2000 at all. Thumbnails and **Copy image** therefore use
`/images/{xref}/preview.png`, which decodes through MuPDF and returns PNG. If
even that fails you get a notice and a `422` with the decoder's reason; the
original bytes are still correct and **Download** will give you a file that
opens in Preview, GIMP or Photoshop. Inline images have no xref, so they have no
preview and fall back to the stored bytes. The rendered page is never affected —
it is rasterised server-side.

**Pages stay grey while scrolling**
Placeholders are shown until a page's render arrives, and pages are only
requested when they come close to the viewport. Scroll more slowly, or use the
page box or `Home`/`End` to jump: the target page is then loaded directly. A
placeholder that turns red carries the reason that page could not be rendered.

**The page area is huge or tiny**
Non-standard page sizes are reported faithfully. Check `page.boxes.mediabox`
against `cropbox`: a giant MediaBox with a small CropBox is common in
print-production files.

**The browser becomes sluggish with overlays on**
Turn off *Characters*, and *Spans* on dense pages. Each box is a DOM node; a
text-heavy page can have tens of thousands of characters.

## Copy and download

**"Browser blocked image copy — use Download instead"**
The clipboard image API needs a secure context and browser support. Firefox in
particular restricts writing images. Use **Download**; the file is identical.

**Copy opens a textarea dialog instead of copying**
`navigator.clipboard.writeText` was refused — usually an insecure context
(`http://` on a non-localhost host) or a missing user gesture. The textarea is
the fallback; select and copy manually. Access the app via `127.0.0.1` rather
than a LAN IP to keep the secure-context exemption.

**A download starts but the file is tiny or empty**
Check the response: an error is returned as JSON with a `detail` field.
`GET /api/documents/{id}` will show whether the document is still `analyzing`.

**"Download everything" seems to hang**
The bundle is built before the download starts: every page is extracted and
compressed. For a several-hundred-page document this takes a while. The
document's sidebar chip reads *building export bundle* meanwhile.

**Images are missing from `images.zip`**
The endpoint extracts every page first, so they should all be there. An image
that PyMuPDF could not decode is reported with an `error` in the page report
and has no file.

## Performance

**Opening a huge document is slow**
Document analysis scans every object once. A file with hundreds of thousands of
objects will take seconds; `file.xref.scan_truncated` tells you when the scan
limit was hit.

**One page takes seconds to extract**
Usually thousands of vector paths, or a very large image. Try
`include_operators=False` when using the core directly if you only need text.

**Everything is slow when several documents are analysed**
The pool is saturated. Raise `PDF_DECOMPILER_WORKERS` if you have spare cores;
`pool.running` in `/api/status` shows the current load.

## Multi-document oddities

**Documents disappeared after a restart**
By design: the registry is in memory and the workspace is emptied on start.
Re-upload.

**Two entries for the same file**
Also by design: each upload is independent. The second is marked
`duplicate_of`.

**A download from document A appeared to contain document B's data**
That would be a bug — please report it. Every download name carries the source
stem and the document id prefix; check the file name first, since two similar
documents are easy to confuse.

## API errors

| Status | Meaning | Fix |
| --- | --- | --- |
| `401` | Password rejected | Use the user password |
| `404` | Unknown document, page, xref, image or attachment | Refresh the document list; ids do not survive a restart |
| `409` | Document still `pending`/`analyzing`, or `all.zip` with nothing ready | Poll `GET /api/documents` and retry |
| `422` | Document failed to open, or a page/object/render/export failed | Read `detail`; the document's `error` field has the original reason |
| `423` | Document is locked | `POST /unlock` |

## Diagnosing a document from the shell

Work directly with the core when the UI is not the fastest route:

```bash
.venv/bin/python - <<'PY'
from pdf_decompiler.core import analyze_document, analyze_page

report = analyze_document("suspect.pdf")
print("version:", report["file"]["pdf_version"])
print("repaired:", report["file"]["is_repaired"])
print("encrypted:", report["encryption"])
print("objects:", report["file"]["xref"]["type_counts"])
print("tagged:", report["structure"]["struct_tree_root"] is not None)
print("warnings:", report["warnings"])

page = analyze_page("suspect.pdf", 0)
print("text layer:", page["text"]["has_text_layer"], page["text"]["note"])
print("operators:", page["content_streams"]["operator_counts"])
print("images:", [p["xref"] for p in page["images"]["placements"]])
PY
```

Compare against MuPDF's own tooling if you suspect the extractor rather than
the file:

```bash
.venv/bin/python -c "import pymupdf; d=pymupdf.open('suspect.pdf'); print(d.page_count, d.metadata)"
```
