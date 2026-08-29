"""Image extraction: bytes, properties and every placement on a page.

An image XObject referenced from several pages is stored once (keyed by xref)
while each placement is recorded separately with its own bbox and matrix.
Inline images (``BI ... ID ... EI``) have no xref; they are stored per
occurrence and flagged as inline.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pymupdf

from . import objects
from .coordinates import matrix_to_list, rect_to_list
from .errors import ImageDecodeError, ObjectNotFoundError

#: Colourspace component counts reported by MuPDF as integers.
COLORSPACE_NAMES: dict[int, str] = {0: "None", 1: "GRAY", 2: "RGB(2)", 3: "RGB", 4: "CMYK"}


def _image_object_properties(doc: pymupdf.Document, xref: int) -> dict[str, Any]:
    """Read the image XObject dictionary entries that describe encoding."""
    keys = (
        "Filter",
        "DecodeParms",
        "ColorSpace",
        "BitsPerComponent",
        "Width",
        "Height",
        "ImageMask",
        "Decode",
        "Interpolate",
        "SMask",
        "Mask",
        "Intent",
        "Name",
    )
    properties = {key: objects.key_value(doc, xref, key) for key in keys}
    return {key: value for key, value in properties.items() if value is not None}


def extract_image_object(
    doc: pymupdf.Document,
    xref: int,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Extract one image XObject: properties plus its bytes in original format."""
    record: dict[str, Any] = {"xref": xref, "inline": False}
    try:
        data = doc.extract_image(xref)
    except Exception as exc:
        record["error"] = f"image bytes could not be extracted by PyMuPDF: {exc}"
        record["object"] = _image_object_properties(doc, xref)
        return record

    payload: bytes = data.get("image", b"")
    record.update(
        {
            "width": data.get("width"),
            "height": data.get("height"),
            "ext": data.get("ext"),
            "colorspace_components": data.get("colorspace"),
            "colorspace": COLORSPACE_NAMES.get(data.get("colorspace"), "unknown"),
            "colorspace_name": data.get("cs-name"),
            "bits_per_component": data.get("bpc"),
            "xres": data.get("xres"),
            "yres": data.get("yres"),
            "dpi": [data.get("xres"), data.get("yres")],
            "byte_size": len(payload),
            "smask_xref": data.get("smask") or None,
            "has_transparency": bool(data.get("smask")),
            "object": _image_object_properties(doc, xref),
        }
    )

    if output_dir is not None and payload:
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"image-xref{xref}.{data.get('ext') or 'bin'}"
        target = output_dir / filename
        if not target.exists():
            target.write_bytes(payload)
        record["file"] = filename
    return record


#: Longest side of a preview when the caller does not ask for a specific size.
PREVIEW_MAX_SIDE = 2000


def image_preview_png(
    path: str | Path,
    xref: int,
    *,
    password: str | None = None,
    max_side: int | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Decode one image XObject and re-encode it as PNG.

    Stored image bytes keep the format the PDF used, which is the honest thing to
    hand out for download but is not always something a browser can display:
    JPEG 2000 (``.jpx``/``.jp2``), JBIG2 and CCITT are common in scanned files and
    only Safari renders JPEG 2000 at all. This gives callers a lossless-container
    PNG of the same pixels for on-screen use, while the original bytes stay
    untouched on disk.

    Returns the PNG bytes and a small report of what was decoded, including
    ``original_ext`` so a caller can say which format the source was in.
    """
    from .document import open_document

    limit = PREVIEW_MAX_SIDE if max_side is None else max(1, int(max_side))
    doc = open_document(path, password)
    try:
        if xref < 1 or xref >= doc.xref_length():
            raise ObjectNotFoundError(f"xref {xref} does not exist in this document")
        if objects.key_value(doc, xref, "Subtype") != "/Image":
            raise ObjectNotFoundError(f"xref {xref} is not an image XObject")

        original_ext = None
        with contextlib.suppress(Exception):
            original_ext = doc.extract_image(xref).get("ext")

        # Pixmap() decodes through MuPDF, so every format MuPDF can read works,
        # including the ones no browser can.
        try:
            pixmap = pymupdf.Pixmap(doc, xref)
        except Exception as exc:
            raise ImageDecodeError(
                f"image xref {xref}"
                f"{f' ({original_ext})' if original_ext else ''} could not be decoded: {exc}"
            ) from exc
        source_width, source_height = pixmap.width, pixmap.height

        try:
            # CMYK and other multi-component spaces have no PNG representation.
            if pixmap.colorspace is not None and pixmap.colorspace.n > 3:
                pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)

            scale = min(1.0, limit / max(source_width, source_height, 1))
            if scale < 1.0:
                pixmap = pymupdf.Pixmap(
                    pixmap,
                    max(1, int(source_width * scale)),
                    max(1, int(source_height * scale)),
                    None,
                )
            png = pixmap.tobytes("png")
        except Exception as exc:
            raise ImageDecodeError(f"image xref {xref} could not be encoded as PNG: {exc}") from exc

        return png, {
            "xref": xref,
            "original_ext": original_ext,
            "source_pixels": [source_width, source_height],
            "preview_pixels": [pixmap.width, pixmap.height],
            "colorspace": pixmap.colorspace.name if pixmap.colorspace else "alpha only",
            "has_alpha": bool(pixmap.alpha),
            "max_side": limit,
        }
    finally:
        doc.close()


def _inline_image_blocks(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Image blocks from ``get_text('dict')``, used to recover inline image bytes."""
    return [block for block in page.get_text("dict").get("blocks", []) if block.get("type") == 1]


def extract_page_images(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Return placements for one page plus the deduplicated image objects used."""
    placements: list[dict[str, Any]] = []
    used: dict[int, dict[str, Any]] = {}
    inline_images: list[dict[str, Any]] = []

    try:
        infos = page.get_image_info(hashes=False, xrefs=True)
    except Exception as exc:
        return {
            "placements": [],
            "objects": [],
            "inline_images": [],
            "error": f"image placements unavailable: {exc}",
        }

    inline_blocks = None
    for index, info in enumerate(infos):
        xref = int(info.get("xref", 0) or 0)
        placement: dict[str, Any] = {
            "index": index,
            "xref": xref or None,
            "inline": xref == 0,
            "bbox": rect_to_list(info.get("bbox")),
            "transform": matrix_to_list(info.get("transform")),
            "width": info.get("width"),
            "height": info.get("height"),
            "colorspace_components": info.get("colorspace"),
            "colorspace_name": info.get("cs-name"),
            "bits_per_component": info.get("bpc"),
            "xres": info.get("xres"),
            "yres": info.get("yres"),
            "stored_size": info.get("size"),
            "has_mask": info.get("has-mask"),
        }

        if xref:
            if xref not in used:
                used[xref] = extract_image_object(doc, xref, output_dir)
            placement["file"] = used[xref].get("file")
        else:
            if inline_blocks is None:
                inline_blocks = _inline_image_blocks(page)
            block = _match_inline_block(inline_blocks, info.get("bbox"))
            inline_record = _store_inline_image(block, page.number, len(inline_images), output_dir)
            inline_images.append(inline_record)
            placement["file"] = inline_record.get("file")
            placement["inline_index"] = len(inline_images) - 1
        placements.append(placement)

    return {
        "placements": placements,
        "objects": list(used.values()),
        "inline_images": inline_images,
    }


def _match_inline_block(blocks: list[dict[str, Any]], bbox: Any) -> dict[str, Any] | None:
    """Find the ``dict`` image block covering the same area as a placement."""
    if bbox is None:
        return None
    target = rect_to_list(bbox)
    best: dict[str, Any] | None = None
    best_delta = 1.0
    for block in blocks:
        candidate = rect_to_list(block.get("bbox"))
        if candidate is None or target is None:
            continue
        delta = sum(abs(a - b) for a, b in zip(candidate, target, strict=False))
        if delta < best_delta:
            best, best_delta = block, delta
    return best


def _store_inline_image(
    block: dict[str, Any] | None,
    page_number: int,
    index: int,
    output_dir: Path | None,
) -> dict[str, Any]:
    """Persist an inline image's bytes, when MuPDF made them available."""
    record: dict[str, Any] = {"inline": True, "page": page_number, "index": index}
    if block is None:
        record["error"] = "inline image detected on the page, but MuPDF did not expose its bytes"
        return record
    payload = block.get("image") or b""
    record.update(
        {
            "width": block.get("width"),
            "height": block.get("height"),
            "ext": block.get("ext"),
            "colorspace_components": block.get("colorspace"),
            "bits_per_component": block.get("bpc"),
            "xres": block.get("xres"),
            "yres": block.get("yres"),
            "byte_size": len(payload),
            "bbox": rect_to_list(block.get("bbox")),
            "transform": matrix_to_list(block.get("transform")),
        }
    )
    if output_dir is not None and payload:
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"image-inline-p{page_number}-{index}.{block.get('ext') or 'bin'}"
        (output_dir / filename).write_bytes(payload)
        record["file"] = filename
    return record
