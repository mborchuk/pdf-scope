# Core Python API

`pdf_decompiler.core` is the extraction engine. It has **no web-framework
dependency**: import it, point it at a file, get JSON-serialisable data back.
Everything the HTTP API returns is produced by these functions.

- [Install and import](#install-and-import)
- [Public surface](#public-surface)
- [Document analysis](#document-analysis)
- [Page analysis](#page-analysis)
- [Objects and structure](#objects-and-structure)
- [Content streams](#content-streams)
- [Text, images, drawings, annotations](#text-images-drawings-annotations)
- [Rendering](#rendering)
- [Exports](#exports)
- [Coordinates](#coordinates)
- [Serialisation](#serialisation)
- [Errors](#errors)
- [Concurrency rules](#concurrency-rules)
- [Worked examples](#worked-examples)

## Install and import

```bash
.venv/bin/pip install -r requirements.txt
```

```python
from pdf_decompiler.core import analyze_document, analyze_page, dumps
```

Only `pymupdf` and the standard library are needed for the core; FastAPI and
uvicorn are for the web layer.

## Public surface

Re-exported from `pdf_decompiler.core`:

| Name | Kind | Purpose |
| --- | --- | --- |
| `SCHEMA_VERSION` | `str` | Version of the report shape (`"1.0"`) |
| `analyze_document` | function | Document-level report |
| `analyze_page` | function | Full report for one page |
| `open_document` | function | Open and authenticate a file |
| `describe_object` | function | Describe one indirect object |
| `page_content_stream_bytes` | function | Whole content stream of a page |
| `render_page_png` | function | Render a page to PNG |
| `image_preview_png` | function | Decode one image XObject and re-encode it as PNG |
| `build_document_bundle` | function | Complete extraction as a zip |
| `collect_document_json` | function | Document plus every page report in one dict |
| `document_text` | function | Whole-document text as `.txt`/`.md` |
| `sha256_of_file` | function | File digest |
| `dumps` | function | JSON serialisation that understands PyMuPDF types |
| `PdfDecompilerError` and subclasses | exceptions | See [Errors](#errors) |

Submodules (`core.objects`, `core.text`, `core.images`, `core.drawings`,
`core.annotations`, `core.contentstream`, `core.coordinates`, `core.page`,
`core.document`) hold the building blocks and are stable enough to use
directly; they are documented below.

## Document analysis

```python
analyze_document(
    path: str | Path,
    *,
    password: str | None = None,
    document_id: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]
```

Opens the file, produces the document report described in
[schema.md](schema.md#document-report) and closes it again. Page **contents**
are not extracted — only cheap per-page summaries — so this stays fast on large
documents (a 300-page file takes well under a second).

| Argument | Meaning |
| --- | --- |
| `path` | Any file MuPDF can open; non-PDFs produce a warning and no object-level sections |
| `password` | User password for encrypted files |
| `document_id` | Copied into `identity.document_id`; use your own id when scripting |
| `source_name` | Overrides the file name in `identity.source_name` |

Raises `PasswordRequiredError` or `DocumentOpenError`.

```python
report = analyze_document("contract.pdf", password="hunter2")
print(report["file"]["pdf_version"], report["file"]["page_count"])
print(report["encryption"]["permissions"]["allowed"])
for font in report["fonts"]["items"]:
    print(font["base_font"], font["embedded"], font["used_on_pages"])
```

Helpers in the same module:

| Function | Purpose |
| --- | --- |
| `open_document(path, password=None) -> pymupdf.Document` | Open and authenticate; **you** must close the result |
| `decode_permissions(value: int) -> dict` | Turn a permission bitmask into named booleans |
| `page_transform_matrices(page) -> dict` | The four matrices for a page |
| `sha256_of_file(path) -> str` | Chunked digest |
| `KNOWN_LIMITATIONS` | The list embedded in every report |
| `FONT_SCAN_PAGE_LIMIT` | Pages scanned when aggregating fonts |

## Page analysis

```python
analyze_page(
    path: str | Path,
    page_number: int,                 # zero-based
    *,
    password: str | None = None,
    document_id: str | None = None,
    image_dir: str | Path | None = None,
    include_operators: bool = True,
) -> dict[str, Any]
```

Produces the page report from [schema.md](schema.md#page-report). It opens its
own `Document` and closes it, so it is safe to call from a worker process.

| Argument | Meaning |
| --- | --- |
| `image_dir` | Where extracted images are written. Omit to skip writing bytes; placements are still reported, with `file: null` |
| `include_operators` | Set `False` to skip the content-stream parse when you only need text or images |

Raises `PageNotFoundError` for an out-of-range page.

```python
page = analyze_page("contract.pdf", 2, image_dir="out/images")

for block in page["text"]["structure"]["blocks"]:
    if block["type"] != "text":
        continue
    for line in block["lines"]:
        for span in line["spans"]:
            print(f'{span["bbox"]} {span["font"]} {span["size"]:.1f} {span["text"]!r}')

for placement in page["images"]["placements"]:
    print(placement["xref"], placement["bbox"], placement["file"])
```

`core.page.content_streams(doc, page, *, inline_limit, operator_limit,
include_operators)` builds just the content-stream section if you have a
`Document` open already.

```python
page_content_stream_bytes(
    path, page_number, *, password=None, raw=False
) -> bytes
```

The complete content stream of a page: decoded (default) or exactly as stored
(`raw=True`). Use it when the inline copy in the report is truncated.

## Objects and structure

`pdf_decompiler.core.objects` works on an open `pymupdf.Document`.

| Function | Returns |
| --- | --- |
| `describe_object(doc, xref, *, include_stream=False, stream_limit=200_000)` | [Object description](schema.md#object-description) |
| `scan_xref_table(doc, *, limit=XREF_SCAN_LIMIT)` | Type histogram, stream counts, object/xref-stream detection |
| `page_tree(doc, *, node_limit=5_000)` | The `/Pages` tree with inherited attributes |
| `structure_tree(doc, *, node_limit=5_000)` | `/StructTreeRoot` walk, or `None` when untagged |
| `name_trees(doc, *, node_limit=5_000)` | Catalog `/Names` sub-trees with their entries |
| `collect_javascript(doc)` | Document-level JavaScript actions, streams resolved |
| `page_resources(doc, page)` | `/Resources` expanded per category |
| `key_value(doc, xref, path)` | Raw value of a dictionary entry; `path` may be nested (`"Resources/Font"`) |
| `resolve_reference(value)` | `"12 0 R"` → `12` |
| `find_references(source)` | Every reference in an object source, sorted |
| `parse_dict_source(source)` | `"<< /A 1 /B [2 3] >>"` → `[("A", "1"), ("B", "[2 3]")]` |

```python
from pdf_decompiler.core import open_document, describe_object
from pdf_decompiler.core.objects import find_references

doc = open_document("contract.pdf")
try:
    catalog = describe_object(doc, doc.pdf_catalog())
    print(catalog["entries"].keys())
    for xref in find_references(catalog["source"]):
        child = describe_object(doc, xref)
        print(xref, child["type"], child["subtype"])
finally:
    doc.close()
```

Walk limits exist so a hostile or enormous file cannot exhaust memory; when a
walk stops early the result carries `truncated: true`.

## Content streams

`pdf_decompiler.core.contentstream` is a self-contained PDF content-stream
lexer — no PyMuPDF involved, so it works on any decoded stream bytes.

```python
parse_content_stream(data: bytes, *, operator_limit: int | None = None) -> dict
```

Returns `{operators, operator_counts, truncated, bytes_parsed, bytes_total}`.
Operand values follow the shapes listed in
[schema.md](schema.md#content_streams). `OPERATOR_DESCRIPTIONS` maps operators
to plain-English descriptions.

```python
from pdf_decompiler.core import open_document
from pdf_decompiler.core.contentstream import parse_content_stream

doc = open_document("contract.pdf")
try:
    parsed = parse_content_stream(doc.load_page(0).read_contents())
finally:
    doc.close()

print(parsed["operator_counts"])
fonts_used = [op["operands"][0]["name"] for op in parsed["operators"] if op["op"] == "Tf"]
print(sorted(set(fonts_used)))
```

Inline images are consumed correctly: a `BI` entry carries
`inline_image.dictionary` and `inline_image.data_bytes`, and parsing resumes
after the matching `EI`.

## Text, images, drawings, annotations

Each takes an open `pymupdf.Page` (and `Document` where needed):

| Function | Module | Returns |
| --- | --- | --- |
| `extract_text(page)` | `core.text` | Every text granularity for the page |
| `page_text_markdown(page, page_number)` | `core.text` | One `## Page N` Markdown section |
| `decode_flags(value, table)` | `core.text` | Bitmask → named booleans (`FONT_FLAGS`, `CHAR_FLAGS`) |
| `color_to_rgb(value)` | `core.text` | MuPDF's packed sRGB int → `{int, hex, rgb, rgb_float}` |
| `extract_page_images(doc, page, output_dir=None)` | `core.images` | Placements, deduplicated objects, inline images |
| `extract_image_object(doc, xref, output_dir=None)` | `core.images` | One image XObject's bytes and properties |
| `extract_drawings(page)` | `core.drawings` | Vector paths with coordinates and paint state |
| `extract_annotations(page)` | `core.annotations` | Annotations with geometry and properties |
| `extract_links(page)` | `core.annotations` | Link annotations with targets |
| `extract_widgets(page)` | `core.annotations` | Form field widgets |

All of them fail soft: a single unreadable element yields an `error` entry
rather than an exception.

## Rendering

```python
render_page_png(
    path, page_number, *, dpi=120, password=None, annotations=True, clip=None
) -> tuple[bytes, dict]
```

Returns the PNG bytes and the scale information described in
[schema.md](schema.md#render-info). `dpi` is clamped to 24–400.

`clip` is an optional `(x0, y0, x1, y1)` in PyMuPDF page points: only that
rectangle is rasterised. It is normalised and clamped to `page.rect`, and raises
`ValueError` if it is not four numbers or falls entirely outside the page. Use it
to preview an image whose own bytes cannot be extracted, or to pull a detail of a
page at high resolution without rendering the whole sheet.

```python
png, info = render_page_png("contract.pdf", 0, dpi=150)
Path("page1.png").write_bytes(png)

# map a reported bbox onto the bitmap
zoom = info["zoom"]
x0, y0, x1, y1 = span["bbox"]
box_px = ((x0 - rect[0]) * zoom, (y0 - rect[1]) * zoom,
          (x1 - rect[0]) * zoom, (y1 - rect[1]) * zoom)
```

```python
image_preview_png(
    path, xref, *, password=None, max_side=None
) -> tuple[bytes, dict]
```

Decode one image XObject and re-encode it as PNG. Extracted image files keep the
format the PDF used — good for archiving, but JPEG 2000, JBIG2 and CCITT are
common in scans and no browser except Safari displays JPEG 2000 — so this gives
the same pixels in a form anything can read. `max_side` scales the longest side
down (never up); the default is 2000. CMYK is converted to RGB. Raises
`ObjectNotFoundError` if the xref is missing or is not an image, and
`ImageDecodeError` if MuPDF cannot decode it.

```python
png, info = image_preview_png("scan.pdf", 126, max_side=600)
info["original_ext"]     # 'jpx' — what the PDF actually stored
info["source_pixels"]    # [1654, 2338]
info["preview_pixels"]   # [424, 600]
```

## Exports

```python
build_document_bundle(
    source_path, output_zip, *, password=None, document_id=None,
    source_name=None, image_dir=None, progress=None
) -> Path
```

Writes the complete extraction to `output_zip` (layout in
[schema.md](schema.md#export-bundle-layout)), streaming entries so memory use
stays flat. `progress` is called as `progress(done, total)` per page.

```python
collect_document_json(
    source_path, *, password=None, document_id=None,
    source_name=None, image_dir=None
) -> dict
```

`{"document": <document report>, "pages": [<page report>, …]}` in memory. A
page that fails contributes `{"page_number": n, "error": "..."}`.

```python
document_text(source_path, *, password=None, fmt="txt", title=None) -> str
```

Whole-document text; `fmt="md"` adds a title and `## Page N` sections.

## Coordinates

`pdf_decompiler.core.coordinates`:

| Name | Purpose |
| --- | --- |
| `COORDINATE_SPACE_NOTE` | The description embedded in every report |
| `rect_to_list(rect)` | PyMuPDF `Rect` → `[x0, y0, x1, y1]` |
| `matrix_to_list(matrix)` | `Matrix` → `[a, b, c, d, e, f]` |
| `point_to_list(point)` | `Point` → `[x, y]` |
| `invert_matrix(matrix)` | Affine inverse, or `None` if singular |
| `apply_matrix_to_rect(rect, matrix)` | Transform and normalise a rectangle |
| `rect_to_pdf_space(rect, transformation_matrix)` | PyMuPDF space → PDF space |

```python
from pdf_decompiler.core.coordinates import rect_to_pdf_space

page = analyze_page("a4.pdf", 0)
matrix = page["page"]["transformation_matrix"]
print(rect_to_pdf_space([0, 0, 100, 100], matrix))   # [0.0, 742.0, 100.0, 842.0]
```

## Serialisation

```python
from pdf_decompiler.core import dumps
from pdf_decompiler.core.schema import jsonable

dumps(report)              # indented JSON text
dumps(report, indent=None) # compact
jsonable(pymupdf_value)    # Rect/Matrix/Point/bytes/dict/list → JSON-native
```

Reports are already JSON-native, so `json.dumps(report)` works too; `dumps` is
convenient when you mix in raw PyMuPDF values of your own.

## Errors

```
PdfDecompilerError
├── DocumentOpenError      file unreadable or not a document
├── PasswordRequiredError  encrypted and the password did not work
├── PageNotFoundError      page index out of range
└── ObjectNotFoundError    xref outside 1 … xref_length - 1
```

PyMuPDF exceptions never escape the core; failures inside a section become an
`error` field instead of an exception, so a single broken element does not lose
a whole report.

```python
from pdf_decompiler.core import analyze_document
from pdf_decompiler.core.errors import DocumentOpenError, PasswordRequiredError

try:
    report = analyze_document(path)
except PasswordRequiredError:
    report = analyze_document(path, password=ask_user())
except DocumentOpenError as exc:
    print(f"cannot open {path}: {exc}")
```

## Concurrency rules

PyMuPDF's documentation states it *"does not support running on multiple
threads"* and recommends `multiprocessing`. The core is written for that model:

1. Every top-level function opens its own `Document` and closes it in a
   `finally`.
2. No PyMuPDF object is returned across a process boundary — only paths, ints,
   strings, dicts and bytes, all picklable.
3. If you open a `Document` yourself with `open_document`, keep it inside one
   thread and close it.

```python
from concurrent.futures import ProcessPoolExecutor
from pdf_decompiler.core import analyze_document

files = ["a.pdf", "b.pdf", "c.pdf"]
with ProcessPoolExecutor(max_workers=4) as pool:
    for report in pool.map(analyze_document, files):
        print(report["identity"]["source_name"], report["file"]["page_count"])
```

## Worked examples

**Every image in a document, with placements, on disk**

```python
from pathlib import Path
from pdf_decompiler.core import analyze_document, analyze_page

out = Path("images"); out.mkdir(exist_ok=True)
report = analyze_document("catalogue.pdf")
for number in range(report["file"]["page_count"]):
    page = analyze_page("catalogue.pdf", number, image_dir=out)
    for placement in page["images"]["placements"]:
        print(number, placement["xref"], placement["bbox"], placement["file"])
```

**Fonts that are not embedded (a print-production check)**

```python
report = analyze_document("artwork.pdf")
missing = [f for f in report["fonts"]["items"] if not f["embedded"]]
for font in missing:
    print("not embedded:", font["base_font"], "pages", font["used_on_pages"])
```

**Which pages have no text layer (scan detection)**

```python
report = analyze_document("archive.pdf")
for number in range(report["file"]["page_count"]):
    page = analyze_page("archive.pdf", number, include_operators=False)
    if not page["text"]["has_text_layer"]:
        print("page", number + 1, "has no text:", page["text"]["note"])
```

**Dump one page's operators as a listing**

```python
page = analyze_page("form.pdf", 0)
for op in page["content_streams"]["operators"]:
    operands = " ".join(str(o) for o in op["operands"])
    print(f'{op["offset"]:>8}  {operands:<40} {op["op"]:<4} {op.get("description", "")}')
```

**Full extraction bundle from a script**

```python
from pdf_decompiler.core import build_document_bundle

build_document_bundle(
    "contract.pdf",
    "out/contract-extraction.zip",
    source_name="contract.pdf",
    image_dir="out/images",
    progress=lambda done, total: print(f"{done}/{total} pages"),
)
```
