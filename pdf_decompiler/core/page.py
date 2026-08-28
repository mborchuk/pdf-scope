"""Per-page analysis: page dictionary, resources, content stream, contents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from . import annotations as annots_module
from . import drawings as drawings_module
from . import images as images_module
from . import objects, text
from .contentstream import parse_content_stream
from .coordinates import COORDINATE_SPACE_NOTE, rect_to_list, rect_to_pdf_space
from .document import open_document, page_transform_matrices
from .errors import PageNotFoundError
from .schema import (
    CONTENT_STREAM_INLINE_LIMIT,
    CONTENT_STREAM_OPERATOR_LIMIT,
    PAGE_DRAWING_LIMIT,
    PAGE_OPERATOR_LIMIT,
    SCHEMA_VERSION,
)


def _page_dictionary(doc: pymupdf.Document, page: pymupdf.Page) -> dict[str, Any]:
    """The page object's own dictionary entries, as stored in the file."""
    return objects.describe_object(doc, page.xref)


def content_streams(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    *,
    inline_limit: int = CONTENT_STREAM_INLINE_LIMIT,
    operator_limit: int | None = PAGE_OPERATOR_LIMIT,
    include_operators: bool = True,
) -> dict[str, Any]:
    """Return the page content stream(s): raw sizes, decoded text and operators."""
    try:
        stream_xrefs = list(page.get_contents())
    except Exception:
        stream_xrefs = []

    streams: list[dict[str, Any]] = []
    for xref in stream_xrefs:
        entry: dict[str, Any] = {"xref": xref, "filter": objects.key_value(doc, xref, "Filter")}
        try:
            entry["raw_bytes"] = len(doc.xref_stream_raw(xref))
        except Exception as exc:
            entry["raw_bytes"] = None
            entry["raw_error"] = str(exc)
        try:
            entry["decoded_bytes"] = len(doc.xref_stream(xref))
        except Exception as exc:
            entry["decoded_bytes"] = None
            entry["decode_error"] = (
                f"MuPDF could not decode this stream ({exc}); its filter chain may be "
                "unsupported or the stream may be damaged"
            )
        streams.append(entry)

    try:
        combined = page.read_contents()
    except Exception as exc:
        return {
            "streams": streams,
            "error": f"content stream could not be read: {exc}",
            "decoded": None,
            "operators": None,
        }

    decoded_text = combined[:inline_limit].decode("utf-8", "replace")
    result: dict[str, Any] = {
        "streams": streams,
        "stream_count": len(stream_xrefs),
        "total_decoded_bytes": len(combined),
        "decoded": decoded_text,
        "decoded_truncated": len(combined) > inline_limit,
        "note": (
            "Streams are concatenated in page order and decoded by MuPDF. Download the "
            "full stream for the complete text when it is truncated here."
        ),
    }

    if include_operators:
        parsed = parse_content_stream(combined, operator_limit=operator_limit)
        result["operators"] = parsed["operators"]
        result["operator_counts"] = parsed["operator_counts"]
        result["operators_truncated"] = parsed["truncated"]
    return result


def analyze_page(
    path: str | Path,
    page_number: int,
    *,
    password: str | None = None,
    document_id: str | None = None,
    image_dir: str | Path | None = None,
    include_operators: bool = True,
    drawing_limit: int | None = PAGE_DRAWING_LIMIT,
) -> dict[str, Any]:
    """Produce the full report for a single page.

    Opens its own ``Document`` instance, so this function is safe to run in a
    separate process (PyMuPDF documents must not be shared).
    """
    doc = open_document(path, password)
    try:
        if page_number < 0 or page_number >= doc.page_count:
            raise PageNotFoundError(
                f"page {page_number} does not exist (document has {doc.page_count} pages)"
            )
        page = doc.load_page(page_number)
        matrices = page_transform_matrices(page)
        transformation = matrices["transformation_matrix"]

        boxes = {
            "rect": rect_to_list(page.rect),
            "mediabox": rect_to_list(page.mediabox),
            "cropbox": rect_to_list(page.cropbox),
            "artbox": rect_to_list(page.artbox),
            "bleedbox": rect_to_list(page.bleedbox),
            "trimbox": rect_to_list(page.trimbox),
        }

        image_output = Path(image_dir) if image_dir is not None else None
        image_data = images_module.extract_page_images(doc, page, image_output)
        # Vector paths are windowed: see PAGE_DRAWING_LIMIT for why.
        drawing_window = drawings_module.extract_drawings_range(page, limit=drawing_limit)

        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "document_id": document_id,
            "page_number": page_number,
            "label": page.get_label() or None,
            "coordinate_space": COORDINATE_SPACE_NOTE,
            "page": {
                "xref": page.xref,
                "rotation": page.rotation,
                "boxes": boxes,
                "rect_in_pdf_space": rect_to_pdf_space(boxes["rect"], transformation),
                "width": round(page.rect.width, 4),
                "height": round(page.rect.height, 4),
                **matrices,
                "dictionary": _page_dictionary(doc, page),
            },
            "resources": objects.page_resources(doc, page),
            "content_streams": content_streams(doc, page, include_operators=include_operators),
            "text": text.extract_text(page),
            "images": image_data,
            "drawings": drawing_window["items"],
            "drawings_info": {
                key: drawing_window[key] for key in ("total", "offset", "limit", "truncated")
            },
            "annotations": annots_module.extract_annotations(page),
            "links": annots_module.extract_links(page),
            "widgets": annots_module.extract_widgets(page),
            "xobjects": [
                {
                    "xref": item[0],
                    "name": f"/{item[1]}" if len(item) > 1 else None,
                    "raw": [str(part) for part in item],
                }
                for item in _safe_xobjects(page)
            ],
            "fonts": [
                {
                    "xref": item[0],
                    "font_file_extension": None if item[1] == "n/a" else item[1],
                    "embedded": item[1] != "n/a",
                    "subtype": item[2],
                    "base_font": item[3],
                    "resource_name": f"/{item[4]}" if item[4] else None,
                    "encoding": item[5] or None,
                    "referenced_by_xobject": item[6] if len(item) > 6 else None,
                }
                for item in _safe_fonts(page)
            ],
        }
        return report
    finally:
        doc.close()


def _safe_xobjects(page: pymupdf.Page) -> list[Any]:
    try:
        return list(page.get_xobjects())
    except Exception:
        return []


def _safe_fonts(page: pymupdf.Page) -> list[Any]:
    try:
        return list(page.get_fonts(full=True))
    except Exception:
        return []


def page_drawings(
    path: str | Path,
    page_number: int,
    *,
    offset: int = 0,
    limit: int | None = PAGE_DRAWING_LIMIT,
    password: str | None = None,
) -> dict[str, Any]:
    """A window of a page's vector paths, with the page's real total.

    The page report only inlines the first ``PAGE_DRAWING_LIMIT`` paths, because a
    CAD sheet can carry hundreds of thousands. This is how the rest is reached.
    """
    doc = open_document(path, password)
    try:
        if page_number < 0 or page_number >= doc.page_count:
            raise PageNotFoundError(f"page {page_number} does not exist")
        window = drawings_module.extract_drawings_range(
            doc.load_page(page_number), offset=offset, limit=limit
        )
        window["page_number"] = page_number
        return window
    finally:
        doc.close()


def page_operators(
    path: str | Path,
    page_number: int,
    *,
    offset: int = 0,
    limit: int | None = CONTENT_STREAM_OPERATOR_LIMIT,
    password: str | None = None,
) -> dict[str, Any]:
    """A window of a page's content-stream operators, with the exact total.

    The whole stream is lexed so the total is exact, but only the requested window
    is materialised, which keeps memory flat on the very long streams that CAD
    plotters produce.
    """
    doc = open_document(path, password)
    try:
        if page_number < 0 or page_number >= doc.page_count:
            raise PageNotFoundError(f"page {page_number} does not exist")
        data = doc.load_page(page_number).read_contents()
    finally:
        doc.close()

    parsed = parse_content_stream(
        data, operator_limit=limit, operator_offset=offset, count_all=True
    )
    parsed["page_number"] = page_number
    return parsed


def page_content_stream_bytes(
    path: str | Path,
    page_number: int,
    *,
    password: str | None = None,
    raw: bool = False,
) -> bytes:
    """Return the complete content stream of a page, decoded or raw."""
    doc = open_document(path, password)
    try:
        if page_number < 0 or page_number >= doc.page_count:
            raise PageNotFoundError(f"page {page_number} does not exist")
        page = doc.load_page(page_number)
        if not raw:
            return page.read_contents()
        chunks = []
        for xref in page.get_contents():
            try:
                chunks.append(doc.xref_stream_raw(xref))
            except Exception:
                continue
        return b"".join(chunks)
    finally:
        doc.close()
