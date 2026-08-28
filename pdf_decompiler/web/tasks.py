"""Functions executed inside worker processes.

PyMuPDF documents must not be shared between workers, and the library's own
documentation states it does not support running on multiple threads. Every
function here therefore takes plain picklable arguments (paths, ints, strings),
opens its own ``Document`` and closes it before returning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core import (
    analyze_document,
    analyze_page,
    build_document_bundle,
    describe_object,
    document_text,
    image_preview_png,
    open_document,
    page_content_stream_bytes,
    page_drawings,
    page_operators,
    render_page_png,
)


def task_analyze_document(
    path: str,
    password: str | None,
    document_id: str,
    source_name: str,
) -> dict[str, Any]:
    return analyze_document(
        path, password=password, document_id=document_id, source_name=source_name
    )


def task_analyze_page(
    path: str,
    page_number: int,
    password: str | None,
    document_id: str,
    image_dir: str,
) -> dict[str, Any]:
    return analyze_page(
        path,
        page_number,
        password=password,
        document_id=document_id,
        image_dir=image_dir,
    )


def task_render_page(
    path: str,
    page_number: int,
    dpi: int,
    password: str | None,
    clip: tuple[float, float, float, float] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    return render_page_png(path, page_number, dpi=dpi, password=password, clip=clip)


def task_image_preview(
    path: str,
    xref: int,
    max_side: int | None,
    password: str | None,
) -> tuple[bytes, dict[str, Any]]:
    return image_preview_png(path, xref, password=password, max_side=max_side)


def task_describe_object(
    path: str,
    xref: int,
    password: str | None,
    include_stream: bool,
) -> dict[str, Any]:
    doc = open_document(path, password)
    try:
        return describe_object(doc, xref, include_stream=include_stream)
    finally:
        doc.close()


def task_object_stream(path: str, xref: int, password: str | None, raw: bool) -> bytes:
    doc = open_document(path, password)
    try:
        return doc.xref_stream_raw(xref) if raw else doc.xref_stream(xref)
    finally:
        doc.close()


def task_page_drawings(
    path: str,
    page_number: int,
    offset: int,
    limit: int,
    password: str | None,
) -> dict[str, Any]:
    return page_drawings(path, page_number, offset=offset, limit=limit, password=password)


def task_page_operators(
    path: str,
    page_number: int,
    offset: int,
    limit: int,
    password: str | None,
) -> dict[str, Any]:
    return page_operators(path, page_number, offset=offset, limit=limit, password=password)


def task_content_stream(path: str, page_number: int, password: str | None, raw: bool) -> bytes:
    return page_content_stream_bytes(path, page_number, password=password, raw=raw)


def task_document_text(path: str, password: str | None, fmt: str, title: str) -> str:
    return document_text(path, password=password, fmt=fmt, title=title)


def task_page_text(path: str, page_number: int, password: str | None, fmt: str) -> str:
    doc = open_document(path, password)
    try:
        plain = doc.load_page(page_number).get_text("text")
    finally:
        doc.close()
    if fmt == "md":
        body = plain.rstrip() or "_(no text layer on this page)_"
        return f"## Page {page_number + 1}\n\n{body}\n"
    return plain


def task_attachment(path: str, index: int, password: str | None) -> tuple[bytes, str]:
    doc = open_document(path, password)
    try:
        info = doc.embfile_info(index)
        return doc.embfile_get(index), str(info.get("filename") or f"attachment-{index}")
    finally:
        doc.close()


def task_build_bundle(
    path: str,
    output_zip: str,
    password: str | None,
    document_id: str,
    source_name: str,
    image_dir: str,
) -> str:
    result = build_document_bundle(
        path,
        output_zip,
        password=password,
        document_id=document_id,
        source_name=source_name,
        image_dir=image_dir,
    )
    return str(result)


def task_extract_all_images(path: str, password: str | None, image_dir: str) -> list[str]:
    """Make sure every page's images are on disk; return the file names."""
    from ..core.images import extract_page_images

    target = Path(image_dir)
    target.mkdir(parents=True, exist_ok=True)
    doc = open_document(path, password)
    try:
        for page_number in range(doc.page_count):
            try:
                extract_page_images(doc, doc.load_page(page_number), target)
            except Exception:
                continue
    finally:
        doc.close()
    return sorted(item.name for item in target.iterdir() if item.is_file())
