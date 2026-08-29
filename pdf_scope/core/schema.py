"""Schema constants and JSON coercion helpers.

The extraction result is a plain ``dict`` tree containing only JSON-native
types.  Binary payloads (image bytes, content streams, attachments) are never
inlined: they are written to the artifact directory and referenced by relative
path, so a result can always be serialised with ``json.dumps``.
"""

from __future__ import annotations

import json
from typing import Any

#: Bumped whenever the shape of a document/page report changes.
SCHEMA_VERSION = "1.0"

#: Maximum number of characters of a decoded content stream inlined in a page
#: report.  Anything longer is truncated and must be downloaded in full.
CONTENT_STREAM_INLINE_LIMIT = 200_000

#: Largest window of operators a single request may ask for.
CONTENT_STREAM_OPERATOR_LIMIT = 20_000

#: Operators inlined in a page report. A CAD sheet can hold millions of them
#: (5 071 999 on one sheet in testing), so the report carries the first window and
#: the operator range accessor reaches the rest.
PAGE_OPERATOR_LIMIT = 5_000

#: Maximum number of vector paths inlined in a page report.  CAD plots routinely
#: hold tens or hundreds of thousands of paths — 265 507 on one sheet in testing,
#: which is 746 MB of JSON — so the report carries a window and reports the total.
#: The rest is reachable through the drawings range accessor.
PAGE_DRAWING_LIMIT = 5_000

#: Maximum number of xref objects scanned when profiling the object model.
XREF_SCAN_LIMIT = 200_000


def jsonable(value: Any) -> Any:
    """Coerce PyMuPDF values (Rect, Matrix, Point, bytes, ...) into JSON types."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    # PyMuPDF geometry objects are sequences of floats.
    try:
        return [jsonable(v) for v in value]
    except TypeError:
        return str(value)


def dumps(data: Any, *, indent: int | None = 2) -> str:
    """Serialise an extraction result to JSON text."""
    return json.dumps(data, indent=indent, ensure_ascii=False, default=jsonable)
