# Extraction schema reference

Every field produced by the extraction core, with its type and meaning.
Two documents are described: the **document report**
(`analyze_document` / `GET /api/documents/{id}`) and the **page report**
(`analyze_page` / `GET /api/documents/{id}/pages/{n}`).

- [Versioning](#versioning)
- [Ground rules](#ground-rules)
- [Document report](#document-report)
  - [identity](#identity)
  - [extractor](#extractor)
  - [coordinate_space](#coordinate_space)
  - [file](#file)
  - [file.xref](#filexref)
  - [encryption](#encryption)
  - [metadata](#metadata)
  - [structure](#structure)
  - [fonts](#fonts)
  - [attachments](#attachments)
  - [form](#form)
  - [optional_content](#optional_content)
  - [javascript](#javascript)
  - [pages (summaries)](#pages-summaries)
  - [known_limitations and warnings](#known_limitations-and-warnings)
- [Page report](#page-report)
  - [page](#page)
  - [resources](#resources)
  - [content_streams](#content_streams)
  - [text](#text)
  - [images](#images)
  - [drawings](#drawings)
  - [annotations](#annotations)
  - [links](#links)
  - [widgets](#widgets)
  - [xobjects and fonts](#xobjects-and-fonts)
- [Object description](#object-description)
- [Render info](#render-info)
- [Export bundle layout](#export-bundle-layout)
- [Truncation and limits](#truncation-and-limits)
- [Error fields](#error-fields)

## Versioning

Both reports carry `schema_version`, currently **`"1.0"`**. It is independent
of the application version.

- Adding a key, or adding a value to an existing enumerated field, is a
  **minor** change and does not bump the version.
- Removing or renaming a key, or changing the type or meaning of an existing
  one, bumps the version.

Consumers should ignore unknown keys.

## Ground rules

| Rule | Detail |
| --- | --- |
| JSON-native only | Every value is `null`, boolean, number, string, array or object. `core.schema.jsonable()` converts PyMuPDF types |
| Rectangles | `[x0, y0, x1, y1]` floats, PDF points, PyMuPDF space (top-left origin, y down) |
| Matrices | `[a, b, c, d, e, f]`; a point maps to `(a·x + c·y + e, b·x + d·y + f)` |
| Points | `[x, y]` |
| Page numbers | Zero-based |
| Raw PDF syntax | Strings such as `"5 0 R"`, `"/DeviceRGB"`, `"<</A 1>>"` are reproduced verbatim from the file |
| Binary payloads | Never inline. Images are written to disk and referenced by `file`; streams are downloaded through the API |
| Missing vs absent | A key that could not be produced is `null` or carries a sibling `error` string; features absent from the PDF are reported as empty structures |

## Document report

```jsonc
{
  "schema_version": "1.0",
  "identity": {}, "extractor": {}, "coordinate_space": {},
  "file": {}, "encryption": {}, "metadata": {}, "structure": {},
  "fonts": {}, "attachments": [], "form": {}, "optional_content": {},
  "javascript": [], "pages": [],
  "known_limitations": [], "warnings": []
}
```

### identity

| Field | Type | Meaning |
| --- | --- | --- |
| `document_id` | string \| null | The server's UUID for this open document; `null` when the core is used directly without one |
| `source_name` | string | Original file name as uploaded |
| `source_size_bytes` | int | Size of the file on disk |
| `sha256` | string | Hex SHA-256 of the file bytes; used to detect the same file opened twice |

### extractor

| Field | Type | Meaning |
| --- | --- | --- |
| `library` | string | Always `"PyMuPDF"` |
| `pymupdf_version` | string | e.g. `"1.28.2"` |
| `mupdf_version` | string | Underlying MuPDF version |

### coordinate_space

A fixed description of the convention, repeated in both reports so a JSON file
is self-explanatory: `unit`, `space`, `origin`, `pdf_space`, `page_area`,
`conversion`. See [pdf-primer.md](pdf-primer.md#coordinate-systems).

### file

| Field | Type | Meaning |
| --- | --- | --- |
| `is_pdf` | bool | False for other formats MuPDF can open (XPS, EPUB, …); object-level views are unavailable then |
| `pdf_version` | string \| null | From the header, e.g. `"PDF 1.7"` |
| `catalog_version` | string \| null | `/Version` in the catalog, which overrides the header when present |
| `page_count` | int | Pages |
| `chapter_count` | int | MuPDF chapters; `1` for PDFs |
| `version_count` | int | Number of incremental-update generations MuPDF sees |
| `is_repaired` | bool | True when MuPDF had to rebuild the xref to open the file — a strong hint the file is damaged |
| `is_linearized_fast_web_view` | bool | Linearised for byte-serving |
| `document_id` | string[] | The trailer `/ID` pair as hex strings |
| `trailer` | string \| null | Trailer source as MuPDF prints it |
| `catalog_xref` | int \| null | xref of `/Root` |
| `page_mode` | string | `/PageMode`, e.g. `"UseNone"`, `"UseOutlines"`, `"UseAttachments"` |
| `page_layout` | string | `/PageLayout`, e.g. `"SinglePage"`, `"TwoColumnLeft"` |
| `mark_info` | object | `/MarkInfo`, e.g. `{"Marked": true}` |
| `language` | string \| null | `/Lang` |
| `page_labels` | array | `/PageLabels` rules if present |
| `xref` | object | See below |

### file.xref

Produced by scanning every object's `/Type`.

| Field | Type | Meaning |
| --- | --- | --- |
| `xref_length` | int | Slots in the cross-reference table, including slot 0 |
| `objects_scanned` | int | How many were actually inspected |
| `scan_truncated` | bool | True when the file has more objects than `XREF_SCAN_LIMIT` (200 000) |
| `type_counts` | object | Histogram, e.g. `{"/Page": 4, "/Font": 2}`, sorted by count |
| `objects_without_type` | int | Free slots and objects with no `/Type` (many streams and arrays have none) |
| `stream_objects` | int | Objects that carry stream data |
| `object_streams` | int[] | xrefs of `/ObjStm` objects |
| `uses_object_streams` | bool | Convenience flag |
| `cross_reference_streams` | int[] | xrefs of `/XRef` objects |
| `uses_cross_reference_streams` | bool | False means a classic xref table |

### encryption

| Field | Type | Meaning |
| --- | --- | --- |
| `is_encrypted` | bool | The file itself is encrypted (derived from `needs_pass` plus the method string, so it stays true after a successful unlock) |
| `needs_password` | bool | A password was required to open it |
| `still_locked` | bool | PyMuPDF's raw `Document.is_encrypted`, which flips to false after authentication |
| `method` | string \| null | e.g. `"Standard V5 R6 256-bit AES"` |
| `permissions.raw` | int | The permission bitmask as reported |
| `permissions.allowed` | object | `print`, `modify`, `copy`, `annotate`, `fill_forms`, `accessibility`, `assemble`, `print_high_quality` → bool |

Permissions are informational; PDF permissions are not enforced by any reader
that can decrypt the file.

### metadata

| Field | Type | Meaning |
| --- | --- | --- |
| `info` | object | The Info dictionary as MuPDF reports it: `format`, `title`, `author`, `subject`, `keywords`, `creator`, `producer`, `creationDate`, `modDate`, `trapped`, `encryption` |
| `xmp.present` | bool | Whether `/Metadata` exists |
| `xmp.xref` | int \| null | Object holding the XMP packet |
| `xmp.xml` | string \| null | The packet, decoded as UTF-8 |
| `xmp.length` | int | Characters |
| `xmp.error` | string | Present when the stream could not be read |

Dates are PDF date strings (`D:20260828173949+02'00'`), left unparsed on
purpose.

### structure

| Field | Type | Meaning |
| --- | --- | --- |
| `catalog` | object | Full [object description](#object-description) of `/Root` |
| `page_tree.root` | object \| null | Recursive node: `xref`, `type`, `count`, `inherited` (`MediaBox`, `CropBox`, `Resources`, `Rotate` as raw source), `kids[]` |
| `page_tree.nodes` | int | Nodes visited |
| `page_tree.truncated` | bool | True if the walk hit the node limit, a cycle or depth 64 |
| `struct_tree_root` | object \| null | `null` when the document is **not tagged**; otherwise `root_xref`, `role_map`, `class_map`, `parent_tree`, `tree`, `nodes`, `truncated` |
| `struct_tree_root.tree` | object | Recursive node: `xref`, `type`, `tag` (`/P`, `/H1`, `/Figure`…), `title`, `alt`, `actual_text`, `language`, `page` (xref of `/Pg`), `kids[]`, or `marked_content` when children are marked-content ids rather than objects |
| `name_trees.names_xref` | int \| null | The catalog's `/Names` object |
| `name_trees.trees` | object | Per sub-tree (`Dests`, `JavaScript`, `EmbeddedFiles`, `AP`, `Pages`, `Templates`, `URLS`, `IDS`, `Renditions`, `AlternatePresentations`): `xref` and `entries[] {key, value}` |
| `named_destinations` | object | `Document.resolve_names()` output: destination name → target details |
| `outline` | array | `level` (1-based depth), `title`, `page` (zero-based, `null` if unresolved), `page_label_number` (one-based as PyMuPDF reports it), `destination` (`kind`, `xref`, `page`, `to`, `zoom`) |

### fonts

| Field | Type | Meaning |
| --- | --- | --- |
| `items[].xref` | int | Font object |
| `items[].base_font` | string | `/BaseFont`, e.g. `"ABCDEF+Helvetica"` |
| `items[].subtype` | string | `Type1`, `TrueType`, `Type0`, `Type3`, `MMType1` |
| `items[].resource_name` | string \| null | Name used in the content stream, e.g. `"/F1"` |
| `items[].encoding` | string \| null | e.g. `"WinAnsiEncoding"` |
| `items[].embedded` | bool | Whether the font program is in the file |
| `items[].font_file_extension` | string \| null | `ttf`, `cff`, `otf`… when embedded |
| `items[].subset_prefix` | string \| null | The six-letter subset tag if present |
| `items[].referenced_by_xobject` | string \| null | Set when the font is referenced from a form XObject rather than the page |
| `items[].used_on_pages` | int[] | Zero-based page numbers |
| `items[].font_descriptor_xref` | int \| null | `/FontDescriptor` |
| `items[].to_unicode_xref` | int \| null | `/ToUnicode` CMap; absence often explains unreadable text |
| `items[].descendant_fonts` | int[] | For `Type0` fonts |
| `pages_scanned` | int | Pages inspected (limit 2 000) |
| `scan_truncated` | bool | True when the document has more pages than that |

### attachments

Array of embedded files: `index`, `name` (name-tree key), `filename`,
`ufilename`, `description`, `size` (uncompressed), `length`, `creationDate`,
`modDate`. Download with
[`/attachments/{index}`](api.md#get-attachmentsindex).

### form

| Field | Type | Meaning |
| --- | --- | --- |
| `is_form_pdf` | bool | Document has an AcroForm |
| `acroform` | string \| null | Raw `/AcroForm` value |
| `acroform_xref` | int \| null | Its object, when indirect |
| `sig_flags` | int | `/SigFlags`; `-1` when absent, `1` signatures exist, `3` append-only |
| `fields[]` | array | One entry per widget, across all pages |

Field entries: `page`, `xref`, `field_name`, `field_label`, `field_type`
(int), `field_type_string` (`Text`, `CheckBox`, `RadioButton`, `ComboBox`,
`ListBox`, `Signature`, `Button`), `field_value`, `field_display`,
`field_flags`, `is_signed`, `choice_values`, `rect`, `text_font`,
`text_fontsize`, `text_maxlen`, `border_style`, `script`.

### optional_content

| Field | Type | Meaning |
| --- | --- | --- |
| `ocgs` | object | Optional content groups by xref, with name, intent, usage |
| `layers` | array | Layer configurations |
| `ui_configs` | array | Entries a viewer would show in its layers panel |

Each may instead be `{"error": "..."}` if PyMuPDF refused.

### javascript

Array of document-level JavaScript actions: `name`, `xref`, `script`. Scripts
stored as streams are fetched and decoded. Field-level scripts appear in
`form.fields[].script` instead. Nothing is ever executed.

### pages (summaries)

Cheap per-page entries so the UI can build navigation without extracting
anything: `page_number`, `label` (from `/PageLabels`), `xref`, `rect`,
`mediabox`, `cropbox`, `rotation`, `width`, `height`. A page that failed to
load contributes `{page_number, error}`.

### known_limitations and warnings

`known_limitations` is a fixed list of `{topic, detail}` describing what exists
in PDFs but cannot be reached through PyMuPDF — reproduced in the UI's
**Not extractable** tab and in [coverage.md](coverage.md).

`warnings` is document-specific, for example when a file is not tagged or is
not a PDF at all.

## Page report

```jsonc
{
  "schema_version": "1.0", "document_id": "…", "page_number": 0, "label": null,
  "coordinate_space": {}, "page": {}, "resources": {}, "content_streams": {},
  "text": {}, "images": {}, "drawings": [], "annotations": [], "links": [],
  "widgets": [], "xobjects": [], "fonts": []
}
```

### page

| Field | Type | Meaning |
| --- | --- | --- |
| `xref` | int | The page object |
| `rotation` | int | `/Rotate`, already applied to every coordinate below |
| `boxes.rect` | rect | `page.rect` — CropBox after rotation; the reference frame for all coordinates |
| `boxes.mediabox` | rect | `/MediaBox` |
| `boxes.cropbox` | rect | `/CropBox` |
| `boxes.artbox` / `bleedbox` / `trimbox` | rect | The remaining boxes; each defaults to CropBox/MediaBox when absent |
| `rect_in_pdf_space` | rect | `boxes.rect` converted to the file's bottom-left origin, as a worked example |
| `width`, `height` | float | Of `boxes.rect`, rounded to 4 decimals |
| `transformation_matrix` | matrix | PDF space → PyMuPDF space |
| `transformation_matrix_inverse` | matrix \| null | The inverse |
| `rotation_matrix` | matrix | Unrotated → rotated |
| `derotation_matrix` | matrix | Rotated → unrotated |
| `dictionary` | object | Full [object description](#object-description) of the page object |

### resources

| Field | Type | Meaning |
| --- | --- | --- |
| `raw` | string \| null | The page's `/Resources` value as written |
| `xref` | int \| null | Its object when indirect; `null` when written inline |
| `inherited` | bool | True when the page has no `/Resources` of its own and inherits from an ancestor |
| `categories` | object | One entry per present category: `Font`, `XObject`, `ColorSpace`, `Pattern`, `Shading`, `ExtGState`, `Properties`, `ProcSet` |
| `categories.<C>.raw` | string | Category value as written |
| `categories.<C>.xref` | int \| null | Category dictionary object, when indirect |
| `categories.<C>.members[]` | array | `name` (`"/F1"`), `value` (raw), `xref` (resolved, if indirect), `type`, `subtype` |

Direct dictionaries (`/Resources << /Font << /F1 12 0 R >> >>`) are parsed by
the project's own dictionary-source parser, so members resolve whether the
producer used indirect objects or not.

### content_streams

| Field | Type | Meaning |
| --- | --- | --- |
| `streams[]` | array | Per `/Contents` stream: `xref`, `filter`, `raw_bytes`, `decoded_bytes`, plus `raw_error`/`decode_error` when MuPDF refused |
| `stream_count` | int | Number of streams concatenated |
| `total_decoded_bytes` | int | Length of the concatenated decoded stream |
| `decoded` | string | Up to 200 000 characters of it |
| `decoded_truncated` | bool | True when longer; download the full stream from the API |
| `note` | string | Explains the concatenation and truncation policy |
| `operators[]` | array | The decompiled listing, in order |
| `operator_counts` | object | Operator → count, sorted by frequency |
| `operators_truncated` | bool | True when the page report's operator window (5 000) did not cover the stream. The exact total is not in the page report, because counting means lexing the whole stream; ask [`operators`](api.md#get-pagespage_numberoperators) for it |
| `error` | string | Present instead of the above when the stream could not be read at all |

Operator entries:

| Field | Type | Meaning |
| --- | --- | --- |
| `op` | string | The operator, e.g. `"Tf"`, `"re"`, `"TJ"` |
| `offset` | int | Byte offset in the concatenated decoded stream |
| `operands` | array | Numbers, or objects: `{"name": "/F1"}`, `{"string": "text"}`, `{"hex_string": "48690a", "text": "Hi\n"}`, `{"array": [...]}`, `{"dict": [...]}` |
| `description` | string | Plain-English meaning, when the operator is a known one |
| `inline_image` | object | Only on `BI`: `{dictionary, data_bytes}`, and `truncated` if `EI` was never found |

### text

| Field | Type | Meaning |
| --- | --- | --- |
| `has_text_layer` | bool | False for scans and pure vector art |
| `plain` | string | `get_text("text")`, reading order preserved |
| `character_count` | int | Characters across all spans |
| `note` | string \| null | Explains an absent text layer, including that no OCR is performed |
| `blocks[]` | array | Flat block list: `index`, `number`, `type` (`text`/`image`), `bbox`, `text` |
| `words[]` | array | `bbox`, `text`, `block`, `line`, `word` indices |
| `structure.width` / `.height` | float | Page size as MuPDF reports it for the text page |
| `structure.blocks[]` | array | The full tree, below |

Block → line → span → char:

| Level | Fields |
| --- | --- |
| Block | `index`, `number`, `type`, `bbox`, `lines[]`; image blocks instead carry `image {width, height, ext, colorspace, bpc, xres, yres, size, transform, has_mask}` and an empty `lines` |
| Line | `index`, `bbox`, `wmode` (0 horizontal, 1 vertical), `direction` `[cos, −sin]`, `spans[]` |
| Span | `index`, `text`, `bbox`, `origin`, `font`, `size`, `color`, `alpha`, `ascender`, `descender`, `flags`, `font_flags`, `char_flags`, `style_flags`, `bidi`, `chars[]` |
| Char | `c` (one character), `bbox`, `origin`, `synthetic` (glyph invented by the renderer) |

`color` is `{int, hex, rgb, rgb_float}`.
`font_flags` decodes `flags`: `superscript`, `italic`, `serifed`,
`monospaced`, `bold`.
`style_flags` decodes `char_flags`: `strikeout`, `underline`,
`synthetic_bold`, `filled`, `stroked`, `clipped`.

### images

| Field | Type | Meaning |
| --- | --- | --- |
| `placements[]` | array | One per drawn instance, in page order |
| `objects[]` | array | One per distinct image XObject used on the page |
| `inline_images[]` | array | One per inline image occurrence |
| `error` | string | Present when placements could not be listed at all |

Placement entries: `index`, `xref` (`null` for inline), `inline`, `bbox`,
`transform` (the matrix that maps the unit square to the placement),
`width`/`height` (**stored pixels**, not the drawn size),
`colorspace_components`, `colorspace_name`, `bits_per_component`, `xres`,
`yres`, `stored_size`, `has_mask`, `file`, and `inline_index` for inline
images.

Object entries: `xref`, `inline: false`, `width`, `height`, `ext` (`png`,
`jpeg`, `jpx`, `bmp`, …), `colorspace` (`GRAY`/`RGB`/`CMYK`),
`colorspace_components`, `colorspace_name` (the full name including ICC
profile), `bits_per_component`, `xres`, `yres`, `dpi`, `byte_size`,
`smask_xref`, `has_transparency`, `file`, and `object` — the raw dictionary
entries that describe encoding: `Filter`, `DecodeParms`, `ColorSpace`,
`BitsPerComponent`, `Width`, `Height`, `ImageMask`, `Decode`, `Interpolate`,
`SMask`, `Mask`, `Intent`, `Name`. `error` replaces the payload fields when the
bytes could not be extracted.

`file` is a name inside the document's `images/` directory, served by
[`/images/{filename}`](api.md#get-imagesfilename). One xref is written once,
however many placements reference it.

### drawings

Array of paths, in painting order — **a window, not necessarily the whole page**.
`drawings_info` states what the window covers:

| Field | Type | Meaning |
| --- | --- | --- |
| `drawings_info.total` | int \| null | Paths on the page, whatever the window holds; `null` if MuPDF could not read them |
| `drawings_info.offset` | int | Index of the first path in `drawings` |
| `drawings_info.limit` | int \| null | Window size that was applied |
| `drawings_info.truncated` | bool | True when paths after the window exist. Page through [`drawings`](api.md#get-pagespage_numberdrawings) |

Each path:

| Field | Type | Meaning |
| --- | --- | --- |
| `index` | int | Position **on the page**, so it stays stable across windows |
| `seqno` | int | MuPDF's sequence number, which interleaves with text |
| `type` | string | `f`, `s`, `fs`, `c`, `cs`, `clip` |
| `type_label` | string | `fill`, `stroke`, `fill and stroke`, `clip`, … |
| `rect` | rect | Bounding box of the whole path |
| `even_odd` | bool | Fill rule |
| `close_path` | bool | Whether the path was closed |
| `fill`, `stroke` | object \| null | `{components: [...], hex: "#rrggbb"}`; components are the raw values in the source colour space (1 = gray, 3 = RGB, 4 = CMYK) |
| `fill_opacity`, `stroke_opacity` | float | 0–1 |
| `width` | float | Line width in points |
| `dashes` | string | PDF dash array as written, e.g. `"[3 2] 0"` |
| `line_cap` | int[] | Cap styles |
| `line_join` | float | Join style |
| `layer` | string \| null | Optional-content layer the path belongs to |
| `level` | int \| null | Nesting depth |
| `scissor` | rect \| null | Active clip rectangle |
| `items[]` | array | The path itself |

Item shapes: `{"op": "l", "kind": "line", "points": [[x,y],[x,y]]}`,
`{"op": "c", "kind": "cubic bezier", "points": [p0,p1,p2,p3]}`,
`{"op": "re", "kind": "rectangle", "rect": [...], "orientation": 1}`,
`{"op": "qu", "kind": "quad", "points": [ul, ur, ll, lr]}`.

### annotations

Array with `index`, `xref`, `type` (`Highlight`, `Text`, `Square`,
`FreeText`, `Stamp`, `FileAttachment`, …), `type_number`, `rect`, `info`
(`content`, `title`, `subject`, `name`, `creationDate`, `modDate`, `id`),
`flags`, `colors` (`stroke`, `fill`), `border`, `opacity`, `blend_mode`,
`vertices`, `line_ends`, `is_open`, `has_popup`, `popup_rect`, `irt_xref`,
`language`, `appearance_bbox`, `file_info`. Type-specific fields are `null`
where they do not apply. An entry that could not be read is
`{index, error}`.

Widget annotations are reported in [`widgets`](#widgets), not here.

### links

`index`, `kind` (MuPDF's link kind), `rect`, plus `uri` for external links or
`page`/`to`/`zoom` for internal destinations, and `xref` where available.

### widgets

Form fields on this page, same field set as
[`form.fields`](#form) minus `page`.

### xobjects and fonts

`xobjects[]`: `xref`, `name`, `raw` — every XObject referenced by the page,
images and form XObjects alike.

`fonts[]`: the page's own font list — `xref`, `embedded`,
`font_file_extension`, `subtype`, `base_font`, `resource_name`, `encoding`,
`referenced_by_xobject`. The document-level [`fonts`](#fonts) aggregates the
same data across pages with usage information.

## Object description

Returned by `describe_object()` and by
[`GET /objects/{xref}`](api.md#get-apidocumentsdocument_idobjectsxref); also
embedded as `structure.catalog` and `page.dictionary`.

| Field | Type | Meaning |
| --- | --- | --- |
| `xref` | int | Object number |
| `type` | string \| null | `/Type` value |
| `subtype` | string \| null | `/Subtype` value |
| `is_stream` | bool | Whether the object carries stream data |
| `source` | string | The object's dictionary as MuPDF prints it |
| `entries` | object | Key → `{type, value, xref?}`; `type` is MuPDF's token type (`name`, `int`, `array`, `dict`, `string`, `xref`), and `xref` is set when the value is an indirect reference |
| `references` | int[] | Every `N 0 R` found in `source`, sorted |
| `stream_raw_bytes` | int \| null | Stored size |
| `stream_decoded_bytes` | int \| null | Size after filters |
| `stream_decoded` | string | Decoded text, when requested |
| `stream_truncated` | bool | True when longer than 200 000 characters |
| `stream_raw_error` / `stream_decode_error` | string | Why MuPDF refused |
| `error` | string | The object could not be read at all |

## Render info

The `X-Render-Info` header on
[`render.png`](api.md#get-pagespage_numberrenderpng):

| Field | Meaning |
| --- | --- |
| `dpi` | Effective resolution after clamping to 24–400 |
| `zoom` | `dpi / 72` — the points-to-pixels factor |
| `pixel_width`, `pixel_height` | Bitmap size |
| `point_width`, `point_height` | Size of what was rendered: `page.rect`, or the clip rectangle when one was given |
| `rotation` | `/Rotate` applied |
| `origin` | Reminder that the frame matches the reported bounding boxes |
| `clip` | Only with `?clip=`: the rectangle actually rendered, after being normalised and clamped to `page.rect` |
| `page_point_size` | Only with `?clip=`: `[width, height]` of the whole page, so a clipped render can still be placed on it |

The `X-Image-Preview-Info` header on
[`images/{xref}/preview.png`](api.md#get-imagesxrefpreviewpng):

| Field | Meaning |
| --- | --- |
| `xref` | The image XObject that was decoded |
| `original_ext` | Format the bytes are stored in (`jpx`, `jpeg`, `png`, …) — the preview is always PNG |
| `source_pixels` | `[width, height]` of the decoded image |
| `preview_pixels` | `[width, height]` returned, after `max_side` scaling |
| `colorspace` | Colourspace of the decoded pixmap, including ICC profile name where MuPDF reports one |
| `has_alpha` | Whether the pixmap carries an alpha channel |
| `max_side` | The limit that was applied |

## Export bundle layout

`GET /export.zip` and `build_document_bundle()`:

| Entry | Content |
| --- | --- |
| `README.txt` | Describes the bundle and restates the coordinate convention |
| `document.json` | Document report |
| `pages/page-NNNN.json` | Page report per page (one-based file names) |
| `pages/page-NNNN.error.txt` | Written instead when a page failed |
| `text/page-NNNN.txt` | Per-page plain text |
| `text/document.txt` | Whole document text |
| `text/document.md` | Whole document text with `## Page N` sections |
| `content-streams/page-NNNN.txt` | Decoded content stream per page |
| `content-streams/page-NNNN.error.txt` | Written instead on failure |
| `images/…` | Every extracted image, original format and name |

`GET /api/export/all.zip` nests one such bundle per document under
`<file_prefix>/`.

## Truncation and limits

| Limit | Value | Constant | Effect when hit |
| --- | --- | --- | --- |
| Objects scanned for the type histogram | 200 000 | `core.schema.XREF_SCAN_LIMIT` | `file.xref.scan_truncated: true` |
| Nodes per structure/name-tree walk | 5 000 | `core.objects.DEFAULT_NODE_LIMIT` | `truncated: true` on that tree |
| Tree depth | 64 | — | Node marked `truncated` |
| Inlined decoded content stream | 200 000 chars | `core.schema.CONTENT_STREAM_INLINE_LIMIT` | `decoded_truncated: true`; download for the rest |
| Operators inlined in a page report | 5 000 | `core.schema.PAGE_OPERATOR_LIMIT` | `operators_truncated: true`; page through [`operators`](api.md#get-pagespage_numberoperators) |
| Operators per window request | 20 000 | `core.schema.CONTENT_STREAM_OPERATOR_LIMIT` | `422` when a larger `limit` is asked for |
| Vector paths inlined in a page report | 5 000 | `core.schema.PAGE_DRAWING_LIMIT` | `drawings_info.truncated: true`, with the real `total`; page through [`drawings`](api.md#get-pagespage_numberdrawings) |
| Pages scanned for fonts | 2 000 | `core.document.FONT_SCAN_PAGE_LIMIT` | `fonts.scan_truncated: true` |
| Inlined object stream | 200 000 chars | argument to `describe_object` | `stream_truncated: true` |
| Render resolution | 24–400 dpi | `core.render.MAX_DPI` | Clamped silently |

Nothing is ever dropped without a flag saying so.

## Error fields

| Where | Field | Meaning |
| --- | --- | --- |
| Any section | `error` | That section could not be produced; the rest of the report is valid |
| `content_streams.streams[]` | `raw_error`, `decode_error` | MuPDF could not read or decode that stream |
| `images.objects[]` | `error` | Image bytes unavailable, e.g. an unsupported filter |
| `images.inline_images[]` | `error` | An inline image was detected but its bytes were not exposed |
| `annotations[]`, `widgets[]` | `error` | A single annotation failed; the others are intact |
| Object description | `error`, `stream_raw_error`, `stream_decode_error` | See above |
| Document report | `warnings[]` | Document-level observations, e.g. "not tagged" |
