"""Bundle builder: pack a complete extraction of one document into a zip.

The bundle is written straight to disk so memory use stays flat regardless of
document size.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .document import analyze_document, open_document
from .images import extract_page_images
from .page import analyze_page
from .schema import dumps

ProgressCallback = Callable[[int, int], None]

BUNDLE_README = """PDF decompiler export
=====================

document.json           Document level report: identity, file structure, metadata,
                        fonts, outline, attachments, form fields, object model.
pages/page-NNNN.json    Per page report: page dictionary, resources, content stream
                        operators, text (blocks/lines/spans/chars), images, drawings,
                        annotations, links, widgets.
text/page-NNNN.txt      Plain text of each page, reading order preserved.
text/document.txt       Plain text of the whole document.
text/document.md        Same text as Markdown, one section per page.
content-streams/        Decoded page content streams, one file per page.
images/                 Every embedded image in its original format. Image XObjects
                        are stored once and named by xref; inline images are named
                        by page and occurrence.

All coordinates are PDF points in PyMuPDF space: origin top-left, y grows
downwards. Each report carries the matrices needed to convert to PDF space.
"""


def _page_name(page_number: int) -> str:
    return f"page-{page_number + 1:04d}"


def build_document_bundle(
    source_path: str | Path,
    output_zip: str | Path,
    *,
    password: str | None = None,
    document_id: str | None = None,
    source_name: str | None = None,
    image_dir: str | Path | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    """Write the complete extraction of one document to ``output_zip``."""
    source_path = Path(source_path)
    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    image_dir = Path(image_dir) if image_dir is not None else output_zip.parent / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    document_report = analyze_document(
        source_path,
        password=password,
        document_id=document_id,
        source_name=source_name,
    )
    page_count = document_report["file"]["page_count"]

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", BUNDLE_README)
        archive.writestr("document.json", dumps(document_report))

        full_text: list[str] = []
        markdown: list[str] = [f"# {source_name or source_path.name}\n"]

        doc = open_document(source_path, password)
        try:
            for page_number in range(page_count):
                page = doc.load_page(page_number)
                extract_page_images(doc, page, image_dir)
                plain = page.get_text("text")
                full_text.append(plain)
                markdown.append(
                    f"## Page {page_number + 1}\n\n"
                    + (plain.rstrip() or "_(no text layer on this page)_")
                    + "\n"
                )
                archive.writestr(f"text/{_page_name(page_number)}.txt", plain)
                try:
                    archive.writestr(
                        f"content-streams/{_page_name(page_number)}.txt",
                        page.read_contents().decode("utf-8", "replace"),
                    )
                except Exception as exc:  # keep going, note the failure
                    archive.writestr(
                        f"content-streams/{_page_name(page_number)}.error.txt",
                        f"content stream unavailable: {exc}\n",
                    )
                if progress is not None:
                    progress(page_number + 1, page_count)
        finally:
            doc.close()

        # Page reports are produced separately so a single bad page cannot abort
        # the bundle.
        for page_number in range(page_count):
            try:
                report = analyze_page(
                    source_path,
                    page_number,
                    password=password,
                    document_id=document_id,
                    image_dir=image_dir,
                )
                archive.writestr(f"pages/{_page_name(page_number)}.json", dumps(report))
            except Exception as exc:
                archive.writestr(
                    f"pages/{_page_name(page_number)}.error.txt",
                    f"page analysis failed: {exc}\n",
                )

        archive.writestr("text/document.txt", "\n".join(full_text))
        archive.writestr("text/document.md", "\n".join(markdown))

        for image_file in sorted(image_dir.glob("*")):
            if image_file.is_file():
                archive.write(image_file, f"images/{image_file.name}")

    return output_zip


def document_text(
    source_path: str | Path,
    *,
    password: str | None = None,
    fmt: str = "txt",
    title: str | None = None,
) -> str:
    """Return the whole document's text as plain text or Markdown."""
    doc = open_document(source_path, password)
    try:
        parts: list[str] = [f"# {title or Path(source_path).name}\n"] if fmt == "md" else []
        for page_number in range(doc.page_count):
            plain = doc.load_page(page_number).get_text("text")
            if fmt == "md":
                parts.append(
                    f"## Page {page_number + 1}\n\n"
                    + (plain.rstrip() or "_(no text layer on this page)_")
                    + "\n"
                )
            else:
                parts.append(plain)
        return "\n".join(parts)
    finally:
        doc.close()


def collect_document_json(
    source_path: str | Path,
    *,
    password: str | None = None,
    document_id: str | None = None,
    source_name: str | None = None,
    image_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return document report plus every page report in one JSON-safe dict."""
    document_report = analyze_document(
        source_path, password=password, document_id=document_id, source_name=source_name
    )
    pages: list[dict[str, Any]] = []
    for page_number in range(document_report["file"]["page_count"]):
        try:
            pages.append(
                analyze_page(
                    source_path,
                    page_number,
                    password=password,
                    document_id=document_id,
                    image_dir=image_dir,
                )
            )
        except Exception as exc:
            pages.append({"page_number": page_number, "error": str(exc)})
    return {"document": document_report, "pages": pages}
