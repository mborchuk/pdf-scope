"""Table detection and whole-document content counts."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from pdf_decompiler.core import analyze_page, document_content_summary
from pdf_decompiler.core.tables import TABLE_DETECTION_PATH_GUARD, extract_tables


def test_tables_are_detected_with_geometry_and_markdown(table_pdf: Path) -> None:
    page = analyze_page(table_pdf, 0)
    tables = page["tables"]
    assert tables["skipped"] is False
    assert tables["count"] == 1, "the fixture draws exactly one ruled grid"
    assert "detected" in tables["note"].lower(), "the report says this is a detection"

    table = tables["items"][0]
    assert table["row_count"] == 4 and table["col_count"] == 3
    assert table["bbox"][0] >= 39 and table["bbox"][2] <= 341
    assert table["header"]["names"][:3] == ["Item", "Quantity", "Unit"]
    assert len(table["cell_bboxes"]) == 12
    assert ["Gravel", "120", "m3"] in [
        [cell for cell in row if cell is not None] for row in table["rows"]
    ]
    assert "|Item|Quantity|Unit|" in table["markdown"].replace(" ", "")


def test_table_detection_is_skipped_on_path_heavy_pages(table_pdf: Path) -> None:
    """Detection walks the vector graphics, which costs 19 s on a 265 507-path CAD
    sheet, so a page that heavy is skipped with a reason instead of stalling."""
    doc = pymupdf.open(table_pdf)
    try:
        result = extract_tables(doc.load_page(0), path_count=TABLE_DETECTION_PATH_GUARD + 1)
    finally:
        doc.close()
    assert result["skipped"] is True
    assert result["count"] == 0
    assert str(TABLE_DETECTION_PATH_GUARD) in result["skip_reason"]


def test_content_summary_counts_every_page(rich_pdf: Path) -> None:
    summary = document_content_summary(rich_pdf)
    assert summary["page_count"] == 2
    assert summary["pages_counted"] == 2
    assert summary["complete"] is True

    totals = summary["totals"]
    assert totals["characters"] > 0
    assert totals["words"] > 0
    assert totals["images"] == 1
    assert totals["drawings"] >= 2
    assert totals["annotations"] >= 1
    assert totals["form_fields"] >= 1
    assert summary["pages_without_text_layer"] == 0

    first = summary["pages"][0]
    assert first["page_number"] == 0
    assert first["has_text_layer"] is True


def test_content_summary_windows_pages(rich_pdf: Path) -> None:
    second = document_content_summary(rich_pdf, offset=1, limit=1)
    assert second["pages_counted"] == 1
    assert second["complete"] is False
    assert second["pages"][0]["page_number"] == 1

    whole = document_content_summary(rich_pdf)
    assert second["totals"]["characters"] <= whole["totals"]["characters"]
    assert second["pages"][0] == whole["pages"][1]


def test_content_summary_reports_pages_without_text(scanned_pdf: Path) -> None:
    summary = document_content_summary(scanned_pdf)
    assert summary["pages_without_text_layer"] == 1
    assert summary["totals"]["images"] == 1
    assert summary["totals"]["characters"] == 0


def test_content_summary_can_skip_tables(table_pdf: Path) -> None:
    with_tables = document_content_summary(table_pdf)
    assert with_tables["totals"]["tables"] == 1
    assert with_tables["partial_totals"] == []

    without = document_content_summary(table_pdf, include_tables=False)
    assert without["pages"][0]["tables"] is None
    assert "tables" in without["partial_totals"]
