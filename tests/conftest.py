"""Fixture PDFs, generated programmatically so the repository stays binary-free."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pymupdf
import pytest


def png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Build a tiny solid-colour PNG without extra dependencies."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(scope="session")
def rich_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two pages with text, vector art, an image, annotation, widget and more."""
    path = tmp_path_factory.mktemp("fixtures") / "rich.pdf"
    doc = pymupdf.open()

    page = doc.new_page(width=400, height=500)
    page.insert_text((72, 100), "Hello decompiler", fontname="helv", fontsize=14)
    page.insert_text((72, 140), "second line", fontname="hebo", fontsize=10)
    page.draw_rect(pymupdf.Rect(50, 200, 200, 300), color=(1, 0, 0), fill=(0, 0, 1), width=2)
    page.draw_line(pymupdf.Point(20, 320), pymupdf.Point(380, 320), color=(0, 0.5, 0), width=1.5)
    page.insert_image(pymupdf.Rect(220, 200, 320, 260), stream=png_bytes(4, 3, (255, 0, 0)))
    page.insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(20, 20, 200, 40),
            "uri": "https://example.org",
        }
    )
    annot = page.add_highlight_annot(pymupdf.Rect(70, 90, 220, 110))
    annot.set_info(content="a highlight", title="tester")
    annot.update()

    widget = pymupdf.Widget()
    widget.rect = pymupdf.Rect(50, 380, 250, 410)
    widget.field_name = "given_name"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_value = "Ada"
    page.add_widget(widget)

    second = doc.new_page(width=400, height=500)
    second.insert_text((60, 80), "page two text", fontname="helv", fontsize=12)

    doc.set_metadata({"title": "Rich fixture", "author": "pytest", "subject": "testing"})
    doc.set_toc([[1, "First page", 1], [2, "Second page", 2]])
    doc.embfile_add("notes.txt", b"attached payload", filename="notes.txt", desc="a note")
    doc.save(path)
    doc.close()
    return path


@pytest.fixture(scope="session")
def rotated_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A rotated page with a non-standard size."""
    path = tmp_path_factory.mktemp("fixtures") / "rotated.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=333, height=211)
    page.insert_text((40, 60), "rotated page", fontname="helv", fontsize=11)
    page.set_rotation(90)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture(scope="session")
def scanned_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An image-only page: no text layer at all."""
    path = tmp_path_factory.mktemp("fixtures") / "scanned.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(0, 0, 300, 300), stream=png_bytes(8, 8, (10, 200, 40)))
    doc.save(path)
    doc.close()
    return path


@pytest.fixture(scope="session")
def encrypted_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A document protected with a user password."""
    path = tmp_path_factory.mktemp("fixtures") / "encrypted.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "secret content", fontname="helv", fontsize=12)
    doc.save(
        path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-pw",
        user_pw="user-pw",
        permissions=int(pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_ACCESSIBILITY),
    )
    doc.close()
    return path


@pytest.fixture(scope="session")
def corrupt_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Bytes that only look like a PDF."""
    path = tmp_path_factory.mktemp("fixtures") / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not a pdf body at all\n%%EOF\n")
    return path


@pytest.fixture(scope="session")
def table_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A ruled grid with text in every cell, so table detection has real input."""
    path = tmp_path_factory.mktemp("fixtures") / "table.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)

    left, top, cell_width, cell_height = 40.0, 40.0, 100.0, 30.0
    columns, rows = 3, 4
    for row in range(rows + 1):
        y = top + row * cell_height
        page.draw_line(
            pymupdf.Point(left, y),
            pymupdf.Point(left + columns * cell_width, y),
            width=0.8,
        )
    for column in range(columns + 1):
        x = left + column * cell_width
        page.draw_line(
            pymupdf.Point(x, top),
            pymupdf.Point(x, top + rows * cell_height),
            width=0.8,
        )

    headers = ("Item", "Quantity", "Unit")
    body = (("Gravel", "120", "m3"), ("Topsoil", "45", "m3"), ("Kerb", "310", "m"))
    for column, label in enumerate(headers):
        page.insert_text(
            (left + column * cell_width + 6, top + 20), label, fontname="hebo", fontsize=10
        )
    for row, cells in enumerate(body, start=1):
        for column, value in enumerate(cells):
            page.insert_text(
                (left + column * cell_width + 6, top + row * cell_height + 20),
                value,
                fontname="helv",
                fontsize=10,
            )

    doc.save(path)
    doc.close()
    return path


@pytest.fixture(scope="session")
def second_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clearly different document, used for cross-contamination checks."""
    path = tmp_path_factory.mktemp("fixtures") / "second.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=250)
    page.insert_text((30, 60), "UNIQUE-SECOND-DOCUMENT", fontname="helv", fontsize=9)
    page.insert_image(pymupdf.Rect(20, 100, 80, 160), stream=png_bytes(2, 2, (0, 0, 255)))
    doc.set_metadata({"title": "Second fixture"})
    doc.save(path)
    doc.close()
    return path
