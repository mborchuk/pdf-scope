"""Document-level analysis: identity, file structure, metadata, global contents."""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
from typing import Any

import pymupdf

from . import objects
from .coordinates import COORDINATE_SPACE_NOTE, matrix_to_list, rect_to_list
from .errors import DocumentOpenError, PasswordRequiredError
from .schema import SCHEMA_VERSION, jsonable

#: Permission bits reported by ``Document.permissions``.
PERMISSION_BITS: dict[str, int] = {
    "print": pymupdf.PDF_PERM_PRINT,
    "modify": pymupdf.PDF_PERM_MODIFY,
    "copy": pymupdf.PDF_PERM_COPY,
    "annotate": pymupdf.PDF_PERM_ANNOTATE,
    "fill_forms": pymupdf.PDF_PERM_FORM,
    "accessibility": pymupdf.PDF_PERM_ACCESSIBILITY,
    "assemble": pymupdf.PDF_PERM_ASSEMBLE,
    "print_high_quality": pymupdf.PDF_PERM_PRINT_HQ,
}

#: Pages inspected when aggregating the document font list.
FONT_SCAN_PAGE_LIMIT = 2_000

#: Things that exist in PDF files but that PyMuPDF/MuPDF does not surface.
#: Reported verbatim in the UI and README so gaps are explicit, not silent.
KNOWN_LIMITATIONS: list[dict[str, str]] = [
    {
        "topic": "Digital signatures",
        "detail": (
            "PyMuPDF reports /SigFlags and signature widget dictionaries, but does not "
            "validate signatures or expose the PKCS#7 certificate chain in a structured "
            "form. The raw /Contents byte string is reachable through the object view."
        ),
    },
    {
        "topic": "Encryption internals",
        "detail": (
            "The encryption method string and permission bits are reported. The /Encrypt "
            "dictionary's keys, algorithm parameters and the file encryption key are not "
            "exposed by the API."
        ),
    },
    {
        "topic": "Font programs",
        "detail": (
            "Embedded font files can be located by xref and downloaded as raw streams, "
            "but glyph outlines, CMaps and ToUnicode mappings are not decoded into a "
            "structured form."
        ),
    },
    {
        "topic": "Scanned pages",
        "detail": (
            "Image-only pages carry no text layer. No OCR is performed, so text "
            "extraction correctly returns nothing for them."
        ),
    },
    {
        "topic": "Original byte offsets",
        "detail": (
            "MuPDF re-serialises object source when it is read, so the byte offsets of "
            "objects in the original file, the classic xref table layout and incremental "
            "update sections are not reported. Object stream and xref stream usage is "
            "detected by object type instead."
        ),
    },
    {
        "topic": "Content stream provenance",
        "detail": (
            "Page content streams are concatenated and decoded by MuPDF. The operator "
            "listing is produced by this application's own parser; unsupported or damaged "
            "filter chains are reported per stream rather than silently skipped."
        ),
    },
]


def sha256_of_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_document(path: str | Path, password: str | None = None) -> pymupdf.Document:
    """Open a PDF, authenticating if needed.

    Raises ``DocumentOpenError`` for unreadable files and
    ``PasswordRequiredError`` when the document stays locked.
    """
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise DocumentOpenError(str(exc)) from exc

    if doc.needs_pass and not doc.authenticate(password or ""):
        doc.close()
        raise PasswordRequiredError("document is password protected")
    return doc


def decode_permissions(value: int) -> dict[str, Any]:
    """Split the permission bitmask into named booleans."""
    return {
        "raw": int(value),
        "allowed": {name: bool(value & bit) for name, bit in PERMISSION_BITS.items()},
    }


def _encryption_info(doc: pymupdf.Document) -> dict[str, Any]:
    """Report encryption state.

    ``Document.is_encrypted`` means "still locked": it flips to False once
    ``authenticate`` succeeds. The file's own encryption is therefore derived
    from ``needs_pass`` plus the encryption method string.
    """
    metadata = doc.metadata or {}
    method = metadata.get("encryption")
    return {
        "is_encrypted": bool(doc.needs_pass or method),
        "needs_password": bool(doc.needs_pass),
        "still_locked": bool(doc.is_encrypted),
        "method": method,
        "permissions": decode_permissions(doc.permissions),
    }


def _xmp_metadata(doc: pymupdf.Document) -> dict[str, Any]:
    xref = 0
    with contextlib.suppress(Exception):
        xref = doc.xref_xml_metadata()
    if not xref:
        return {"present": False, "xref": None, "xml": None}
    try:
        xml = doc.xref_stream(xref).decode("utf-8", "replace")
    except Exception as exc:
        return {"present": True, "xref": xref, "xml": None, "error": str(exc)}
    return {"present": True, "xref": xref, "xml": xml, "length": len(xml)}


def _catalog_info(doc: pymupdf.Document) -> dict[str, Any]:
    catalog_xref = doc.pdf_catalog()
    return objects.describe_object(doc, catalog_xref) if catalog_xref else {}


def _document_ids(doc: pymupdf.Document) -> list[str]:
    trailer = ""
    with contextlib.suppress(Exception):
        trailer = doc.pdf_trailer() or ""
    start = trailer.find("/ID")
    if start == -1:
        return []
    segment = trailer[start : start + 400]
    ids: list[str] = []
    depth = 0
    current = ""
    for char in segment:
        if char == "<":
            depth += 1
            current = ""
            continue
        if char == ">":
            depth -= 1
            if current:
                ids.append(current)
            current = ""
            continue
        if depth:
            current += char
        if char == "]" and ids:
            break
    return ids


def _fonts(doc: pymupdf.Document) -> dict[str, Any]:
    """Aggregate every font referenced by any page, recording where it is used."""
    fonts: dict[int, dict[str, Any]] = {}
    scanned = min(doc.page_count, FONT_SCAN_PAGE_LIMIT)
    for pno in range(scanned):
        try:
            page_fonts = doc.get_page_fonts(pno, full=True)
        except Exception:
            continue
        for item in page_fonts:
            xref, ext, ftype, basefont, refname, encoding = item[:6]
            referencer = item[6] if len(item) > 6 else None
            record = fonts.setdefault(
                xref,
                {
                    "xref": xref,
                    "base_font": basefont,
                    "subtype": ftype,
                    "resource_name": f"/{refname}" if refname else None,
                    "encoding": encoding or None,
                    "embedded": ext != "n/a",
                    "font_file_extension": None if ext == "n/a" else ext,
                    "subset_prefix": _subset_prefix(basefont),
                    "referenced_by_xobject": referencer or None,
                    "used_on_pages": [],
                },
            )
            record["used_on_pages"].append(pno)

    for record in fonts.values():
        xref = record["xref"]
        if xref:
            descriptor = objects.key_value(doc, xref, "FontDescriptor")
            record["font_descriptor_xref"] = objects.resolve_reference(descriptor)
            record["to_unicode_xref"] = objects.resolve_reference(
                objects.key_value(doc, xref, "ToUnicode")
            )
            descendant = objects.key_value(doc, xref, "DescendantFonts")
            if descendant:
                record["descendant_fonts"] = objects.find_references(descendant)

    return {
        "items": sorted(fonts.values(), key=lambda item: (item["base_font"] or "", item["xref"])),
        "pages_scanned": scanned,
        "scan_truncated": doc.page_count > scanned,
    }


def _subset_prefix(base_font: str | None) -> str | None:
    """Return the six-letter subset prefix of a base font name, if present."""
    if not base_font or len(base_font) < 8 or base_font[6] != "+":
        return None
    prefix = base_font[:6]
    return prefix if prefix.isalpha() and prefix.isupper() else None


def _attachments(doc: pymupdf.Document) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        names = doc.embfile_names()
    except Exception:
        return items
    for index, name in enumerate(names):
        try:
            info = dict(doc.embfile_info(index))
        except Exception as exc:
            items.append({"index": index, "name": name, "error": str(exc)})
            continue
        info["index"] = index
        info["name"] = name
        items.append(jsonable(info))
    return items


def _form_fields(doc: pymupdf.Document) -> dict[str, Any]:
    """Collect AcroForm fields with their values, page by page."""
    catalog = doc.pdf_catalog()
    acroform = objects.key_value(doc, catalog, "AcroForm")
    fields: list[dict[str, Any]] = []
    for pno in range(doc.page_count):
        try:
            page = doc.load_page(pno)
        except Exception:
            continue
        try:
            for widget in page.widgets():
                fields.append(
                    {
                        "page": pno,
                        "xref": widget.xref,
                        "field_name": widget.field_name,
                        "field_label": widget.field_label,
                        "field_type": widget.field_type,
                        "field_type_string": widget.field_type_string,
                        "field_value": jsonable(widget.field_value),
                        "field_display": widget.field_display,
                        "field_flags": widget.field_flags,
                        "is_signed": widget.is_signed,
                        "choice_values": jsonable(widget.choice_values),
                        "rect": rect_to_list(widget.rect),
                        "text_font": widget.text_font,
                        "text_fontsize": widget.text_fontsize,
                        "text_maxlen": widget.text_maxlen,
                        "border_style": widget.border_style,
                        "script": widget.script,
                    }
                )
        except Exception as exc:
            fields.append({"page": pno, "error": str(exc)})
        finally:
            page = None
    sig_flags = -1
    with contextlib.suppress(Exception):
        sig_flags = doc.get_sigflags()
    return {
        "is_form_pdf": bool(doc.is_form_pdf),
        "acroform": acroform,
        "acroform_xref": objects.resolve_reference(acroform),
        "sig_flags": sig_flags,
        "fields": fields,
    }


def _optional_content(doc: pymupdf.Document) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name, getter in (
        ("ocgs", doc.get_ocgs),
        ("layers", doc.get_layers),
        ("ui_configs", doc.layer_ui_configs),
    ):
        try:
            data[name] = jsonable(getter())
        except Exception as exc:
            data[name] = {"error": str(exc)}
    return data


def _outline(doc: pymupdf.Document) -> list[dict[str, Any]]:
    try:
        toc = doc.get_toc(simple=False)
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for entry in toc:
        level, title, page = entry[0], entry[1], entry[2]
        details = jsonable(entry[3]) if len(entry) > 3 else {}
        items.append(
            {
                "level": level,
                "title": title,
                "page": page - 1 if isinstance(page, int) and page > 0 else None,
                "page_label_number": page,
                "destination": details,
            }
        )
    return items


def _page_summaries(doc: pymupdf.Document) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    labels: list[str] = []
    with contextlib.suppress(Exception):
        labels = [doc.load_page(i).get_label() for i in range(doc.page_count)]
    for pno in range(doc.page_count):
        try:
            page = doc.load_page(pno)
        except Exception as exc:
            summaries.append({"page_number": pno, "error": str(exc)})
            continue
        summaries.append(
            {
                "page_number": pno,
                "label": labels[pno] if pno < len(labels) else None,
                "xref": page.xref,
                "rect": rect_to_list(page.rect),
                "mediabox": rect_to_list(page.mediabox),
                "cropbox": rect_to_list(page.cropbox),
                "rotation": page.rotation,
                "width": round(page.rect.width, 4),
                "height": round(page.rect.height, 4),
            }
        )
    return summaries


def analyze_document(
    path: str | Path,
    *,
    password: str | None = None,
    document_id: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """Produce the document-level report.

    Page contents are *not* extracted here; use ``analyze_page`` per page so
    large documents stay cheap to open.
    """
    path = Path(path)
    doc = open_document(path, password)
    warnings: list[str] = []
    try:
        if not doc.is_pdf:
            warnings.append(
                "file was opened by MuPDF but is not a PDF; object-level views are unavailable"
            )

        metadata = jsonable(doc.metadata or {})
        catalog = _catalog_info(doc)
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "identity": {
                "document_id": document_id,
                "source_name": source_name or path.name,
                "source_size_bytes": path.stat().st_size,
                "sha256": sha256_of_file(path),
            },
            "extractor": {
                "library": "PyMuPDF",
                "pymupdf_version": pymupdf.version[0],
                "mupdf_version": pymupdf.mupdf_version,
            },
            "coordinate_space": COORDINATE_SPACE_NOTE,
            "file": {
                "is_pdf": bool(doc.is_pdf),
                "pdf_version": metadata.get("format"),
                "catalog_version": objects.key_value(doc, doc.pdf_catalog(), "Version")
                if doc.is_pdf
                else None,
                "page_count": doc.page_count,
                "chapter_count": doc.chapter_count,
                "version_count": doc.version_count,
                "is_repaired": bool(doc.is_repaired),
                "is_linearized_fast_web_view": bool(doc.is_fast_webaccess),
                "document_id": _document_ids(doc),
                "trailer": doc.pdf_trailer() if doc.is_pdf else None,
                "catalog_xref": doc.pdf_catalog() if doc.is_pdf else None,
                "page_mode": doc.pagemode,
                "page_layout": doc.pagelayout,
                "mark_info": jsonable(doc.markinfo),
                "language": doc.language,
                "page_labels": jsonable(doc.get_page_labels()),
                "xref": objects.scan_xref_table(doc) if doc.is_pdf else {},
            },
            "encryption": _encryption_info(doc),
            "metadata": {
                "info": metadata,
                "xmp": _xmp_metadata(doc),
            },
            "structure": {
                "catalog": catalog,
                "page_tree": objects.page_tree(doc) if doc.is_pdf else {},
                "struct_tree_root": objects.structure_tree(doc) if doc.is_pdf else None,
                "name_trees": objects.name_trees(doc) if doc.is_pdf else {},
                "named_destinations": jsonable(doc.resolve_names()) if doc.is_pdf else {},
                "outline": _outline(doc),
            },
            "fonts": _fonts(doc),
            "attachments": _attachments(doc),
            "form": _form_fields(doc) if doc.is_pdf else {},
            "optional_content": _optional_content(doc) if doc.is_pdf else {},
            "javascript": objects.collect_javascript(doc) if doc.is_pdf else [],
            "pages": _page_summaries(doc),
            "known_limitations": KNOWN_LIMITATIONS,
            "warnings": warnings,
        }

        if report["structure"]["struct_tree_root"] is None:
            warnings.append(
                "document has no /StructTreeRoot: it is not tagged, so no logical "
                "structure tree exists in the file"
            )
        return report
    finally:
        doc.close()


def page_transform_matrices(page: pymupdf.Page) -> dict[str, Any]:
    """Return the matrices that relate PyMuPDF space, PDF space and rotation."""
    from .coordinates import invert_matrix

    transformation = matrix_to_list(page.transformation_matrix)
    return {
        "transformation_matrix": transformation,
        "transformation_matrix_inverse": (
            invert_matrix(transformation) if transformation else None
        ),
        "rotation_matrix": matrix_to_list(page.rotation_matrix),
        "derotation_matrix": matrix_to_list(page.derotation_matrix),
    }
