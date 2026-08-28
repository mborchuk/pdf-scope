"""Document-level extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_decompiler.core import analyze_document, render_page_png
from pdf_decompiler.core.errors import DocumentOpenError, PasswordRequiredError


def test_document_report_is_json_serialisable(rich_pdf: Path) -> None:
    report = analyze_document(rich_pdf, document_id="doc-1")
    json.dumps(report)  # must not raise
    assert report["schema_version"] == "1.0"
    assert report["identity"]["document_id"] == "doc-1"
    assert report["identity"]["source_name"] == "rich.pdf"
    assert len(report["identity"]["sha256"]) == 64


def test_metadata_and_file_structure(rich_pdf: Path) -> None:
    report = analyze_document(rich_pdf)
    assert report["metadata"]["info"]["title"] == "Rich fixture"
    assert report["metadata"]["info"]["author"] == "pytest"
    assert report["file"]["page_count"] == 2
    assert report["file"]["pdf_version"].startswith("PDF")
    assert report["file"]["catalog_xref"] >= 1
    assert "/Catalog" in report["file"]["xref"]["type_counts"]
    assert report["file"]["xref"]["xref_length"] > 1
    assert isinstance(report["file"]["trailer"], str)
    assert report["file"]["document_id"], "trailer /ID should be reported"


def test_pages_summaries(rich_pdf: Path) -> None:
    report = analyze_document(rich_pdf)
    assert len(report["pages"]) == 2
    first = report["pages"][0]
    assert first["rect"] == [0.0, 0.0, 400.0, 500.0]
    assert first["rotation"] == 0
    assert first["xref"] > 0


def test_page_summary_geometry_matches_render(rich_pdf: Path, rotated_pdf: Path) -> None:
    """The UI lays its page scroller out from these summaries before any page is
    extracted, so every summary must carry a size that matches what the renderer
    will produce — including on rotated pages."""
    for path in (rich_pdf, rotated_pdf):
        report = analyze_document(path)
        assert len(report["pages"]) == report["file"]["page_count"]
        for summary in report["pages"]:
            rect = summary["rect"]
            assert summary["width"] == pytest.approx(rect[2] - rect[0])
            assert summary["height"] == pytest.approx(rect[3] - rect[1])
            assert summary["width"] > 0 and summary["height"] > 0

            _, info = render_page_png(path, summary["page_number"], dpi=96)
            assert info["point_width"] == pytest.approx(summary["width"])
            assert info["point_height"] == pytest.approx(summary["height"])


def test_fonts_outline_attachments_and_forms(rich_pdf: Path) -> None:
    report = analyze_document(rich_pdf)

    base_fonts = {font["base_font"] for font in report["fonts"]["items"]}
    assert any("Helvetica" in name for name in base_fonts)
    for font in report["fonts"]["items"]:
        assert font["used_on_pages"], "each font records where it is used"
        assert "embedded" in font

    titles = [item["title"] for item in report["structure"]["outline"]]
    assert titles == ["First page", "Second page"]

    assert report["attachments"][0]["filename"] == "notes.txt"
    assert report["attachments"][0]["size"] == len(b"attached payload")

    fields = report["form"]["fields"]
    assert report["form"]["is_form_pdf"] is True
    assert fields[0]["field_name"] == "given_name"
    assert fields[0]["field_value"] == "Ada"


def test_structure_sections_present(rich_pdf: Path) -> None:
    report = analyze_document(rich_pdf)
    structure = report["structure"]
    assert structure["catalog"]["entries"]["Pages"]["xref"] > 0
    assert structure["page_tree"]["root"]["type"] == "/Pages"
    # The fixture is untagged: absence must be stated, not silently omitted.
    assert structure["struct_tree_root"] is None
    assert any("StructTreeRoot" in warning for warning in report["warnings"])
    assert report["known_limitations"], "limitations are always reported"


def test_encrypted_document_requires_password(encrypted_pdf: Path) -> None:
    with pytest.raises(PasswordRequiredError):
        analyze_document(encrypted_pdf)

    report = analyze_document(encrypted_pdf, password="user-pw")
    assert report["encryption"]["is_encrypted"] is True
    assert report["encryption"]["needs_password"] is True
    assert "AES" in (report["encryption"]["method"] or "")
    allowed = report["encryption"]["permissions"]["allowed"]
    assert allowed["print"] is True
    assert allowed["modify"] is False


def test_corrupt_document_fails_cleanly(corrupt_pdf: Path) -> None:
    with pytest.raises(DocumentOpenError):
        analyze_document(corrupt_pdf)
