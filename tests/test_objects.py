"""Object model access and the content-stream parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_scope.core import describe_object, open_document
from pdf_scope.core.contentstream import parse_content_stream
from pdf_scope.core.errors import ObjectNotFoundError
from pdf_scope.core.objects import (
    find_references,
    page_tree,
    parse_dict_source,
    resolve_reference,
    scan_xref_table,
)


def test_describe_catalog_and_follow_references(rich_pdf: Path) -> None:
    doc = open_document(rich_pdf)
    try:
        catalog = describe_object(doc, doc.pdf_catalog())
        assert catalog["type"] == "/Catalog"
        assert catalog["entries"]["Pages"]["type"] == "xref"
        pages_xref = catalog["entries"]["Pages"]["xref"]
        assert pages_xref in catalog["references"]

        pages = describe_object(doc, pages_xref)
        assert pages["type"] == "/Pages"
        assert pages["references"], "page tree references its kids"
    finally:
        doc.close()


def test_stream_objects_expose_sizes(rich_pdf: Path) -> None:
    doc = open_document(rich_pdf)
    try:
        page = doc.load_page(0)
        content_xref = page.get_contents()[0]
        obj = describe_object(doc, content_xref, include_stream=True)
        assert obj["is_stream"] is True
        assert obj["stream_decoded_bytes"] > 0
        assert "BT" in obj["stream_decoded"]
    finally:
        doc.close()


def test_unknown_xref_raises(rich_pdf: Path) -> None:
    doc = open_document(rich_pdf)
    try:
        with pytest.raises(ObjectNotFoundError):
            describe_object(doc, doc.xref_length() + 10)
    finally:
        doc.close()


def test_xref_scan_and_page_tree(rich_pdf: Path) -> None:
    doc = open_document(rich_pdf)
    try:
        scan = scan_xref_table(doc)
        assert scan["type_counts"]["/Page"] == 2
        assert scan["stream_objects"] >= 1
        tree = page_tree(doc)
        assert tree["root"]["type"] == "/Pages"
        assert len(tree["root"]["kids"]) == 2
    finally:
        doc.close()


def test_reference_helpers() -> None:
    assert resolve_reference("12 0 R") == 12
    assert resolve_reference("/Name") is None
    assert find_references("<</A 3 0 R /B [4 0 R 5 0 R]>>") == [3, 4, 5]


def test_dict_source_parser() -> None:
    pairs = parse_dict_source("<</F1 5 0 R/Sub<</A 1/B[1 2 3]>>/N /Foo/S (a/b)>>")
    assert pairs == [
        ("F1", "5 0 R"),
        ("Sub", "<</A 1/B[1 2 3]>>"),
        ("N", "/Foo"),
        ("S", "(a/b)"),
    ]


def test_content_stream_parser_basics() -> None:
    data = b"q 1 0 0 1 10 20 cm /F1 12 Tf BT (Hi \\(there\\)) Tj ET [ (a) -250 (b) ] TJ Q"
    parsed = parse_content_stream(data)
    ops = [item["op"] for item in parsed["operators"]]
    assert ops == ["q", "cm", "Tf", "BT", "Tj", "ET", "TJ", "Q"]

    cm = parsed["operators"][1]
    assert cm["operands"] == [1, 0, 0, 1, 10, 20]
    assert parsed["operators"][4]["operands"][0]["string"] == "Hi (there)"
    assert parsed["operators"][2]["operands"][0]["name"] == "/F1"
    array = parsed["operators"][6]["operands"][0]["array"]
    assert array[1] == -250
    assert parsed["operator_counts"]["Tj"] == 1


def test_content_stream_parser_inline_image() -> None:
    data = b"BI /W 2 /H 2 /CS /G /BPC 8 ID \x01\x02\x03\x04 EI Q"
    parsed = parse_content_stream(data)
    inline = parsed["operators"][0]
    assert inline["op"] == "BI"
    assert inline["inline_image"]["dictionary"]["/W"] == 2
    assert inline["inline_image"]["data_bytes"] == 4
    assert parsed["operators"][1]["op"] == "Q"


def test_content_stream_operator_limit() -> None:
    data = b"q Q " * 100
    parsed = parse_content_stream(data, operator_limit=10)
    assert len(parsed["operators"]) == 10
    assert parsed["truncated"] is True
