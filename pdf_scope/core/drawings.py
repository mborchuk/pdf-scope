"""Vector graphics extraction: paths, their coordinates and paint parameters."""

from __future__ import annotations

from typing import Any

import pymupdf

from .coordinates import point_to_list, rect_to_list

#: Path "type" values reported by MuPDF.
PATH_TYPES: dict[str, str] = {
    "f": "fill",
    "s": "stroke",
    "fs": "fill and stroke",
    "c": "clip",
    "cs": "clip and stroke",
    "clip": "clip",
}


def _convert_item(item: tuple[Any, ...]) -> dict[str, Any]:
    """Convert one path element into JSON-safe coordinates."""
    op = item[0]
    if op == "l":
        return {
            "op": "l",
            "kind": "line",
            "points": [point_to_list(item[1]), point_to_list(item[2])],
        }
    if op == "c":
        return {
            "op": "c",
            "kind": "cubic bezier",
            "points": [point_to_list(point) for point in item[1:5]],
        }
    if op == "re":
        return {
            "op": "re",
            "kind": "rectangle",
            "rect": rect_to_list(item[1]),
            "orientation": item[2] if len(item) > 2 else None,
        }
    if op == "qu":
        quad = item[1]
        return {
            "op": "qu",
            "kind": "quad",
            "points": [
                point_to_list(quad.ul),
                point_to_list(quad.ur),
                point_to_list(quad.ll),
                point_to_list(quad.lr),
            ],
        }
    return {"op": str(op), "kind": "unknown", "raw": [str(part) for part in item[1:]]}


def _color(value: Any) -> dict[str, Any] | None:
    """Normalise a MuPDF colour tuple (0..1 floats) into floats plus hex."""
    if value is None:
        return None
    components = [round(float(component), 6) for component in value]
    if len(components) == 3:
        red, green, blue = (int(round(component * 255)) for component in components)
    elif len(components) == 1:
        red = green = blue = int(round(components[0] * 255))
    elif len(components) == 4:
        cyan, magenta, yellow, black = components
        red = int(round(255 * (1 - min(1.0, cyan + black))))
        green = int(round(255 * (1 - min(1.0, magenta + black))))
        blue = int(round(255 * (1 - min(1.0, yellow + black))))
    else:
        return {"components": components, "hex": None}
    return {"components": components, "hex": f"#{red:02x}{green:02x}{blue:02x}"}


def extract_drawings_range(
    page: pymupdf.Page,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return a window of the page's vector paths, plus the total count.

    A single CAD sheet can hold hundreds of thousands of paths, which is far more
    than any report should inline, so callers take a window. ``index`` on each
    path is its real position on the page, not its position in the window.
    """
    try:
        paths = page.get_drawings()
    except Exception as exc:
        return {
            "items": [{"error": f"vector graphics unavailable: {exc}"}],
            "total": None,
            "offset": 0,
            "limit": limit,
            "truncated": False,
        }

    total = len(paths)
    start = max(0, int(offset))
    end = total if limit is None else min(total, start + max(0, int(limit)))
    window = paths[start:end]

    items: list[dict[str, Any]] = []
    for position, path in enumerate(window, start=start):
        path_type = path.get("type", "")
        items.append(
            {
                "index": position,
                "seqno": path.get("seqno"),
                "type": path_type,
                "type_label": PATH_TYPES.get(path_type, path_type),
                "rect": rect_to_list(path.get("rect")),
                "even_odd": path.get("even_odd"),
                "close_path": path.get("closePath"),
                "fill": _color(path.get("fill")),
                "fill_opacity": path.get("fill_opacity"),
                "stroke": _color(path.get("color")),
                "stroke_opacity": path.get("stroke_opacity"),
                "width": path.get("width"),
                "dashes": path.get("dashes"),
                "line_cap": list(path.get("lineCap", []) or []),
                "line_join": path.get("lineJoin"),
                "layer": path.get("layer") or None,
                "level": path.get("level"),
                "scissor": rect_to_list(path.get("scissor")),
                "items": [_convert_item(item) for item in path.get("items", [])],
            }
        )
    return {
        "items": items,
        "total": total,
        "offset": start,
        "limit": limit,
        "truncated": end < total,
    }


def extract_drawings(page: pymupdf.Page, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Every vector path on the page, or the first ``limit`` of them."""
    return extract_drawings_range(page, limit=limit)["items"]
