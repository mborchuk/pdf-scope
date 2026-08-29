"""Two documents processed at the same time must stay completely separate."""

from __future__ import annotations

import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from pdf_scope.core import build_document_bundle, document_text
from pdf_scope.web.tasks import task_analyze_document, task_analyze_page


def test_two_documents_analysed_concurrently(rich_pdf: Path, second_pdf: Path) -> None:
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(task_analyze_document, str(rich_pdf), None, "doc-a", "rich.pdf"),
            pool.submit(task_analyze_document, str(second_pdf), None, "doc-b", "second.pdf"),
        ]
        first, second = (future.result() for future in futures)

    assert first["identity"]["document_id"] == "doc-a"
    assert second["identity"]["document_id"] == "doc-b"
    assert first["identity"]["sha256"] != second["identity"]["sha256"]
    assert first["metadata"]["info"]["title"] == "Rich fixture"
    assert second["metadata"]["info"]["title"] == "Second fixture"
    assert first["file"]["page_count"] == 2
    assert second["file"]["page_count"] == 1


def test_concurrent_page_extraction_keeps_artifacts_namespaced(
    rich_pdf: Path, second_pdf: Path, tmp_path: Path
) -> None:
    dir_a = tmp_path / "doc-a" / "images"
    dir_b = tmp_path / "doc-b" / "images"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    with ProcessPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(task_analyze_page, str(rich_pdf), 0, None, "doc-a", str(dir_a)),
            pool.submit(task_analyze_page, str(second_pdf), 0, None, "doc-b", str(dir_b)),
        ]
        page_a, page_b = (future.result() for future in futures)

    assert page_a["document_id"] == "doc-a"
    assert page_b["document_id"] == "doc-b"
    assert "Hello pdf scope" in page_a["text"]["plain"]
    assert "UNIQUE-SECOND-DOCUMENT" in page_b["text"]["plain"]
    assert "UNIQUE-SECOND-DOCUMENT" not in page_a["text"]["plain"]

    files_a = {item.name for item in dir_a.iterdir()}
    files_b = {item.name for item in dir_b.iterdir()}
    assert files_a and files_b
    # Artifacts live in separate directories; identical names cannot collide.
    for name in files_a:
        assert (
            not (dir_b / name).exists()
            or (dir_a / name).read_bytes() != (dir_b / name).read_bytes()
        )


def test_bundle_contains_every_part(rich_pdf: Path, tmp_path: Path) -> None:
    bundle = build_document_bundle(
        rich_pdf,
        tmp_path / "export.zip",
        document_id="doc-a",
        source_name="rich.pdf",
        image_dir=tmp_path / "images",
    )
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert "document.json" in names
        assert "pages/page-0001.json" in names
        assert "text/page-0001.txt" in names
        assert "text/document.txt" in names
        assert "text/document.md" in names
        assert "content-streams/page-0001.txt" in names
        assert any(name.startswith("images/") for name in names)
        assert "Hello pdf scope" in archive.read("text/document.txt").decode()


def test_document_text_formats(rich_pdf: Path) -> None:
    plain = document_text(rich_pdf)
    markdown = document_text(rich_pdf, fmt="md", title="rich.pdf")
    assert "Hello pdf scope" in plain
    assert markdown.startswith("# rich.pdf")
    assert "## Page 1" in markdown and "## Page 2" in markdown
