"""Page-level extraction: text, images, drawings, annotations, coordinates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_decompiler.core import analyze_page, image_preview_png, render_page_png
from pdf_decompiler.core.coordinates import rect_to_pdf_space
from pdf_decompiler.core.errors import ObjectNotFoundError


def test_text_granularities_and_font_details(rich_pdf: Path) -> None:
    page = analyze_page(rich_pdf, 0, document_id="doc-1")
    json.dumps(page)

    text = page["text"]
    assert text["has_text_layer"] is True
    assert "Hello decompiler" in text["plain"]
    assert any("Hello" in block["text"] for block in text["blocks"])
    assert any(word["text"] == "decompiler" for word in text["words"])

    spans = [
        span
        for block in text["structure"]["blocks"]
        if block["type"] == "text"
        for line in block["lines"]
        for span in line["spans"]
    ]
    first = next(span for span in spans if "Hello" in span["text"])
    assert first["size"] == 14
    assert "Helvetica" in first["font"]
    assert len(first["bbox"]) == 4
    assert first["color"]["hex"].startswith("#")
    assert first["chars"], "rawdict characters must be present"
    assert first["chars"][0]["c"] == "H"
    assert len(first["chars"][0]["bbox"]) == 4

    bold = next(span for span in spans if "second line" in span["text"])
    assert bold["font_flags"]["bold"] is True


def test_images_placements_and_files(rich_pdf: Path, tmp_path: Path) -> None:
    page = analyze_page(rich_pdf, 0, image_dir=tmp_path)
    placements = page["images"]["placements"]
    assert len(placements) == 1
    placement = placements[0]
    assert placement["width"] == 4 and placement["height"] == 3
    assert placement["bbox"][0] >= 219 and placement["bbox"][2] <= 321
    assert placement["bits_per_component"] == 8

    obj = page["images"]["objects"][0]
    assert obj["ext"] in {"png", "jpeg", "jpx", "bmp"}
    assert obj["byte_size"] > 0
    assert (tmp_path / obj["file"]).exists()
    assert obj["object"]["Width"] == "4"


def test_image_preview_is_always_png(rich_pdf: Path, scanned_pdf: Path) -> None:
    """Stored bytes keep the PDF's own format, which browsers cannot always draw
    (JPEG 2000 in scanned files is the usual case). The preview must therefore be
    PNG for every image, whatever the stored format is."""
    for path in (rich_pdf, scanned_pdf):
        page = analyze_page(path, 0)
        xref = page["images"]["placements"][0]["xref"]

        png, info = image_preview_png(path, xref)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert info["xref"] == xref
        assert info["preview_pixels"] == info["source_pixels"]
        assert info["colorspace"], "the decoded colourspace is always reported"


def test_image_preview_downscales_to_max_side(scanned_pdf: Path) -> None:
    page = analyze_page(scanned_pdf, 0)
    xref = page["images"]["placements"][0]["xref"]

    _, full = image_preview_png(scanned_pdf, xref)
    _, small = image_preview_png(scanned_pdf, xref, max_side=4)
    assert max(full["source_pixels"]) > 4
    assert max(small["preview_pixels"]) == 4
    assert small["source_pixels"] == full["source_pixels"]


def test_region_render_covers_only_the_requested_rectangle(rich_pdf: Path) -> None:
    """Images with no extractable bytes (inline ones, or any MuPDF cannot tie to
    an xref) are previewed by rendering their rectangle of the page, so a clipped
    render must report and rasterise exactly that rectangle."""
    page = analyze_page(rich_pdf, 0)
    bbox = page["images"]["placements"][0]["bbox"]

    png, info = render_page_png(rich_pdf, 0, dpi=144, clip=bbox)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert info["clip"] == [pytest.approx(value, abs=0.01) for value in bbox]
    assert info["point_width"] == pytest.approx(bbox[2] - bbox[0], abs=0.01)
    assert info["point_height"] == pytest.approx(bbox[3] - bbox[1], abs=0.01)
    assert info["pixel_width"] == pytest.approx((bbox[2] - bbox[0]) * 2, abs=2)
    assert info["page_point_size"] == [400.0, 500.0]

    full = render_page_png(rich_pdf, 0, dpi=144)[1]
    assert info["pixel_width"] < full["pixel_width"]


def test_region_render_is_clamped_to_the_page(rich_pdf: Path) -> None:
    _, info = render_page_png(rich_pdf, 0, dpi=72, clip=[-100, -100, 10_000, 10_000])
    assert info["clip"] == [0.0, 0.0, 400.0, 500.0]

    with pytest.raises(ValueError, match="does not intersect"):
        render_page_png(rich_pdf, 0, clip=[900, 900, 1000, 1000])
    with pytest.raises(ValueError, match="four numbers"):
        render_page_png(rich_pdf, 0, clip=[1, 2, 3])


def test_image_preview_rejects_a_non_image_xref(rich_pdf: Path) -> None:
    """The core wraps PyMuPDF's own errors, so the web layer can map them."""
    with pytest.raises(ObjectNotFoundError, match="not an image"):
        image_preview_png(rich_pdf, 1)  # the catalog is not an image
    with pytest.raises(ObjectNotFoundError, match="does not exist"):
        image_preview_png(rich_pdf, 10_000)


def test_drawings_carry_coordinates_and_colours(rich_pdf: Path) -> None:
    page = analyze_page(rich_pdf, 0)
    paths = page["drawings"]
    assert paths, "fixture draws a rectangle and a line"

    rect_path = next(path for path in paths if any(item["op"] == "re" for item in path["items"]))
    assert rect_path["fill"]["hex"] == "#0000ff"
    assert rect_path["stroke"]["hex"] == "#ff0000"
    assert rect_path["width"] == 2.0
    assert rect_path["items"][0]["rect"] == [50.0, 200.0, 200.0, 300.0]

    line_path = next(path for path in paths if any(i["op"] == "l" for i in path["items"]))
    assert line_path["items"][0]["points"][0] == [20.0, 320.0]


def test_annotations_links_widgets(rich_pdf: Path) -> None:
    page = analyze_page(rich_pdf, 0)
    annot = page["annotations"][0]
    assert annot["type"] == "Highlight"
    assert annot["info"]["content"] == "a highlight"
    assert annot["xref"] > 0

    link = page["links"][0]
    assert link["uri"] == "https://example.org"
    assert len(link["rect"]) == 4

    widget = page["widgets"][0]
    assert widget["field_name"] == "given_name"
    assert widget["field_value"] == "Ada"


def test_content_stream_operators(rich_pdf: Path) -> None:
    page = analyze_page(rich_pdf, 0)
    streams = page["content_streams"]
    assert streams["stream_count"] >= 1
    ops = [item["op"] for item in streams["operators"]]
    assert "BT" in ops and "ET" in ops and "re" in ops and "Do" in ops
    # MuPDF writes text with TJ (positioned show text) for this fixture.
    show_text = next(item for item in streams["operators"] if item["op"] in ("Tj", "TJ"))
    assert show_text["operands"], "show-text operators carry their string operands"
    assert "show text" in show_text["description"]
    assert streams["operator_counts"][show_text["op"]] >= 1


def test_resources_and_page_dictionary(rich_pdf: Path) -> None:
    page = analyze_page(rich_pdf, 0)
    categories = page["resources"]["categories"]
    assert "Font" in categories and "XObject" in categories
    font_member = categories["Font"]["members"][0]
    assert font_member["name"].startswith("/")
    assert font_member["xref"] > 0

    dictionary = page["page"]["dictionary"]
    assert dictionary["type"] == "/Page"
    assert "Contents" in dictionary["entries"]
    assert dictionary["references"]


def test_coordinates_pdf_space_conversion(rich_pdf: Path) -> None:
    page = analyze_page(rich_pdf, 0)
    matrix = page["page"]["transformation_matrix"]
    rect = page["page"]["boxes"]["rect"]
    # A box at the top of the page in MuPDF space sits at the top in PDF space too,
    # but expressed from a bottom-left origin.
    converted = rect_to_pdf_space([0.0, 0.0, 100.0, 100.0], matrix)
    assert converted == [0.0, rect[3] - 100.0, 100.0, rect[3]]
    assert page["page"]["rect_in_pdf_space"] == rect


def test_rotated_page_boxes_align(rotated_pdf: Path) -> None:
    page = analyze_page(rotated_pdf, 0)
    assert page["page"]["rotation"] == 90
    # page.rect is the rotated, visible area: width and height swap.
    rect = page["page"]["boxes"]["rect"]
    assert round(rect[2] - rect[0]) == 211
    assert round(rect[3] - rect[1]) == 333
    for block in page["text"]["structure"]["blocks"]:
        x0, y0, x1, y1 = block["bbox"]
        assert rect[0] - 1 <= x0 <= x1 <= rect[2] + 1
        assert rect[1] - 1 <= y0 <= y1 <= rect[3] + 1


def test_scanned_page_reports_missing_text_layer(scanned_pdf: Path) -> None:
    page = analyze_page(scanned_pdf, 0)
    assert page["text"]["has_text_layer"] is False
    assert "no text layer" in page["text"]["note"].lower()
    assert page["images"]["placements"], "the scan itself is still extracted"
