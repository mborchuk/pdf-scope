"""Whole-document content counts: how much of what is in this file.

The document report describes structure and metadata, which are cheap to read.
Counting *content* — characters, images, vector paths, annotations, tables — means
touching every page, and on CAD sheets a single page can take seconds. This module
therefore counts a range of pages at a time so a caller can walk a document in
chunks and show progress, and never inlines any payload: counts only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from .document import open_document
from .errors import PageNotFoundError
from .tables import TABLE_DETECTION_PATH_GUARD, extract_tables

#: Counted fields, in the order they are worth reading.
COUNT_FIELDS = (
    "characters",
    "words",
    "images",
    "drawings",
    "tables",
    "annotations",
    "links",
    "form_fields",
)


def _page_counts(page: pymupdf.Page, *, include_tables: bool) -> dict[str, Any]:
    counts: dict[str, Any] = {"page_number": page.number}
    try:
        text = page.get_text("text")
        counts["characters"] = len(text)
        counts["words"] = len(page.get_text("words"))
        counts["has_text_layer"] = bool(text.strip())
    except Exception as exc:
        counts["text_error"] = str(exc)
        counts["characters"] = counts["words"] = 0
        counts["has_text_layer"] = False

    try:
        counts["images"] = len(page.get_image_info(xrefs=True))
    except Exception as exc:
        counts["images_error"] = str(exc)
        counts["images"] = 0

    try:
        counts["drawings"] = len(page.get_drawings())
    except Exception as exc:
        counts["drawings_error"] = str(exc)
        counts["drawings"] = 0

    for key, getter in (
        ("annotations", page.annots),
        ("links", page.links),
        ("form_fields", page.widgets),
    ):
        try:
            counts[key] = sum(1 for _ in getter())
        except Exception as exc:
            counts[f"{key}_error"] = str(exc)
            counts[key] = 0

    if include_tables:
        detected = extract_tables(page, path_count=counts.get("drawings"), include_text=False)
        counts["tables"] = detected["count"]
        if detected.get("skipped"):
            counts["tables"] = None
            counts["tables_skipped"] = True
        elif detected.get("error"):
            counts["tables"] = None
            counts["tables_error"] = detected["error"]
    else:
        counts["tables"] = None
        counts["tables_skipped"] = True

    return counts


def document_content_summary(
    path: str | Path,
    *,
    password: str | None = None,
    offset: int = 0,
    limit: int | None = None,
    include_tables: bool = True,
) -> dict[str, Any]:
    """Count the content of a range of pages.

    Returns per-page counts plus the totals for that range. A caller aggregating
    several ranges adds the totals up; ``page_count`` says when it is done.
    """
    doc = open_document(path, password)
    try:
        page_count = doc.page_count
        start = max(0, int(offset))
        if start and start >= page_count:
            raise PageNotFoundError(f"page {start} does not exist (document has {page_count})")
        end = page_count if limit is None else min(page_count, start + max(0, int(limit)))

        pages: list[dict[str, Any]] = []
        for number in range(start, end):
            try:
                pages.append(_page_counts(doc.load_page(number), include_tables=include_tables))
            except Exception as exc:
                pages.append({"page_number": number, "error": str(exc)})

        totals = dict.fromkeys(COUNT_FIELDS, 0)
        unknown: set[str] = set()
        for entry in pages:
            for field in COUNT_FIELDS:
                value = entry.get(field)
                if value is None:
                    unknown.add(field)
                    continue
                totals[field] += value

        return {
            "page_count": page_count,
            "offset": start,
            "limit": limit,
            "pages_counted": len(pages),
            "complete": start == 0 and end == page_count,
            "pages_without_text_layer": sum(
                1 for entry in pages if entry.get("has_text_layer") is False
            ),
            "totals": totals,
            "partial_totals": sorted(unknown),
            "table_detection_path_guard": TABLE_DETECTION_PATH_GUARD,
            "pages": pages,
        }
    finally:
        doc.close()
