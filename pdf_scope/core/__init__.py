"""Extraction core: PDF in, structured data out.

This package has no web-framework dependency. It can be imported, tested and
scripted on its own::

    from pdf_scope.core import analyze_document, analyze_page

    report = analyze_document("file.pdf")
    page = analyze_page("file.pdf", 0)
"""

from .document import analyze_document, open_document, sha256_of_file
from .errors import (
    DocumentOpenError,
    ImageDecodeError,
    ObjectNotFoundError,
    PageNotFoundError,
    PasswordRequiredError,
    PdfScopeError,
)
from .export import build_document_bundle, collect_document_json, document_text
from .images import image_preview_png
from .objects import describe_object
from .page import analyze_page, page_content_stream_bytes, page_drawings, page_operators
from .render import render_page_png
from .schema import SCHEMA_VERSION, dumps
from .summary import document_content_summary

__all__ = [
    "SCHEMA_VERSION",
    "DocumentOpenError",
    "ImageDecodeError",
    "ObjectNotFoundError",
    "PageNotFoundError",
    "PasswordRequiredError",
    "PdfScopeError",
    "analyze_document",
    "analyze_page",
    "build_document_bundle",
    "collect_document_json",
    "describe_object",
    "document_content_summary",
    "document_text",
    "dumps",
    "image_preview_png",
    "open_document",
    "page_content_stream_bytes",
    "page_drawings",
    "page_operators",
    "render_page_png",
    "sha256_of_file",
]
