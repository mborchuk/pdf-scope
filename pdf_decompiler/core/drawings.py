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


def extract_drawings(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Return every vector path on the page with coordinates and paint state."""
    try:
        paths = page.get_drawings()
    except Exception as exc:
        return [{"error": f"vector graphics unavailable: {exc}"}]

    result: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        path_type = path.get("type", "")
        result.append(
            {
                "index": index,
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
    return result
