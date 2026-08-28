# Coverage: what is and is not extracted

An honest map of the PDF feature set against what this tool surfaces. The rule
throughout the project: if something exists in the file but cannot be reached,
say so — in the report (`known_limitations`, `warnings`, `error` fields), in
the UI (**Not extractable** tab) and here.

- [Legend](#legend)
- [File and document structure](#file-and-document-structure)
- [Objects and streams](#objects-and-streams)
- [Pages](#pages)
- [Content streams](#content-streams)
- [Text](#text)
- [Fonts](#fonts)
- [Images](#images)
- [Vector graphics and colour](#vector-graphics-and-colour)
- [Annotations, links, forms](#annotations-links-forms)
- [Navigation and logical structure](#navigation-and-logical-structure)
- [Metadata](#metadata)
- [Encryption](#encryption)
- [Optional content, multimedia, 3D](#optional-content-multimedia-3d)
- [Out of scope by design](#out-of-scope-by-design)
- [Summary of the hard limits](#summary-of-the-hard-limits)

## Legend

| Symbol | Meaning |
| --- | --- |
| ✅ | Fully exposed as structured data |
| 🟡 | Exposed, but raw or partial — usually the PDF source string rather than a parsed structure |
| ❌ | Not reachable through PyMuPDF; explicitly reported as a limitation |
| — | Out of scope by design |

## File and document structure

| Feature | Status | Where / notes |
| --- | --- | --- |
| PDF version (header and `/Version`) | ✅ | `file.pdf_version`, `file.catalog_version` |
| Page, chapter, version counts | ✅ | `file.*_count` |
| Trailer dictionary | 🟡 | `file.trailer` as source text; individual keys are not parsed out |
| Document `/ID` pair | ✅ | `file.document_id` |
| Catalog | ✅ | `structure.catalog` with every entry and reference |
| Linearisation (fast web view) | 🟡 | Boolean only (`file.is_linearized_fast_web_view`); the linearisation dictionary and hint streams are not exposed |
| Damaged file repaired on open | ✅ | `file.is_repaired` |
| Incremental update sections | ❌ | MuPDF flattens them; `version_count` hints at how many exist, but the per-revision objects and the previous xref chain are not reachable |
| Original byte offsets of objects | ❌ | MuPDF re-serialises object source; offsets in the source file are lost |
| Classic xref table layout | ❌ | Only the effective object table is visible |
| File size, SHA-256 | ✅ | `identity` |

## Objects and streams

| Feature | Status | Where / notes |
| --- | --- | --- |
| Any object by number | ✅ | `objects/{xref}` — type, subtype, entries, source, references |
| Dictionary entries with resolved references | ✅ | `entries[].xref` |
| Nested dictionaries | 🟡 | Reported as source text (`<</A 1>>`); `parse_dict_source` splits one level when needed |
| Streams: raw and decoded sizes | ✅ | `stream_raw_bytes`, `stream_decoded_bytes` |
| Stream bytes | ✅ | Downloadable decoded or raw |
| Filter chains | 🟡 | `/Filter` and `/DecodeParms` as written; decoding is MuPDF's, and an unsupported chain is reported per stream |
| Object streams (`/ObjStm`) | 🟡 | Detected and listed by xref; the packed objects are readable individually, but the packing layout is not shown |
| Cross-reference streams (`/XRef`) | 🟡 | Detected and listed by xref |
| Free / deleted objects | ❌ | Slots with no type are counted (`objects_without_type`), not enumerated |
| Object generation numbers | ❌ | PyMuPDF's API is generation-agnostic; everything is treated as generation 0 |

## Pages

| Feature | Status | Where / notes |
| --- | --- | --- |
| Page tree with inheritance | ✅ | `structure.page_tree`, including inherited MediaBox/CropBox/Resources/Rotate |
| Page dictionary | ✅ | `page.dictionary` |
| MediaBox, CropBox, BleedBox, TrimBox, ArtBox | ✅ | `page.boxes` |
| `/Rotate` | ✅ | `page.rotation`, already applied to coordinates |
| Coordinate matrices | ✅ | Transformation, inverse, rotation, derotation |
| `/Resources` per category | ✅ | Fonts, XObjects, colour spaces, patterns, shadings, ExtGState, properties, ProcSet |
| Page labels | ✅ | `file.page_labels`, and `label` per page |
| `/UserUnit` | ❌ | Not exposed; pages are always reported in points |
| Page-level transitions, `/Group`, `/Thumb` | 🟡 | Present in the page dictionary as raw entries; not parsed |

## Content streams

| Feature | Status | Where / notes |
| --- | --- | --- |
| Stream objects making up a page | ✅ | `content_streams.streams[]` |
| Decoded stream text | ✅ | Inline up to 200 000 characters, always downloadable in full |
| Raw (still encoded) bytes | ✅ | Download endpoint |
| Operator listing with operands and offsets | ✅ | Parsed by this project, not by PyMuPDF |
| Operator descriptions | ✅ | For the ~70 standard operators |
| Inline images (`BI … ID … EI`) | 🟡 | Dictionary and byte length reported; bytes recovered through MuPDF's image blocks where it exposes them, otherwise noted as unavailable |
| Form XObject content streams | 🟡 | Reachable through the object browser as a stream; not parsed into an operator listing of their own |
| Type 3 font glyph procedures | 🟡 | Same: reachable as streams, not listed as operators |
| Byte offsets in the *original* file | ❌ | Offsets are into the decoded, concatenated stream |

## Text

| Feature | Status | Where / notes |
| --- | --- | --- |
| Plain page text in reading order | ✅ | `text.plain` |
| Blocks, lines, spans | ✅ | `text.structure` |
| Individual characters with bbox and origin | ✅ | `spans[].chars[]` from `rawdict` |
| Words with indices | ✅ | `text.words` |
| Font name, size, colour, alpha per span | ✅ | |
| Bold / italic / serif / monospace / superscript flags | ✅ | `font_flags`, derived by MuPDF from the font |
| Underline / strikeout / fill / stroke / clip flags | ✅ | `style_flags` |
| Writing mode and direction | ✅ | `lines[].wmode`, `lines[].direction` |
| Bidi level | ✅ | `spans[].bidi` |
| Text rendering mode (`Tr`) | 🟡 | Visible in the operator listing; not attached to spans |
| Character-to-glyph mapping, `/ToUnicode` CMap contents | ❌ | The `/ToUnicode` stream can be downloaded, but is not decoded into a mapping table |
| Text in scanned pages | ❌ | No OCR. `has_text_layer` is false and `text.note` explains it |
| Logical reading order from tagging | 🟡 | The structure tree is exposed; text is not re-ordered to follow it |

## Fonts

| Feature | Status | Where / notes |
| --- | --- | --- |
| Base font name, subtype, encoding | ✅ | `fonts.items[]` |
| Embedded or not, font-file extension | ✅ | |
| Subset prefix | ✅ | `ABCDEF+` split out |
| Where each font is used | ✅ | `used_on_pages` |
| `/FontDescriptor`, `/ToUnicode`, descendant fonts | ✅ | As xrefs, one click away |
| Embedded font program bytes | 🟡 | Downloadable as a raw stream from the descriptor |
| Glyph outlines, widths, kerning, CMaps | ❌ | Not decoded |
| Font metrics (`/FontBBox`, `/StemV`, …) | 🟡 | Visible in the descriptor object, unparsed |

## Images

| Feature | Status | Where / notes |
| --- | --- | --- |
| Image bytes in original format | ✅ | Written per xref, downloadable |
| Pixel dimensions, bit depth | ✅ | |
| Colourspace, including ICC profile name | ✅ | `colorspace_name` |
| DPI | ✅ | As reported by MuPDF for the placement |
| Filters and decode parameters | 🟡 | Raw `/Filter`, `/DecodeParms` |
| SMask / transparency | ✅ | `smask_xref`, `has_transparency`; the soft mask itself is reachable as an object |
| `/Mask`, `/Decode`, `/ImageMask`, `/Interpolate` | 🟡 | Raw values in `objects[].object` |
| Every placement with bbox and matrix | ✅ | Deduplicated per xref |
| Inline images | 🟡 | Reported per occurrence; bytes only where MuPDF exposes them |
| JPXDecode (JPEG 2000) images | 🟡 | Extracted when MuPDF can decode them; otherwise the error is reported. Stored as `.jpx`, which browsers cannot display, so the UI previews them through `/images/{xref}/preview.png` |
| Colour-managed conversion | ❌ | No colour management: components are reported as stored, and hex values are a plain approximation |

## Vector graphics and colour

| Feature | Status | Where / notes |
| --- | --- | --- |
| Paths with full coordinates | ✅ | Lines, cubic Béziers, rectangles, quads |
| Fill and stroke colours | ✅ | Components plus hex approximation |
| Opacity, line width, dashes, caps, joins | ✅ | |
| Even-odd vs nonzero fill | ✅ | |
| Clipping | 🟡 | Clip paths appear as path type `clip`, and `scissor` gives the active clip rect |
| Layer membership | ✅ | `drawings[].layer` |
| Shadings and gradients (`sh`, `/Shading`) | 🟡 | Listed as resources and reachable as objects; the shading function is not evaluated or previewed |
| Tiling and shading patterns | 🟡 | Same |
| Blend modes, soft masks in `/ExtGState` | 🟡 | Reachable as ExtGState objects; not summarised per path |
| Transparency groups | 🟡 | Present in the page dictionary as `/Group` |

## Annotations, links, forms

| Feature | Status | Where / notes |
| --- | --- | --- |
| All annotation types with rect and properties | ✅ | `annotations[]` |
| Contents, author, dates, flags, colours | ✅ | `info`, `flags`, `colors` |
| Vertices, line ends, popups, appearance bbox | ✅ | Where the type has them |
| Appearance streams (`/AP`) | 🟡 | Reachable through the annotation's object; not rendered separately (they are part of the page render) |
| Links with URI or destination | ✅ | `links[]` |
| AcroForm fields and values | ✅ | `form.fields[]`, per page in `widgets[]` |
| Field flags, choices, max length, font | ✅ | |
| Field-level JavaScript | ✅ | `fields[].script` |
| Signature widgets and `/SigFlags` | 🟡 | Reported; **signatures are not validated** |
| Signature certificate chain, signing time, coverage | ❌ | The `/Contents` PKCS#7 blob is downloadable as a raw value only |
| XFA forms | ❌ | Not exposed; an XFA-only document shows an AcroForm shell with no useful fields |

## Navigation and logical structure

| Feature | Status | Where / notes |
| --- | --- | --- |
| Outline / bookmarks with destinations | ✅ | `structure.outline` |
| Named destinations | ✅ | `structure.named_destinations` |
| Name trees (`/Dests`, `/JavaScript`, `/EmbeddedFiles`, …) | ✅ | `structure.name_trees` |
| Structure tree (`/StructTreeRoot`) | ✅ | Tags, `/Alt`, `/ActualText`, language, page links |
| `/RoleMap`, `/ClassMap`, `/ParentTree` | 🟡 | Reported as raw values / xrefs |
| Marked-content operators | 🟡 | Visible in the operator listing (`BDC`, `EMC`); not linked back to structure elements |
| Marked-content id → structure element mapping | ❌ | Would require walking `/ParentTree` and matching MCIDs; not implemented |
| Page labels | ✅ | |
| Article threads, `/Outlines` actions beyond destinations | 🟡 | Reachable as objects |

## Metadata

| Feature | Status | Where / notes |
| --- | --- | --- |
| Info dictionary | ✅ | Verbatim |
| XMP packet | ✅ | Full XML, with its object number |
| XMP parsed into properties | ❌ | Returned as text; parse it yourself if you need fields |
| Dates | 🟡 | PDF date strings, deliberately unparsed |
| PDF/A, PDF/UA conformance claims | 🟡 | Present inside the XMP text; not extracted as a flag |
| `/MarkInfo`, `/Lang`, `/PageMode`, `/PageLayout` | ✅ | |

## Encryption

| Feature | Status | Where / notes |
| --- | --- | --- |
| Encrypted or not, method string | ✅ | e.g. `Standard V5 R6 256-bit AES` |
| Permission bits, decoded | ✅ | Eight named booleans |
| Opening with a user password | ✅ | Via the unlock endpoint or the `password` argument |
| `/Encrypt` dictionary internals (`/O`, `/U`, `/OE`, `/UE`, `/P`, `/R`, `/V`) | ❌ | Not exposed by the API |
| Owner-password recovery, permission bypass | — | Out of scope; the tool needs the password the user has |
| Public-key (certificate) encryption | 🟡 | Opens only if MuPDF can, which normally means it cannot without the recipient's key |

## Optional content, multimedia, 3D

| Feature | Status | Where / notes |
| --- | --- | --- |
| Optional content groups and layer configurations | ✅ | `optional_content` |
| Layer membership of drawings | ✅ | `drawings[].layer` |
| Layer visibility simulation | ❌ | Renders use the document's default configuration |
| Embedded files / attachments | ✅ | Listed and downloadable |
| Document-level JavaScript | ✅ | Shown as inert text; never executed |
| Multimedia, screen annotations, 3D (`/RichMedia`, U3D, PRC) | 🟡 | Their annotation and object dictionaries are visible; content is not decoded |
| Portfolios / collections | 🟡 | The attachments are listed; the collection view schema is not interpreted |

## Out of scope by design

Not missing — deliberately not built:

- **OCR** of scanned pages.
- **Editing, writing or converting** PDFs. The tool never modifies the source
  file; the copy in the workspace is read-only in practice.
- **Rendering fidelity checks**, colour management, print preflight.
- **Signature validation** and any cryptographic verification.
- **Password cracking** or permission bypass.
- **Comparing documents**, search across a corpus, or any kind of database.
- **Network features**: no fetching of remote resources referenced by a PDF.

## Summary of the hard limits

The six entries reproduced in every document report as `known_limitations`:

| Topic | Detail |
| --- | --- |
| Digital signatures | `/SigFlags` and signature widgets are reported; signatures are not validated and the PKCS#7 chain is not decoded. The raw `/Contents` byte string is reachable through the object view |
| Encryption internals | Method string and permission bits are reported; the `/Encrypt` dictionary's parameters and keys are not exposed |
| Font programs | Embedded fonts can be located by xref and downloaded as raw streams, but glyph outlines, CMaps and `/ToUnicode` mappings are not decoded |
| Scanned pages | Image-only pages carry no text layer; no OCR is performed, so extraction correctly returns nothing |
| Original byte offsets | MuPDF re-serialises object source, so byte offsets, the classic xref layout and incremental update sections are not reported; object-stream and xref-stream usage is detected by object type instead |
| Content-stream provenance | Streams are concatenated and decoded by MuPDF; the operator listing comes from this project's parser, and unsupported or damaged filter chains are reported per stream |
