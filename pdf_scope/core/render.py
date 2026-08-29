"""Page rendering used by the UI to draw bounding-box overlays in place.

The renderer reports the exact scale it used so the browser can map PDF points
onto rendered pixels: ``pixel = point * zoom`` with ``zoom = dpi / 72``.

A render can be limited to a rectangle of the page (``clip``). That is how the
UI previews images whose own bytes cannot be extracted — an inline image, or one
MuPDF cannot tie to an xref: the pixels come from rasterising that region of the
page instead, which is always possible.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pymupdf

from .document import open_document
from .errors import PageNotFoundError

DEFAULT_DPI = 120
MAX_DPI = 400


def render_page_png(
    path: str | Path,
    page_number: int,
    *,
    dpi: int = DEFAULT_DPI,
    password: str | None = None,
    annotations: bool = True,
    clip: Sequence[float] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Render one page, or one rectangle of it, to PNG bytes with scale info."""
    dpi = max(24, min(int(dpi), MAX_DPI))
    doc = open_document(path, password)
    try:
        if page_number < 0 or page_number >= doc.page_count:
            raise PageNotFoundError(f"page {page_number} does not exist")
        page = doc.load_page(page_number)

        clip_rect = None
        if clip is not None:
            if len(clip) != 4:
                raise ValueError("clip must be four numbers: x0,y0,x1,y1")
            # Normalise, then keep it inside the page: MuPDF renders an empty
            # pixmap for a rectangle that lies outside page.rect.
            requested = pymupdf.Rect(*(float(value) for value in clip))
            requested.normalize()
            clip_rect = requested & page.rect
            if clip_rect.is_empty:
                raise ValueError("clip does not intersect the page rectangle")

        pixmap = page.get_pixmap(dpi=dpi, annots=annotations, clip=clip_rect)
        info = {
            "dpi": dpi,
            "zoom": dpi / 72.0,
            "pixel_width": pixmap.width,
            "pixel_height": pixmap.height,
            "point_width": round((clip_rect or page.rect).width, 4),
            "point_height": round((clip_rect or page.rect).height, 4),
            "rotation": page.rotation,
            "origin": "top-left, matching all reported bounding boxes",
        }
        if clip_rect is not None:
            info["clip"] = [round(value, 4) for value in clip_rect]
            info["page_point_size"] = [round(page.rect.width, 4), round(page.rect.height, 4)]
        return pixmap.tobytes("png"), info
    finally:
        doc.close()
