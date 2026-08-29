"""Annotations, links and form widgets present on a page."""

from __future__ import annotations

from typing import Any

import pymupdf

from .coordinates import rect_to_list
from .schema import jsonable


def _optional(obj: Any, name: str) -> Any:
    """Read an attribute that only exists for some annotation types."""
    try:
        return getattr(obj, name)
    except Exception:
        return None


def extract_annotations(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Return every annotation on the page with its geometry and properties."""
    items: list[dict[str, Any]] = []
    try:
        annots = list(page.annots())
    except Exception as exc:
        return [{"error": f"annotations unavailable: {exc}"}]

    for index, annot in enumerate(annots):
        try:
            type_number, type_name = annot.type[0], annot.type[1]
            record: dict[str, Any] = {
                "index": index,
                "xref": annot.xref,
                "type": type_name,
                "type_number": type_number,
                "rect": rect_to_list(annot.rect),
                "info": jsonable(annot.info),
                "flags": annot.flags,
                "colors": jsonable(annot.colors),
                "border": jsonable(_optional(annot, "border")),
                "opacity": _optional(annot, "opacity"),
                "blend_mode": _optional(annot, "blendmode"),
                "vertices": jsonable(_optional(annot, "vertices")),
                "line_ends": jsonable(_optional(annot, "line_ends")),
                "is_open": _optional(annot, "is_open"),
                "has_popup": _optional(annot, "has_popup"),
                "popup_rect": rect_to_list(_optional(annot, "popup_rect")),
                "irt_xref": _optional(annot, "irt_xref"),
                "language": _optional(annot, "language"),
                "appearance_bbox": rect_to_list(_optional(annot, "apn_bbox")),
                "file_info": jsonable(_optional(annot, "file_info")),
            }
        except Exception as exc:
            record = {"index": index, "error": str(exc)}
        items.append(record)
    return items


def extract_links(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Return link annotations with their targets."""
    try:
        links = page.get_links()
    except Exception as exc:
        return [{"error": f"links unavailable: {exc}"}]

    items: list[dict[str, Any]] = []
    for index, link in enumerate(links):
        record = jsonable(dict(link))
        record["index"] = index
        if "from" in link:
            record["rect"] = rect_to_list(link["from"])
        items.append(record)
    return items


def extract_widgets(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Return form field widgets on this page."""
    items: list[dict[str, Any]] = []
    try:
        widgets = list(page.widgets())
    except Exception as exc:
        return [{"error": f"form fields unavailable: {exc}"}]

    for index, widget in enumerate(widgets):
        try:
            items.append(
                {
                    "index": index,
                    "xref": widget.xref,
                    "field_name": widget.field_name,
                    "field_label": widget.field_label,
                    "field_type": widget.field_type,
                    "field_type_string": widget.field_type_string,
                    "field_value": jsonable(widget.field_value),
                    "field_flags": widget.field_flags,
                    "field_display": widget.field_display,
                    "is_signed": widget.is_signed,
                    "choice_values": jsonable(widget.choice_values),
                    "rect": rect_to_list(widget.rect),
                    "text_font": widget.text_font,
                    "text_fontsize": widget.text_fontsize,
                    "text_maxlen": widget.text_maxlen,
                    "border_style": widget.border_style,
                    "script": widget.script,
                }
            )
        except Exception as exc:
            items.append({"index": index, "error": str(exc)})
    return items
