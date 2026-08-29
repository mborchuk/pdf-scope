"""Access to the PDF object model: xrefs, dictionaries, name trees, struct tree.

PyMuPDF exposes indirect objects through ``Document.xref_object`` /
``xref_get_key``; everything in this module is built on those primitives so the
UI can walk the file the way a PDF reader would: catalog -> page tree -> page ->
resources -> individual objects.
"""

from __future__ import annotations

import re
from typing import Any

import pymupdf

from .errors import ObjectNotFoundError
from .schema import XREF_SCAN_LIMIT

_REFERENCE_RE = re.compile(rb"(\d+)\s+(\d+)\s+R")
_NULL = ("null", "null")

#: Objects reached while walking a name tree or the structure tree are capped so
#: a hostile or simply enormous file cannot exhaust memory.
DEFAULT_NODE_LIMIT = 5_000


def _key(doc: pymupdf.Document, xref: int, path: str) -> tuple[str, str] | None:
    """Return ``xref_get_key`` result, or ``None`` when the key is absent."""
    try:
        result = doc.xref_get_key(xref, path)
    except Exception:
        return None
    if result is None or tuple(result) == _NULL:
        return None
    return result


def key_value(doc: pymupdf.Document, xref: int, path: str) -> str | None:
    """Return the raw source of a dictionary entry, or ``None``."""
    result = _key(doc, xref, path)
    return None if result is None else result[1]


def resolve_reference(value: str | None) -> int | None:
    """Return the xref number of an ``N 0 R`` reference string."""
    if not value:
        return None
    match = _REFERENCE_RE.fullmatch(value.strip().encode("latin-1", "replace"))
    return int(match.group(1)) if match else None


def find_references(source: str | None) -> list[int]:
    """Return every indirect reference found in an object source string."""
    if not source:
        return []
    found = {int(m.group(1)) for m in _REFERENCE_RE.finditer(source.encode("latin-1", "replace"))}
    return sorted(found)


def describe_object(
    doc: pymupdf.Document,
    xref: int,
    *,
    include_stream: bool = False,
    stream_limit: int = 200_000,
) -> dict[str, Any]:
    """Describe one indirect object: type, dictionary entries, stream, refs."""
    if xref < 1 or xref >= doc.xref_length():
        raise ObjectNotFoundError(f"xref {xref} is outside 1..{doc.xref_length() - 1}")

    try:
        source = doc.xref_object(xref, compressed=False)
    except Exception as exc:  # unusable object, still report it
        return {
            "xref": xref,
            "error": f"object could not be read: {exc}",
            "is_stream": False,
            "entries": {},
            "references": [],
        }

    try:
        keys = list(doc.xref_get_keys(xref))
    except Exception:
        keys = []

    entries: dict[str, Any] = {}
    for name in keys:
        result = _key(doc, xref, name)
        if result is None:
            continue
        kind, value = result
        entry: dict[str, Any] = {"type": kind, "value": value}
        target = resolve_reference(value) if kind == "xref" else None
        if target is not None:
            entry["xref"] = target
        entries[name] = entry

    is_stream = bool(doc.xref_is_stream(xref))
    info: dict[str, Any] = {
        "xref": xref,
        "type": (entries.get("Type", {}).get("value") if entries else None),
        "subtype": (entries.get("Subtype", {}).get("value") if entries else None),
        "is_stream": is_stream,
        "source": source,
        "entries": entries,
        "references": find_references(source),
    }

    if is_stream:
        try:
            raw = doc.xref_stream_raw(xref)
            info["stream_raw_bytes"] = len(raw)
        except Exception as exc:
            info["stream_raw_bytes"] = None
            info["stream_raw_error"] = str(exc)
        try:
            decoded = doc.xref_stream(xref)
            info["stream_decoded_bytes"] = len(decoded)
            if include_stream:
                text = decoded[:stream_limit].decode("utf-8", "replace")
                info["stream_decoded"] = text
                info["stream_truncated"] = len(decoded) > stream_limit
        except Exception as exc:
            info["stream_decoded_bytes"] = None
            info["stream_decode_error"] = (
                f"stream could not be decoded by PyMuPDF/MuPDF ({exc}); the filter chain "
                "may be unsupported or the stream may be damaged"
            )

    return info


def scan_xref_table(doc: pymupdf.Document, *, limit: int = XREF_SCAN_LIMIT) -> dict[str, Any]:
    """Profile every object in the file: type histogram, streams, object streams."""
    length = doc.xref_length()
    scanned = min(length, limit + 1)
    type_counts: dict[str, int] = {}
    stream_count = 0
    object_streams: list[int] = []
    xref_streams: list[int] = []
    free_or_null = 0

    for xref in range(1, scanned):
        result = _key(doc, xref, "Type")
        obj_type = result[1] if result else None
        if obj_type is None:
            free_or_null += 1
        else:
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
            if obj_type == "/ObjStm":
                object_streams.append(xref)
            elif obj_type == "/XRef":
                xref_streams.append(xref)
        try:
            if doc.xref_is_stream(xref):
                stream_count += 1
        except Exception:
            continue

    return {
        "xref_length": length,
        "objects_scanned": max(0, scanned - 1),
        "scan_truncated": length > scanned,
        "type_counts": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
        "objects_without_type": free_or_null,
        "stream_objects": stream_count,
        "object_streams": object_streams,
        "uses_object_streams": bool(object_streams),
        "cross_reference_streams": xref_streams,
        "uses_cross_reference_streams": bool(xref_streams),
    }


def page_tree(doc: pymupdf.Document, *, node_limit: int = DEFAULT_NODE_LIMIT) -> dict[str, Any]:
    """Walk ``/Root /Pages`` and return the page tree with its inherited nodes."""
    catalog = doc.pdf_catalog()
    root_ref = resolve_reference(key_value(doc, catalog, "Pages"))
    if root_ref is None:
        return {
            "root": None,
            "note": "catalog has no /Pages entry (document may be damaged or not a PDF)",
        }

    visited: set[int] = set()
    truncated = False

    def walk(xref: int, depth: int) -> dict[str, Any]:
        nonlocal truncated
        if xref in visited or len(visited) >= node_limit or depth > 64:
            truncated = True
            return {"xref": xref, "truncated": True}
        visited.add(xref)
        node: dict[str, Any] = {
            "xref": xref,
            "type": key_value(doc, xref, "Type"),
            "count": key_value(doc, xref, "Count"),
            "inherited": {
                name: key_value(doc, xref, name)
                for name in ("MediaBox", "CropBox", "Resources", "Rotate")
                if key_value(doc, xref, name) is not None
            },
        }
        kids_raw = key_value(doc, xref, "Kids")
        if kids_raw:
            node["kids"] = [walk(ref, depth + 1) for ref in find_references(kids_raw)]
        return node

    tree = walk(root_ref, 0)
    return {"root": tree, "nodes": len(visited), "truncated": truncated}


def _name_tree_entries(
    doc: pymupdf.Document,
    xref: int,
    *,
    node_limit: int,
) -> list[dict[str, Any]]:
    """Collect ``(key, value)`` pairs from a PDF name tree rooted at ``xref``."""
    entries: list[dict[str, Any]] = []
    stack = [xref]
    seen: set[int] = set()
    while stack and len(entries) < node_limit:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        names_raw = key_value(doc, current, "Names")
        if names_raw:
            tokens = _split_array(names_raw)
            for index in range(0, len(tokens) - 1, 2):
                entries.append({"key": tokens[index], "value": tokens[index + 1]})
        kids_raw = key_value(doc, current, "Kids")
        if kids_raw:
            stack.extend(find_references(kids_raw))
    return entries


def _split_array(source: str) -> list[str]:
    """Split a flat PDF array source into top-level tokens."""
    text = source.strip()
    if text.startswith("["):
        text = text[1:]
    if text.endswith("]"):
        text = text[:-1]
    tokens: list[str] = []
    buffer = ""
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in "([<":
            depth += 1
        elif char in ")]>":
            depth -= 1
        if char.isspace() and depth <= 0:
            if buffer:
                tokens.append(buffer)
                buffer = ""
            index += 1
            continue
        buffer += char
        index += 1
    if buffer:
        tokens.append(buffer)
    # Re-join "N 0 R" triples that whitespace splitting broke apart.
    merged: list[str] = []
    index = 0
    while index < len(tokens):
        if (
            index + 2 < len(tokens)
            and tokens[index].isdigit()
            and tokens[index + 1].isdigit()
            and tokens[index + 2] == "R"
        ):
            merged.append(" ".join(tokens[index : index + 3]))
            index += 3
        else:
            merged.append(tokens[index])
            index += 1
    return merged


def parse_dict_source(source: str | None) -> list[tuple[str, str]]:
    """Split a direct dictionary source ``<< /A 1 /B 2 >>`` into name/value pairs.

    PyMuPDF only assigns an xref to indirect objects, so dictionaries written
    inline (a page's ``/Resources`` very often is) have to be read from source.
    """
    if not source:
        return []
    text = source.strip()
    if text.startswith("<<"):
        text = text[2:]
    if text.endswith(">>"):
        text = text[:-2]

    pairs: list[tuple[str, str]] = []
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index >= length or text[index] != "/":
            break
        start = index + 1
        index = start
        while index < length and not text[index].isspace() and text[index] not in "/<[(":
            index += 1
        name = text[start:index]
        while index < length and text[index].isspace():
            index += 1
        value_start = index
        depth = 0
        if index < length and text[index] == "/":
            # A name value: consume it, then stop at the next key.
            index += 1
            while index < length and not text[index].isspace() and text[index] not in "/<[(":
                index += 1
        else:
            while index < length:
                char = text[index]
                if char in "<[(":
                    depth += 1
                elif char in ">])":
                    depth -= 1
                elif char == "/" and depth <= 0:
                    break
                index += 1
        pairs.append((name, text[value_start:index].strip()))
    return pairs


def name_trees(doc: pymupdf.Document, *, node_limit: int = DEFAULT_NODE_LIMIT) -> dict[str, Any]:
    """Return the catalog ``/Names`` sub-trees that carry user-visible content."""
    catalog = doc.pdf_catalog()
    names_ref = resolve_reference(key_value(doc, catalog, "Names"))
    result: dict[str, Any] = {"names_xref": names_ref, "trees": {}}
    if names_ref is None:
        return result
    for tree_name in (
        "Dests",
        "JavaScript",
        "EmbeddedFiles",
        "AP",
        "Pages",
        "Templates",
        "URLS",
        "IDS",
        "Renditions",
        "AlternatePresentations",
    ):
        subtree = resolve_reference(key_value(doc, names_ref, tree_name))
        if subtree is None:
            continue
        result["trees"][tree_name] = {
            "xref": subtree,
            "entries": _name_tree_entries(doc, subtree, node_limit=node_limit),
        }
    return result


def collect_javascript(doc: pymupdf.Document) -> list[dict[str, Any]]:
    """Return document-level JavaScript actions (``/Names /JavaScript``)."""
    scripts: list[dict[str, Any]] = []
    trees = name_trees(doc)["trees"]
    js_tree = trees.get("JavaScript")
    if not js_tree:
        return scripts
    for entry in js_tree["entries"]:
        action_xref = resolve_reference(entry["value"])
        record: dict[str, Any] = {"name": entry["key"], "xref": action_xref}
        if action_xref is not None:
            source = key_value(doc, action_xref, "JS")
            if source and source.strip().endswith(" R"):
                stream_xref = resolve_reference(source)
                if stream_xref is not None:
                    try:
                        source = doc.xref_stream(stream_xref).decode("utf-8", "replace")
                    except Exception as exc:
                        source = f"<stream {stream_xref} unreadable: {exc}>"
            record["script"] = source
        scripts.append(record)
    return scripts


def structure_tree(
    doc: pymupdf.Document,
    *,
    node_limit: int = DEFAULT_NODE_LIMIT,
) -> dict[str, Any] | None:
    """Walk ``/StructTreeRoot`` (logical structure / tagging), if present.

    PyMuPDF has no dedicated structure-tree API, so the tree is reconstructed
    from raw objects.  Nodes report their ``/S`` tag, ``/T`` title, ``/Alt``
    text, ``/Pg`` page reference and children.
    """
    catalog = doc.pdf_catalog()
    root_ref = resolve_reference(key_value(doc, catalog, "StructTreeRoot"))
    if root_ref is None:
        return None

    visited: set[int] = set()
    truncated = False

    def walk(xref: int, depth: int) -> dict[str, Any]:
        nonlocal truncated
        if xref in visited or len(visited) >= node_limit or depth > 64:
            truncated = True
            return {"xref": xref, "truncated": True}
        visited.add(xref)
        node: dict[str, Any] = {
            "xref": xref,
            "type": key_value(doc, xref, "Type"),
            "tag": key_value(doc, xref, "S"),
            "title": key_value(doc, xref, "T"),
            "alt": key_value(doc, xref, "Alt"),
            "actual_text": key_value(doc, xref, "ActualText"),
            "language": key_value(doc, xref, "Lang"),
            "page": resolve_reference(key_value(doc, xref, "Pg")),
        }
        kids_raw = key_value(doc, xref, "K")
        if kids_raw:
            children = find_references(kids_raw)
            if children:
                node["kids"] = [walk(ref, depth + 1) for ref in children]
            else:
                # Marked-content identifiers (integers) rather than objects.
                node["marked_content"] = kids_raw
        return node

    return {
        "root_xref": root_ref,
        "role_map": key_value(doc, root_ref, "RoleMap"),
        "class_map": key_value(doc, root_ref, "ClassMap"),
        "parent_tree": key_value(doc, root_ref, "ParentTree"),
        "tree": walk(root_ref, 0),
        "nodes": len(visited),
        "truncated": truncated,
    }


def page_resources(doc: pymupdf.Document, page: pymupdf.Page) -> dict[str, Any]:
    """Expand a page ``/Resources`` dictionary one level deep, per category."""
    page_xref = page.xref
    resources_raw = key_value(doc, page_xref, "Resources")
    resources_xref = resolve_reference(resources_raw)
    result: dict[str, Any] = {
        "raw": resources_raw,
        "xref": resources_xref,
        "inherited": resources_raw is None,
        "categories": {},
    }

    def category_source(name: str) -> tuple[str | None, int | None]:
        if resources_xref is not None:
            value = key_value(doc, resources_xref, name)
            return value, resolve_reference(value)
        value = key_value(doc, page_xref, f"Resources/{name}")
        return value, resolve_reference(value)

    for category in (
        "Font",
        "XObject",
        "ColorSpace",
        "Pattern",
        "Shading",
        "ExtGState",
        "Properties",
        "ProcSet",
    ):
        raw, sub_xref = category_source(category)
        if raw is None:
            continue
        if sub_xref is not None:
            pairs = [
                (member_name, key_value(doc, sub_xref, member_name) or "")
                for member_name in _safe_keys(doc, sub_xref)
            ]
        else:
            # The category dictionary is written directly inside /Resources.
            pairs = parse_dict_source(raw)

        members: list[dict[str, Any]] = []
        for member_name, value in pairs:
            member_xref = resolve_reference(value)
            member: dict[str, Any] = {
                "name": f"/{member_name}",
                "value": value,
                "xref": member_xref,
            }
            if member_xref is not None:
                member["type"] = key_value(doc, member_xref, "Type")
                member["subtype"] = key_value(doc, member_xref, "Subtype")
            members.append(member)
        result["categories"][category] = {
            "raw": raw,
            "xref": sub_xref,
            "members": members,
        }
    return result


def _safe_keys(doc: pymupdf.Document, xref: int) -> list[str]:
    try:
        return list(doc.xref_get_keys(xref))
    except Exception:
        return []
