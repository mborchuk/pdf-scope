"""Error types raised by the extraction core.

The core never raises PyMuPDF exceptions to its callers; everything is wrapped
so the web layer can map failures onto HTTP status codes without importing
PyMuPDF itself.
"""

from __future__ import annotations


class PdfDecompilerError(Exception):
    """Base class for all core errors."""


class DocumentOpenError(PdfDecompilerError):
    """The file could not be opened or is not a usable document."""


class PasswordRequiredError(PdfDecompilerError):
    """The document is encrypted and the supplied password did not work."""


class PageNotFoundError(PdfDecompilerError):
    """The requested page index does not exist."""


class ObjectNotFoundError(PdfDecompilerError):
    """The requested xref number does not exist in the document."""


class ImageDecodeError(PdfDecompilerError):
    """An image exists but its pixels could not be decoded or re-encoded."""
