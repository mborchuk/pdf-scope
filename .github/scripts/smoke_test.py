"""End-to-end smoke test: upload a generated PDF and check the extraction.

Used by CI. Run locally against a server you started yourself:

    python .github/scripts/smoke_test.py http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf


def build_pdf(path: Path) -> None:
    """Create a two-page PDF with text, a drawing and an annotation."""
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((72, 100), "smoke test page", fontname="helv", fontsize=14)
    page.draw_rect(pymupdf.Rect(50, 200, 200, 300), color=(1, 0, 0), width=2)
    annot = page.add_highlight_annot(pymupdf.Rect(70, 90, 220, 110))
    annot.update()
    doc.new_page(width=400, height=500)
    doc.set_metadata({"title": "smoke"})
    doc.save(path)
    doc.close()


def post_multipart(url: str, field: str, filename: str, payload: bytes) -> dict:
    """Upload one file as multipart/form-data without extra dependencies."""
    boundary = uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/pdf\r\n\r\n",
            payload,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as response:
        return response.read()


def main(base: str) -> int:
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "smoke.pdf"
        build_pdf(source)
        created = post_multipart(f"{base}/api/documents", "files", "smoke.pdf", source.read_bytes())
        document_id = created["documents"][0]["document_id"]

        for _ in range(60):
            summary = get_json(f"{base}/api/documents/{document_id}")["document"]
            if summary["status"] in {"ready", "error", "needs_password"}:
                break
            time.sleep(0.5)

        assert summary["status"] == "ready", summary
        assert summary["page_count"] == 2, summary

        report = get_json(f"{base}/api/documents/{document_id}")["report"]
        assert report["metadata"]["info"]["title"] == "smoke", report["metadata"]
        assert report["file"]["xref"]["type_counts"]["/Page"] == 2

        page = get_json(f"{base}/api/documents/{document_id}/pages/0")
        assert "smoke test page" in page["text"]["plain"], page["text"]["plain"]
        assert page["drawings"], "the rectangle should be extracted"
        assert page["annotations"], "the highlight should be extracted"
        assert any(op["op"] == "re" for op in page["content_streams"]["operators"])

        png = get_bytes(f"{base}/api/documents/{document_id}/pages/0/render.png?dpi=72")
        assert png.startswith(b"\x89PNG"), "render did not return a PNG"

        bundle = get_bytes(f"{base}/api/documents/{document_id}/export.zip")
        assert bundle.startswith(b"PK"), "export did not return a zip"

        request = urllib.request.Request(f"{base}/api/documents/{document_id}", method="DELETE")
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 200

    print("smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"))
