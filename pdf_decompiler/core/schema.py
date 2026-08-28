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

#: Maximum number of operators listed in the decompiled content-stream view.
CONTENT_STREAM_OPERATOR_LIMIT = 20_000

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
