"""Error types raised by the extraction core.

The core never raises PyMuPDF exceptions to its callers; everything is wrapped
so the web layer can map failures onto HTTP status codes without importing
PyMuPDF itself.
"""

from __future__ import annotations


class PdfScopeError(Exception):
    """Base class for all core errors."""


class DocumentOpenError(PdfScopeError):
    """The file could not be opened or is not a usable document."""


class PasswordRequiredError(PdfScopeError):
    """The document is encrypted and the supplied password did not work."""


class PageNotFoundError(PdfScopeError):
    """The requested page index does not exist."""


class ObjectNotFoundError(PdfScopeError):
    """The requested xref number does not exist in the document."""


class ImageDecodeError(PdfScopeError):
    """An image exists but its pixels could not be decoded or re-encoded."""
