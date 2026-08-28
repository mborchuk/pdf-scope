# Concepts: how a PDF is built

This page explains the parts of a PDF that the tool exposes, and the vocabulary
used everywhere else in the documentation. If you already know ISO 32000, skip
to [Coordinate systems](#coordinate-systems) — that section defines the
convention every number in this project follows.

- [The file as a set of objects](#the-file-as-a-set-of-objects)
- [The cross-reference table](#the-cross-reference-table)
- [Object streams and cross-reference streams](#object-streams-and-cross-reference-streams)
- [The trailer and the catalog](#the-trailer-and-the-catalog)
- [The page tree](#the-page-tree)
- [Page boxes and rotation](#page-boxes-and-rotation)
- [Resources](#resources)
- [Content streams and operators](#content-streams-and-operators)
- [Text: how characters get on the page](#text-how-characters-get-on-the-page)
- [Images](#images)
- [Vector graphics](#vector-graphics)
- [Annotations, links and form fields](#annotations-links-and-form-fields)
- [Logical structure and tagging](#logical-structure-and-tagging)
- [Metadata](#metadata)
- [Encryption and permissions](#encryption-and-permissions)
- [Coordinate systems](#coordinate-systems)
- [Where each concept appears in this tool](#where-each-concept-appears-in-this-tool)

## The file as a set of objects

A PDF is not a stream of pages. It is a bag of numbered **indirect objects**,
plus a table saying where each one lives, plus a pointer to the object that is
the root of everything. Each object is one of eight basic types: boolean,
number, string, name (`/Type`), array, dictionary, stream, null.

An object is written as:

```
12 0 obj
<< /Type /Page /MediaBox [0 0 595 842] /Contents 13 0 R >>
endobj
```

`12` is the **object number** (the *xref number* in this tool's vocabulary),
`0` the generation number. `13 0 R` is a **reference** to another object: the
page's content lives in object 13. Following references is how you walk a PDF,
and the [object browser](ui-guide.md#objects-tab) exists to let you do exactly
that.

A **stream** is a dictionary followed by raw bytes, usually compressed:

```
13 0 obj
<< /Length 512 /Filter /FlateDecode >>
stream
...binary...
endstream
endobj
```

The dictionary describes the bytes: how long they are, which filters were
applied (`/FlateDecode`, `/DCTDecode` for JPEG, `/CCITTFaxDecode` for fax
images, and so on). Page contents, images, embedded fonts, embedded files and
XMP metadata are all streams.

## The cross-reference table

At the end of the file, the **xref table** maps object numbers to byte offsets
so a reader can jump straight to object 12 without scanning the file. When a
PDF is edited incrementally, new objects and a new xref section are appended,
and each section points back to the previous one.

This tool reports the number of xref slots (`file.xref.xref_length`) and a
histogram of object types, but **not** byte offsets — see
[the limitation on byte offsets](coverage.md#file-and-document-structure).

## Object streams and cross-reference streams

PDF 1.5 added two space savers:

- an **object stream** (`/Type /ObjStm`) packs many small objects into one
  compressed stream;
- a **cross-reference stream** (`/Type /XRef`) replaces the plain-text xref
  table with a compressed binary one.

Their presence tells you roughly how modern the producer was and why the file
may look empty when opened in a text editor. The tool detects both by object
type and reports the xrefs involved (`file.xref.uses_object_streams`,
`file.xref.uses_cross_reference_streams`).

## The trailer and the catalog

The **trailer** dictionary closes the file and names the root:

```
trailer
<< /Size 54 /Root 1 0 R /Info 50 0 R /ID [<A1B2…> <C3D4…>] >>
```

- `/Root` → the **catalog**, the top of the document.
- `/Info` → the classic metadata dictionary (title, author, dates…).
- `/ID` → two byte strings identifying the file: the first is set when the file
  is created, the second changes on each update. Useful for telling near-copies
  apart.

The **catalog** (`/Type /Catalog`) points at everything else: `/Pages` (the
page tree), `/Outlines` (bookmarks), `/Names` (name trees), `/AcroForm`
(forms), `/StructTreeRoot` (tagging), `/OCProperties` (layers), `/Metadata`
(XMP), `/PageMode`, `/PageLayout`, `/Lang`.

## The page tree

Pages hang off `/Pages` as a balanced tree of nodes:

- intermediate nodes: `/Type /Pages` with `/Kids` and `/Count`;
- leaves: `/Type /Page`.

Four attributes are **inheritable** down the tree — `/Resources`,
`/MediaBox`, `/CropBox` and `/Rotate` — so a page dictionary that seems to be
missing its MediaBox may be inheriting one from an ancestor. The
[structure explorer](ui-guide.md#structure-tab) prints inherited attributes on each
node so this is visible.

## Page boxes and rotation

A page defines up to five rectangles, all in PDF units (points):

| Box | Meaning |
| --- | --- |
| `/MediaBox` | The physical sheet. Required |
| `/CropBox` | The visible region. Defaults to MediaBox |
| `/BleedBox` | Region including printing bleed |
| `/TrimBox` | Intended finished size after trimming |
| `/ArtBox` | Extent of meaningful content |

`/Rotate` is a multiple of 90 that a viewer applies when displaying the page.
Rotation does **not** change the coordinates stored in the content stream: a
rotated page keeps its original numbers, and the viewer turns the result.
PyMuPDF's `page.rect` is the CropBox **after** rotation, which is why a
90°-rotated A4 page reports 842 × 595 rather than 595 × 842.

## Resources

Content streams do not embed fonts or images; they refer to them by name
through the page's `/Resources` dictionary:

| Category | Holds |
| --- | --- |
| `/Font` | Font dictionaries, referenced as `/F1 12 Tf` |
| `/XObject` | Images and reusable form XObjects, drawn with `Do` |
| `/ColorSpace` | Named colour spaces (`/ICCBased`, `/Separation`, …) |
| `/Pattern` | Tiling and shading patterns |
| `/Shading` | Gradients, painted with `sh` |
| `/ExtGState` | Graphics-state parameter sets, applied with `gs` (opacity, blend mode, line parameters) |
| `/Properties` | Property dictionaries for marked content (`BDC`) |
| `/ProcSet` | Legacy procedure sets; ignorable in modern files |

The resources dictionary can be an indirect object or written inline in the
page. This tool parses both, so `/Resources << /Font << /F1 12 0 R >> >>`
resolves to a clickable font object either way.

## Content streams and operators

The actual drawing instructions are a **content stream**: a sequence of
operands followed by an operator, in postfix order.

```
q                       % save graphics state
1 0 0 1 72 700 cm       % translate
BT                      % begin text
  /F1 12 Tf             % font and size
  (Hello) Tj            % show text
ET
0.8 0.1 0.1 RG          % stroking colour
72 200 228 120 re       % rectangle path
S                       % stroke it
Q                       % restore state
```

A page may have several content streams (`/Contents` is an array); readers
concatenate them in order and treat the result as one stream. That is why
inserting text with a library often adds a stream rather than rewriting the
existing one.

The **decompiled view** in this tool parses that stream and lists each
operator with its operands, byte offset and a description. Inline images
(`BI … ID <bytes> EI`) are recognised: their dictionary is parsed and the byte
count reported, without dumping raw bytes into the listing.

The most common operators, grouped:

| Group | Operators |
| --- | --- |
| Graphics state | `q`, `Q`, `cm`, `w`, `J`, `j`, `M`, `d`, `gs`, `ri`, `i` |
| Path construction | `m`, `l`, `c`, `v`, `y`, `h`, `re` |
| Path painting | `S`, `s`, `f`, `f*`, `B`, `B*`, `b`, `b*`, `n` |
| Clipping | `W`, `W*` |
| Text | `BT`, `ET`, `Tf`, `Td`, `TD`, `Tm`, `T*`, `Tc`, `Tw`, `Tz`, `TL`, `Ts`, `Tr`, `Tj`, `TJ`, `'`, `"` |
| Colour | `CS`, `cs`, `SC`, `SCN`, `sc`, `scn`, `G`, `g`, `RG`, `rg`, `K`, `k` |
| XObjects and shading | `Do`, `sh`, `BI`/`ID`/`EI` |
| Marked content | `MP`, `DP`, `BMC`, `BDC`, `EMC` |

## Text: how characters get on the page

`Tj` and `TJ` do not carry Unicode. They carry **character codes** that index
into the current font's encoding; turning them back into readable text needs
the font's `/Encoding` and, for subsetted or CID fonts, its `/ToUnicode` CMap.
MuPDF does that work, which is why the tool can report spans of real text with
per-character bounding boxes.

Consequences worth knowing:

- A font without a usable `/ToUnicode` map may extract as mojibake or as
  nothing, even though the page looks fine — the glyphs are drawn correctly but
  their meaning is not recorded.
- **Subset** fonts have a six-letter prefix (`ABCDEF+Helvetica`) meaning only
  the used glyphs were embedded. The tool reports the prefix separately.
- A **scanned page** has no text operators at all: it is one big image. There
  is nothing to extract without OCR, and the tool says so instead of showing an
  empty result.
- Reading order in the extracted text is MuPDF's block order, which follows the
  content stream rather than any logical structure. For genuinely logical
  order, a tagged PDF's structure tree is the authority.

Span **flags** reported by MuPDF describe how the glyphs are drawn:
superscript, italic, serifed, monospaced, bold — derived from the font, not
from a style attribute in the file.

## Images

An image is normally an **XObject** (`/Subtype /Image`) referenced from
`/Resources /XObject` and painted with `Do` after a `cm` that positions and
scales it. The image dictionary carries `/Width`, `/Height`,
`/BitsPerComponent`, `/ColorSpace`, `/Filter`, optionally `/SMask` (a soft mask
holding per-pixel alpha), `/Mask`, `/Decode` and `/Interpolate`.

Two things follow:

- The **pixel size** and the **placement size** are unrelated. A 4 × 3 pixel
  image can be stretched over half a page; the effective DPI is derived from
  the placement matrix, and the tool reports both the stored pixel dimensions
  and the placement rectangle and matrix.
- The **same image can be placed many times**. The tool stores its bytes once
  per xref and records every placement separately.

An **inline image** (`BI … ID … EI`) lives inside the content stream and has no
object number, so it cannot be referenced or deduplicated; the tool stores each
occurrence separately and marks it `inline`.

## Vector graphics

Paths are built from move/line/curve/rectangle operators and then painted:
filled, stroked, both, or used as a clip. Paint parameters come from the
graphics state: colour (in the current colour space), line width, dash pattern,
line cap and join, alpha from `/ExtGState`.

MuPDF groups these into path objects, which the tool reports with their full
item list — each `l`, `c`, `re` or quad with its coordinates — plus fill and
stroke colours converted to both component values and a hex approximation.

## Annotations, links and form fields

**Annotations** are objects attached to a page through its `/Annots` array,
each with a `/Subtype` (`Text`, `Highlight`, `Square`, `FreeText`, `Stamp`,
`FileAttachment`, `Widget`, …), a `/Rect`, appearance streams (`/AP`) and
type-specific keys. They live outside the content stream: deleting an
annotation does not change what the page draws.

**Links** are annotations of subtype `/Link` with either a URI action or a
destination inside the document.

**Form fields** are `/Widget` annotations tied to the document's `/AcroForm`.
A field has a name, a type (text, checkbox, radio, combo, list, signature,
button), a value, flags, and appearance settings. Signature fields additionally
carry the signature dictionary — which this tool shows but does not validate.

## Logical structure and tagging

A **tagged** PDF carries a `/StructTreeRoot`: a tree of structure elements
(`/Document`, `/P`, `/H1`, `/Table`, `/Figure`, …) that maps content to
meaning, with `/Alt` text for accessibility and `/ActualText` for replacement
text. Marked-content operators (`BDC`/`EMC`) tie stream content to those
elements.

Most PDFs in the wild are **not** tagged. This is the single biggest reason a
document that looks structured has no machine-readable structure at all. The
tool walks the tree if it exists and says plainly when it does not.

## Metadata

Two parallel systems:

- The **Info dictionary** (`/Info` in the trailer): `Title`, `Author`,
  `Subject`, `Keywords`, `Creator` (the authoring application), `Producer`
  (the PDF writer), `CreationDate`, `ModDate`, `Trapped`.
- **XMP** (`/Metadata` in the catalog): an RDF/XML packet, usually a superset
  of the Info dictionary, holding Dublin Core, PDF/A identification,
  provenance, rights and application-specific schemas.

They can disagree. Both are reported verbatim, side by side.

## Encryption and permissions

An encrypted PDF has an `/Encrypt` dictionary and two passwords:

- the **user password** opens the document;
- the **owner password** additionally lifts the permission restrictions.

Permissions are a bitmask covering printing, modification, copying,
annotation, form filling, accessibility extraction, assembly and high-quality
printing. They are advisory: any reader that decrypts the file can ignore them.
This tool reports the method (`Standard V5 R6 256-bit AES`, for example) and
decodes the bitmask into named booleans; it needs the user password to open the
file and does not attempt to bypass anything.

## Coordinate systems

This matters more than any other convention in the project.

| | PDF file | PyMuPDF / this tool |
| --- | --- | --- |
| Origin | Bottom-left of the page | **Top-left of `page.rect`** |
| y axis | Grows upwards | **Grows downwards** |
| Rotation | Stored separately in `/Rotate` | **Already applied** |
| Unit | Point (1/72 inch) | Point (1/72 inch) |

Every bbox, rect, origin and matrix in this project's output is in the
right-hand column: **PyMuPDF space**. Each page report carries the matrices to
move between the two:

| Field | Maps |
| --- | --- |
| `transformation_matrix` | PDF space → PyMuPDF space |
| `transformation_matrix_inverse` | PyMuPDF space → PDF space |
| `rotation_matrix` | Unrotated → rotated |
| `derotation_matrix` | Rotated → unrotated |

A matrix `[a, b, c, d, e, f]` maps a point as
`x' = a·x + c·y + e`, `y' = b·x + d·y + f`.

For an unrotated A4 page the transformation matrix is `[1, 0, 0, -1, 0, 842]`:
flip y, then shift by the page height. So a box at the top of the page,
`[0, 0, 100, 100]` in PyMuPDF space, is `[0, 742, 100, 842]` in PDF space. The
page report includes `rect_in_pdf_space` as a worked example, and
`core.coordinates.rect_to_pdf_space()` does the conversion for you.

**Rendered pixels** are a third space. The renderer reports the `dpi` and
`zoom` it used, and pixels relate to points as:

```
pixel_x = (point_x - page_rect.x0) * zoom      zoom = dpi / 72
pixel_y = (point_y - page_rect.y0) * zoom
```

Subtracting the rect origin matters: a CropBox that does not start at `(0, 0)`
would otherwise shift every overlay.

## Where each concept appears in this tool

| Concept | Where to look |
| --- | --- |
| Objects, references | **Objects** tab; `objects/{xref}` API; `structure.catalog` |
| xref table, object streams | **Structure** tab → object model summary; `file.xref` |
| Trailer, `/ID` | **Structure** tab → trailer; `file.trailer`, `file.document_id` |
| Catalog | **Structure** tab; `structure.catalog` |
| Page tree | **Structure** tab; `structure.page_tree` |
| Page boxes, rotation | **Page** tab details panel; `page.boxes`, `page.rotation` |
| Resources | **Page** report `resources`; **Objects** tab |
| Content stream, operators | **Content stream** tab; `content_streams.operators` |
| Text, fonts | **Text** and **Fonts** tabs; `text`, `fonts` |
| Images | **Images** tab; `images.placements`, `images.objects` |
| Vector graphics | **Drawings** tab; `drawings` |
| Annotations, links, forms | **Annotations** and **Forms** tabs |
| Tagging | **Structure** tab → structure tree; `structure.struct_tree_root` |
| Metadata | **Metadata** tab; `metadata.info`, `metadata.xmp` |
| Encryption | **Metadata** tab; `encryption` |
