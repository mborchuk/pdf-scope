"""Coordinate conventions and conversion helpers.

Every geometry value produced by this package is expressed in **PDF points**
(1 pt = 1/72 inch) in **PyMuPDF space**:

* origin is the TOP-LEFT corner of the page,
* x grows to the right, y grows DOWNWARDS,
* the page area used is ``page.rect``, i.e. the CropBox after the page
  ``/Rotate`` entry has been applied.

The PDF file format itself uses a BOTTOM-LEFT origin with y growing upwards and
stores unrotated boxes.  Both readings are useful, so every page report carries
the matrices needed to move between them:

* ``transformation_matrix`` maps PDF space -> PyMuPDF space,
* its inverse maps PyMuPDF space -> PDF space,
* ``rotation_matrix`` / ``derotation_matrix`` add or remove the page rotation.

``rect_to_pdf_space`` below performs the PyMuPDF -> PDF conversion so callers
can present both number sets for the same element.
"""

from __future__ import annotations

from typing import Any

Rect4 = list[float]
Matrix6 = list[float]

#: Human readable description embedded in every extraction result.
COORDINATE_SPACE_NOTE: dict[str, Any] = {
    "unit": "PDF point (1/72 inch)",
    "space": "PyMuPDF",
    "origin": "top-left of page.rect, y axis grows downwards",
    "pdf_space": "PDF native space has a bottom-left origin with y growing upwards",
    "page_area": "page.rect == CropBox with /Rotate applied",
    "conversion": (
        "pdf_rect = mupdf_rect * ~page.transformation_matrix; the inverse matrix is "
        "published per page as page.transformation_matrix_inverse"
    ),
}


def rect_to_list(rect: Any) -> Rect4 | None:
    """Convert a PyMuPDF ``Rect``/``IRect``/4-tuple into a JSON-safe list."""
    if rect is None:
        return None
    try:
        return [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]
    except (TypeError, IndexError, ValueError):
        return None


def matrix_to_list(matrix: Any) -> Matrix6 | None:
    """Convert a PyMuPDF ``Matrix``/6-tuple into a JSON-safe list."""
    if matrix is None:
        return None
    try:
        return [float(matrix[i]) for i in range(6)]
    except (TypeError, IndexError, ValueError):
        return None


def point_to_list(point: Any) -> list[float] | None:
    """Convert a PyMuPDF ``Point``/2-tuple into a JSON-safe list."""
    if point is None:
        return None
    try:
        return [float(point[0]), float(point[1])]
    except (TypeError, IndexError, ValueError):
        return None


def invert_matrix(matrix: Matrix6) -> Matrix6 | None:
    """Invert an affine matrix given as ``[a, b, c, d, e, f]``."""
    a, b, c, d, e, f = matrix
    det = a * d - b * c
    if det == 0:
        return None
    ia = d / det
    ib = -b / det
    ic = -c / det
    id_ = a / det
    ie = (c * f - d * e) / det
    if_ = (b * e - a * f) / det
    return [ia, ib, ic, id_, ie, if_]


def apply_matrix_to_rect(rect: Rect4, matrix: Matrix6) -> Rect4:
    """Transform a rectangle by an affine matrix, returning a normalised rect."""
    a, b, c, d, e, f = matrix
    x0, y0, x1, y1 = rect
    corners = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
    mapped = [(a * x + c * y + e, b * x + d * y + f) for x, y in corners]
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    return [min(xs), min(ys), max(xs), max(ys)]


def rect_to_pdf_space(rect: Rect4 | None, transformation_matrix: Matrix6 | None) -> Rect4 | None:
    """Convert a PyMuPDF-space rectangle into PDF (bottom-left origin) space."""
    if rect is None or transformation_matrix is None:
        return None
    inverse = invert_matrix(transformation_matrix)
    if inverse is None:
        return None
    return apply_matrix_to_rect(rect, inverse)
