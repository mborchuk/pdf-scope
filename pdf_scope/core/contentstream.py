"""Content-stream lexer: turns a decoded page content stream into operators.

This is the "decompiled" view of a page.  PyMuPDF hands us the decoded stream
bytes; the PDF operator syntax itself (ISO 32000-1, clause 7.8.2) is parsed
here in pure Python so the UI can list what the page actually draws, in order,
with operand values.

Inline images (``BI ... ID <binary> EI``) are recognised and reported as a
single operator carrying the image dictionary and the byte length of the data;
their raw bytes are not inlined.
"""

from __future__ import annotations

from typing import Any

_WHITESPACE = b"\x00\t\n\x0c\r "
_DELIMITERS = b"()<>[]{}/%"

#: Short descriptions for the operators a reader is most likely to look up.
OPERATOR_DESCRIPTIONS: dict[str, str] = {
    "q": "save graphics state",
    "Q": "restore graphics state",
    "cm": "concatenate matrix to CTM",
    "w": "set line width",
    "J": "set line cap",
    "j": "set line join",
    "M": "set miter limit",
    "d": "set dash pattern",
    "ri": "set rendering intent",
    "i": "set flatness tolerance",
    "gs": "apply ExtGState resource",
    "m": "begin subpath (moveto)",
    "l": "append straight line (lineto)",
    "c": "append cubic Bezier",
    "v": "append cubic Bezier (current point as first control)",
    "y": "append cubic Bezier (end point as second control)",
    "h": "close subpath",
    "re": "append rectangle",
    "S": "stroke path",
    "s": "close and stroke path",
    "f": "fill path (nonzero)",
    "F": "fill path (nonzero, deprecated)",
    "f*": "fill path (even-odd)",
    "B": "fill and stroke path (nonzero)",
    "B*": "fill and stroke path (even-odd)",
    "b": "close, fill and stroke (nonzero)",
    "b*": "close, fill and stroke (even-odd)",
    "n": "end path without painting",
    "W": "set clipping path (nonzero)",
    "W*": "set clipping path (even-odd)",
    "BT": "begin text object",
    "ET": "end text object",
    "Tc": "set character spacing",
    "Tw": "set word spacing",
    "Tz": "set horizontal scaling",
    "TL": "set text leading",
    "Tf": "set font and size",
    "Tr": "set text rendering mode",
    "Ts": "set text rise",
    "Td": "move text position",
    "TD": "move text position and set leading",
    "Tm": "set text matrix",
    "T*": "move to next line",
    "Tj": "show text",
    "TJ": "show text with positioning",
    "'": "next line and show text",
    '"': "set spacing, next line and show text",
    "d0": "set glyph width (Type 3)",
    "d1": "set glyph width and bbox (Type 3)",
    "CS": "set stroking colour space",
    "cs": "set non-stroking colour space",
    "SC": "set stroking colour",
    "SCN": "set stroking colour (ICC/pattern)",
    "sc": "set non-stroking colour",
    "scn": "set non-stroking colour (ICC/pattern)",
    "G": "set stroking grey",
    "g": "set non-stroking grey",
    "RG": "set stroking RGB",
    "rg": "set non-stroking RGB",
    "K": "set stroking CMYK",
    "k": "set non-stroking CMYK",
    "sh": "paint shading",
    "Do": "draw XObject (image or form)",
    "BI": "inline image",
    "MP": "marked-content point",
    "DP": "marked-content point with properties",
    "BMC": "begin marked-content sequence",
    "BDC": "begin marked-content sequence with properties",
    "EMC": "end marked-content sequence",
    "BX": "begin compatibility section",
    "EX": "end compatibility section",
}


class _Token:
    """Marker for syntactic tokens that are not operands."""

    __slots__ = ("kind",)

    def __init__(self, kind: str) -> None:
        self.kind = kind


class _Lexer:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def _skip_whitespace(self) -> None:
        data, n = self.data, len(self.data)
        while self.pos < n:
            ch = data[self.pos]
            if ch in _WHITESPACE:
                self.pos += 1
            elif ch == 0x25:  # '%' comment runs to end of line
                while self.pos < n and data[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                return

    def next_object(self) -> tuple[Any, int] | None:
        """Return ``(value, offset)`` for the next lexical object, or ``None``."""
        self._skip_whitespace()
        if self.pos >= len(self.data):
            return None
        start = self.pos
        ch = self.data[self.pos]
        if ch == 0x2F:  # '/'
            return self._read_name(), start
        if ch == 0x28:  # '('
            return self._read_literal_string(), start
        if ch == 0x3C:  # '<'
            if self.data[self.pos : self.pos + 2] == b"<<":
                self.pos += 2
                return _Token("dict_open"), start
            return self._read_hex_string(), start
        if ch == 0x3E and self.data[self.pos : self.pos + 2] == b">>":
            self.pos += 2
            return _Token("dict_close"), start
        if ch == 0x5B:  # '['
            self.pos += 1
            return _Token("array_open"), start
        if ch == 0x5D:  # ']'
            self.pos += 1
            return _Token("array_close"), start
        if ch in b"{}":
            self.pos += 1
            return _Token("brace"), start
        if ch in b"+-." or 0x30 <= ch <= 0x39:
            return self._read_number(), start
        return self._read_keyword(), start

    def _read_name(self) -> dict[str, str]:
        self.pos += 1
        out = bytearray()
        data, n = self.data, len(self.data)
        while self.pos < n:
            ch = data[self.pos]
            if ch in _WHITESPACE or ch in _DELIMITERS:
                break
            if ch == 0x23 and self.pos + 2 < n:  # '#' hex escape
                try:
                    out.append(int(data[self.pos + 1 : self.pos + 3], 16))
                    self.pos += 3
                    continue
                except ValueError:
                    pass
            out.append(ch)
            self.pos += 1
        return {"name": "/" + out.decode("latin-1")}

    def _read_literal_string(self) -> dict[str, str]:
        self.pos += 1
        depth = 1
        out = bytearray()
        data, n = self.data, len(self.data)
        while self.pos < n:
            ch = data[self.pos]
            if ch == 0x5C:  # backslash escape
                self.pos += 1
                if self.pos >= n:
                    break
                esc = data[self.pos]
                mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
                if esc in mapping:
                    out.append(mapping[esc])
                    self.pos += 1
                elif 0x30 <= esc <= 0x37:
                    digits = bytearray()
                    while self.pos < n and len(digits) < 3 and 0x30 <= data[self.pos] <= 0x37:
                        digits.append(data[self.pos])
                        self.pos += 1
                    out.append(int(digits, 8) & 0xFF)
                else:
                    out.append(esc)
                    self.pos += 1
                continue
            if ch == 0x28:
                depth += 1
            elif ch == 0x29:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    break
            out.append(ch)
            self.pos += 1
        return {"string": out.decode("utf-8", "replace")}

    def _read_hex_string(self) -> dict[str, str]:
        self.pos += 1
        digits = bytearray()
        data, n = self.data, len(self.data)
        while self.pos < n and data[self.pos] != 0x3E:
            ch = data[self.pos]
            if ch not in _WHITESPACE:
                digits.append(ch)
            self.pos += 1
        self.pos += 1
        if len(digits) % 2:
            digits.append(0x30)
        try:
            raw = bytes.fromhex(digits.decode("latin-1"))
        except ValueError:
            raw = bytes(digits)
        return {"hex_string": raw.hex(), "text": raw.decode("utf-8", "replace")}

    def _read_number(self) -> float | int:
        data, n = self.data, len(self.data)
        start = self.pos
        self.pos += 1
        while self.pos < n and (data[self.pos] in b"+-." or 0x30 <= data[self.pos] <= 0x39):
            self.pos += 1
        raw = data[start : self.pos].decode("latin-1")
        try:
            return int(raw)
        except ValueError:
            try:
                return float(raw)
            except ValueError:
                return 0

    def _read_keyword(self) -> str:
        data, n = self.data, len(self.data)
        start = self.pos
        while self.pos < n:
            ch = data[self.pos]
            if ch in _WHITESPACE or ch in _DELIMITERS:
                break
            self.pos += 1
        if self.pos == start:  # unexpected delimiter, consume it
            self.pos += 1
        return data[start : self.pos].decode("latin-1")


def _collect_inline_image(lexer: _Lexer, operands: list[Any]) -> dict[str, Any]:
    """Consume ``ID <binary> EI`` after a ``BI`` operator was seen."""
    info: dict[str, Any] = {}
    key: str | None = None
    while True:
        item = lexer.next_object()
        if item is None:
            return {"dictionary": info, "data_bytes": 0, "truncated": True}
        value, _offset = item
        if isinstance(value, str) and value == "ID":
            break
        if isinstance(value, dict) and "name" in value and key is None:
            key = value["name"]
            continue
        if key is not None:
            info[key] = value
            key = None
    data = lexer.data
    start = lexer.pos + 1  # single whitespace byte after ID
    n = len(data)
    cursor = start
    data_end = n
    resume = n
    while cursor < n:
        idx = data.find(b"EI", cursor)
        if idx == -1:
            break
        before_ok = idx == 0 or data[idx - 1] in _WHITESPACE
        after = data[idx + 2 : idx + 3]
        after_ok = after == b"" or after[0] in _WHITESPACE or after[0] in _DELIMITERS
        if before_ok and after_ok:
            # The whitespace byte separating the data from EI is not image data.
            data_end = idx - 1 if idx > start and data[idx - 1] in _WHITESPACE else idx
            resume = idx + 2
            break
        cursor = idx + 2
    lexer.pos = min(resume, n)
    operands.clear()
    return {"dictionary": info, "data_bytes": max(0, data_end - start)}


def parse_content_stream(
    data: bytes,
    *,
    operator_limit: int | None = None,
    operator_offset: int = 0,
    count_all: bool = False,
) -> dict[str, Any]:
    """Parse a decoded content stream into an ordered operator listing.

    Returns a dict with ``operators`` (each ``{"op", "operands", "offset",
    "description"}``), a ``truncated`` flag and simple ``operator_counts``.

    ``operator_offset`` skips that many operators before collecting, so a caller
    can walk a long stream in windows. ``count_all`` keeps lexing after the limit
    is reached to report ``total`` — it costs the rest of the parse but no extra
    memory, because the skipped operators are counted and dropped.
    """
    lexer = _Lexer(data)
    operators: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    operands: list[Any] = []
    stack: list[list[Any]] = []
    truncated = False
    seen = 0
    start = max(0, int(operator_offset))

    while True:
        item = lexer.next_object()
        if item is None:
            break
        value, offset = item
        if isinstance(value, _Token):
            if value.kind in ("array_open", "dict_open"):
                stack.append([])
            elif value.kind in ("array_close", "dict_close") and stack:
                finished = stack.pop()
                wrapper: Any = (
                    {"array": finished} if value.kind == "array_close" else {"dict": finished}
                )
                (stack[-1] if stack else operands).append(wrapper)
            continue
        if isinstance(value, str):  # operator keyword
            position = seen
            seen += 1
            counts[value] = counts.get(value, 0) + 1
            inline_image = _collect_inline_image(lexer, operands) if value == "BI" else None
            collecting = position >= start and (
                operator_limit is None or len(operators) < operator_limit
            )
            if collecting:
                entry: dict[str, Any] = {
                    "op": value,
                    "offset": offset,
                    "index": position,
                    "operands": list(operands),
                }
                if inline_image is not None:
                    entry["inline_image"] = inline_image
                description = OPERATOR_DESCRIPTIONS.get(value)
                if description:
                    entry["description"] = description
                operators.append(entry)
            operands = []
            stack = []
            reached_limit = operator_limit is not None and len(operators) >= operator_limit
            if reached_limit and not count_all:
                truncated = lexer.pos < len(data)
                break
            continue
        (stack[-1] if stack else operands).append(value)

    if count_all:
        # The whole stream was walked, so the count is exact and nothing is left.
        truncated = start + len(operators) < seen
    return {
        "operators": operators,
        "operator_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "truncated": truncated,
        "offset": start,
        "limit": operator_limit,
        "returned": len(operators),
        "total": seen if count_all else None,
        "bytes_parsed": lexer.pos,
        "bytes_total": len(data),
    }
