"""Table detection.

MuPDF has no notion of a table: a table in a PDF is just lines and text that a
reader's eye groups together. PyMuPDF's ``Page.find_tables()`` reconstructs them
from ruling lines and text alignment, which makes the result a *detection*, not
something stored in the file — worth stating wherever it is shown.

Detection walks the page's vector graphics, so it costs what those cost: a few
hundredths of a second on an ordinary page, but 19 s on a CAD sheet carrying
265 507 paths. Pages above ``TABLE_DETECTION_PATH_GUARD`` paths are therefore
skipped, and say so, instead of stalling a request.
"""

from __future__ import annotations

from typing import Any

import pymupdf

from .coordinates import rect_to_list

#: Vector paths above which table detection is skipped.
TABLE_DETECTION_PATH_GUARD = 20_000

#: Cell rows kept per table when the extracted text is included.
TABLE_ROW_LIMIT = 300

#: Characters of the Markdown rendering kept per table.
TABLE_MARKDOWN_LIMIT = 40_000

DETECTION_NOTE = (
    "Tables are detected from ruling lines and text alignment by PyMuPDF, not read "
    "from the file: PDF has no table object. Treat the row and column counts as an "
    "interpretation of the layout."
)


def _header(header: Any) -> dict[str, Any]:
    try:
        return {
            "names": [str(name) if name is not None else None for name in (header.names or [])],
            "external": bool(header.external),
            "bbox": rect_to_list(pymupdf.Rect(header.bbox)) if header.bbox else None,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": f"header unavailable: {exc}"}


def extract_tables(
    page: pymupdf.Page,
    *,
    path_count: int | None = None,
    path_guard: int = TABLE_DETECTION_PATH_GUARD,
    include_text: bool = True,
) -> dict[str, Any]:
    """Detect the tables on a page.

    ``path_count`` lets a caller that already counted the page's vector paths
    reuse that number for the guard instead of paying for it twice.
    """
    result: dict[str, Any] = {"note": DETECTION_NOTE, "items": [], "count": 0, "skipped": False}

    if path_count is not None and path_count > path_guard:
        result["skipped"] = True
        result["skip_reason"] = (
            f"this page holds {path_count} vector paths, more than the "
            f"{path_guard} table detection walks; detection was skipped because it "
            "would take tens of seconds. Ask for it explicitly if you need it."
        )
        return result

    try:
        tables = list(page.find_tables().tables)
    except Exception as exc:
        result["error"] = f"table detection failed: {exc}"
        return result

    items: list[dict[str, Any]] = []
    for index, table in enumerate(tables):
        entry: dict[str, Any] = {
            "index": index,
            "bbox": rect_to_list(pymupdf.Rect(table.bbox)),
            "row_count": table.row_count,
            "col_count": table.col_count,
            "header": _header(table.header),
        }
        try:
            entry["cell_bboxes"] = [
                rect_to_list(pymupdf.Rect(cell)) if cell else None for cell in table.cells
            ]
        except Exception as exc:
            entry["cell_bboxes_error"] = str(exc)

        if include_text:
            try:
                rows = table.extract()
                entry["rows"] = [
                    [None if cell is None else str(cell) for cell in row]
                    for row in rows[:TABLE_ROW_LIMIT]
                ]
                entry["rows_truncated"] = len(rows) > TABLE_ROW_LIMIT
            except Exception as exc:
                entry["rows_error"] = f"cell text unavailable: {exc}"
            try:
                markdown = table.to_markdown()
                entry["markdown"] = markdown[:TABLE_MARKDOWN_LIMIT]
                entry["markdown_truncated"] = len(markdown) > TABLE_MARKDOWN_LIMIT
            except Exception as exc:
                entry["markdown_error"] = f"Markdown rendering unavailable: {exc}"
        items.append(entry)

    result["items"] = items
    result["count"] = len(items)
    return result
