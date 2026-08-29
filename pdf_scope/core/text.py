"""Text extraction at every granularity PyMuPDF offers.

Granularities produced per page:

* ``plain``      -- ``page.get_text("text")``, reading order preserved
* ``blocks``     -- block level with bbox and block type
* ``words``      -- word level with bbox and block/line/word index
* ``structured`` -- ``dict`` output: blocks -> lines -> spans (font, size,
  colour, flags)
* ``raw``        -- ``rawdict`` output: spans -> individual characters with
  their own bbox and origin

All bounding boxes are in PyMuPDF space (see ``coordinates``).
"""

from __future__ import annotations

from typing import Any

import pymupdf

from .coordinates import point_to_list, rect_to_list

#: Font flag bits reported by MuPDF on each span.
FONT_FLAGS: dict[str, int] = {
    "superscript": 1 << 0,
    "italic": 1 << 1,
    "serifed": 1 << 2,
    "monospaced": 1 << 3,
    "bold": 1 << 4,
}

#: Additional style bits reported on each span as ``char_flags``.
CHAR_FLAGS: dict[str, int] = {
    "strikeout": 1 << 0,
    "underline": 1 << 1,
    "synthetic_bold": 1 << 2,
    "filled": 1 << 3,
    "stroked": 1 << 4,
    "clipped": 1 << 5,
}


def decode_flags(value: int, table: dict[str, int]) -> dict[str, bool]:
    """Expand a bitmask into named booleans."""
    return {name: bool(value & bit) for name, bit in table.items()}


def color_to_rgb(value: int | None) -> dict[str, Any] | None:
    """Convert MuPDF's packed sRGB integer into components and a hex string."""
    if value is None:
        return None
    value = int(value) & 0xFFFFFF
    red, green, blue = (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF
    return {
        "int": value,
        "hex": f"#{red:02x}{green:02x}{blue:02x}",
        "rgb": [red, green, blue],
        "rgb_float": [round(red / 255, 6), round(green / 255, 6), round(blue / 255, 6)],
    }


def extract_text(page: pymupdf.Page) -> dict[str, Any]:
    """Return every text granularity for one page."""
    plain = page.get_text("text")
    structured = page.get_text("dict")
    raw = page.get_text("rawdict")

    # "blocks" output is a list of (x0, y0, x1, y1, text, block_no, block_type).
    blocks = [
        {
            "index": index,
            "number": block[5] if len(block) > 5 else index,
            "type": "text" if (len(block) > 6 and block[6] == 0) else "image",
            "bbox": rect_to_list(block[:4]),
            "text": block[4] if len(block) > 4 else "",
        }
        for index, block in enumerate(page.get_text("blocks"))
    ]

    words = [
        {
            "bbox": rect_to_list(word[:4]),
            "text": word[4],
            "block": word[5],
            "line": word[6],
            "word": word[7],
        }
        for word in page.get_text("words")
    ]

    text_blocks = _convert_blocks(structured, raw)
    character_count = sum(
        len(span["text"])
        for block in text_blocks
        if block["type"] == "text"
        for line in block["lines"]
        for span in line["spans"]
    )

    return {
        "has_text_layer": bool(plain.strip()),
        "plain": plain,
        "character_count": character_count,
        "blocks": blocks,
        "words": words,
        "structure": {
            "width": structured.get("width"),
            "height": structured.get("height"),
            "blocks": text_blocks,
        },
        "note": (
            "No text layer found on this page. The page is most likely a scan or pure "
            "vector artwork; PyMuPDF performs no OCR, so there is nothing to extract."
            if not plain.strip()
            else None
        ),
    }


def _convert_blocks(structured: dict[str, Any], raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge ``dict`` and ``rawdict`` output into one block/line/span/char tree."""
    raw_blocks = raw.get("blocks", [])
    out: list[dict[str, Any]] = []

    for index, block in enumerate(structured.get("blocks", [])):
        raw_block = raw_blocks[index] if index < len(raw_blocks) else {}
        if block.get("type") != 0:
            out.append(
                {
                    "index": index,
                    "number": block.get("number"),
                    "type": "image",
                    "bbox": rect_to_list(block.get("bbox")),
                    "image": {
                        "width": block.get("width"),
                        "height": block.get("height"),
                        "ext": block.get("ext"),
                        "colorspace": block.get("colorspace"),
                        "bpc": block.get("bpc"),
                        "xres": block.get("xres"),
                        "yres": block.get("yres"),
                        "size": block.get("size"),
                        "transform": list(block.get("transform", []) or []),
                        "has_mask": block.get("mask") is not None,
                    },
                    "lines": [],
                }
            )
            continue

        raw_lines = raw_block.get("lines", [])
        lines: list[dict[str, Any]] = []
        for line_index, line in enumerate(block.get("lines", [])):
            raw_line = raw_lines[line_index] if line_index < len(raw_lines) else {}
            raw_spans = raw_line.get("spans", [])
            spans: list[dict[str, Any]] = []
            for span_index, span in enumerate(line.get("spans", [])):
                raw_span = raw_spans[span_index] if span_index < len(raw_spans) else {}
                flags = int(span.get("flags", 0))
                char_flags = int(span.get("char_flags", 0))
                spans.append(
                    {
                        "index": span_index,
                        "text": span.get("text", ""),
                        "bbox": rect_to_list(span.get("bbox")),
                        "origin": point_to_list(span.get("origin")),
                        "font": span.get("font"),
                        "size": span.get("size"),
                        "color": color_to_rgb(span.get("color")),
                        "alpha": span.get("alpha"),
                        "ascender": span.get("ascender"),
                        "descender": span.get("descender"),
                        "flags": flags,
                        "font_flags": decode_flags(flags, FONT_FLAGS),
                        "char_flags": char_flags,
                        "style_flags": decode_flags(char_flags, CHAR_FLAGS),
                        "bidi": span.get("bidi"),
                        "chars": [
                            {
                                "c": char.get("c"),
                                "bbox": rect_to_list(char.get("bbox")),
                                "origin": point_to_list(char.get("origin")),
                                "synthetic": char.get("synthetic"),
                            }
                            for char in raw_span.get("chars", [])
                        ],
                    }
                )
            lines.append(
                {
                    "index": line_index,
                    "bbox": rect_to_list(line.get("bbox")),
                    "wmode": line.get("wmode"),
                    "direction": list(line.get("dir", []) or []),
                    "spans": spans,
                }
            )

        out.append(
            {
                "index": index,
                "number": block.get("number"),
                "type": "text",
                "bbox": rect_to_list(block.get("bbox")),
                "lines": lines,
            }
        )
    return out


def page_text_markdown(page: pymupdf.Page, page_number: int) -> str:
    """Render one page's text as a small Markdown section (for downloads)."""
    body = page.get_text("text").rstrip()
    if not body:
        body = "_(no text layer on this page)_"
    return f"## Page {page_number + 1}\n\n{body}\n"
