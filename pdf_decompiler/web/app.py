"""FastAPI application: thin HTTP layer over the extraction core.

Why FastAPI: the UI needs concurrent uploads and per-document progress, so the
server has to stay responsive while CPU-bound extraction runs elsewhere.
FastAPI's async endpoints combine directly with a ``ProcessPoolExecutor``
(``await pool.run(...)``), it serves the static UI and file downloads out of the
box, and it needs no extra machinery beyond uvicorn.

This module contains no PDF logic: every PDF operation is a call into
``pdf_decompiler.core`` executed in a worker process.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..core import SCHEMA_VERSION, dumps
from ..core.errors import (
    DocumentOpenError,
    ImageDecodeError,
    ObjectNotFoundError,
    PageNotFoundError,
    PasswordRequiredError,
)
from . import tasks
from .jobs import ExtractionPool
from .registry import DocumentRecord, DocumentRegistry

STATIC_DIR = Path(__file__).parent / "static"

#: Uploads larger than this are rejected outright (local tool, sane ceiling).
MAX_UPLOAD_BYTES = int(os.environ.get("PDF_DECOMPILER_MAX_UPLOAD_MB", "512")) * 1024 * 1024


def workspace_dir() -> Path:
    configured = os.environ.get("PDF_DECOMPILER_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd() / ".workspace"


registry = DocumentRegistry(workspace_dir())
pool = ExtractionPool()


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.reset_workspace()
    pool.start()
    try:
        yield
    finally:
        registry.clear()
        pool.shutdown()


app = FastAPI(title="PDF decompiler", version=SCHEMA_VERSION, lifespan=lifespan)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _require(document_id: str) -> DocumentRecord:
    record = registry.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown document id {document_id}")
    return record


def _require_ready(document_id: str) -> DocumentRecord:
    record = _require(document_id)
    if record.status == "needs_password":
        raise HTTPException(status_code=423, detail="document is locked; supply a password")
    if record.status == "error":
        raise HTTPException(status_code=422, detail=record.error or "document failed to open")
    if record.status != "ready":
        raise HTTPException(status_code=409, detail=f"document is {record.status}")
    return record


def _json(data: Any, *, filename: str | None = None) -> Response:
    """Serialise with the core encoder so PyMuPDF values never break JSON."""
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if filename else None
    return Response(
        content=dumps(data, indent=2 if filename else None),
        media_type="application/json",
        headers=headers,
    )


def _text_response(body: str, filename: str, media_type: str = "text/plain") -> Response:
    return Response(
        content=body,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _analyze(record: DocumentRecord) -> None:
    """Run document-level analysis for one record, updating its status."""
    record.status = "analyzing"
    record.stage = "reading document structure"
    try:
        report = await pool.run(
            tasks.task_analyze_document,
            str(record.source_path),
            record.password,
            record.document_id,
            record.source_name,
        )
    except PasswordRequiredError:
        record.status = "needs_password"
        record.stage = "waiting for password"
        record.error = "document is password protected"
        return
    except (DocumentOpenError, Exception) as exc:  # one bad file must not affect others
        record.status = "error"
        record.stage = "failed"
        # Report the user's own file name, never the internal workspace path.
        record.error = (str(exc) or exc.__class__.__name__).replace(
            str(record.source_path), record.source_name
        )
        return

    record.report = report
    record.page_count = report["file"]["page_count"]
    record.sha256 = report["identity"]["sha256"]
    duplicate = registry.find_duplicate(record.sha256, exclude=record.document_id)
    record.duplicate_of = duplicate.document_id if duplicate else None
    record.status = "ready"
    record.stage = "ready"
    record.error = None


def _page_cache_path(record: DocumentRecord, page_number: int) -> Path:
    return record.cache_dir / f"page-{page_number + 1:04d}.json"


async def _page_report(record: DocumentRecord, page_number: int) -> dict[str, Any]:
    """Return a page report, using the on-disk cache when it exists."""
    cache = _page_cache_path(record, page_number)
    if cache.exists():
        try:
            return json.loads(cache.read_text("utf-8"))
        except json.JSONDecodeError:
            cache.unlink(missing_ok=True)
    report = await pool.run(
        tasks.task_analyze_page,
        str(record.source_path),
        page_number,
        record.password,
        record.document_id,
        str(record.image_dir),
    )
    cache.write_text(dumps(report), "utf-8")
    return report


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #


@app.post("/api/documents")
async def upload_documents(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Accept one or more PDFs; each is analysed independently and concurrently."""
    created: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    records: list[DocumentRecord] = []

    for upload in files:
        payload = await upload.read()
        if len(payload) > MAX_UPLOAD_BYTES:
            rejected.append(
                {
                    "source_name": upload.filename,
                    "error": f"file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
                }
            )
            continue
        try:
            record = registry.create(upload.filename or "document.pdf", payload)
        except ValueError as exc:
            rejected.append({"source_name": upload.filename, "error": str(exc)})
            continue
        records.append(record)
        created.append(record.to_json())

    # Analyses run concurrently; failures are captured per record.
    for record in records:
        asyncio.create_task(_analyze(record))

    return JSONResponse({"documents": created, "rejected": rejected}, status_code=201)


@app.get("/api/documents")
async def list_documents() -> Response:
    return _json(
        {
            "documents": [record.to_json() for record in registry.list()],
            "limits": {
                "max_documents": registry.max_documents,
                "max_upload_bytes": MAX_UPLOAD_BYTES,
            },
            "pool": pool.status(),
        }
    )


@app.get("/api/documents/{document_id}")
async def get_document(document_id: str) -> Response:
    record = _require(document_id)
    return _json({"document": record.to_json(), "report": record.report})


@app.post("/api/documents/{document_id}/unlock")
async def unlock_document(document_id: str, password: str = Body(embed=True)) -> Response:
    """Retry analysis of an encrypted document with a password."""
    record = _require(document_id)
    record.password = password
    await _analyze(record)
    if record.status == "needs_password":
        raise HTTPException(status_code=401, detail="password rejected")
    return _json({"document": record.to_json()})


@app.delete("/api/documents/{document_id}")
async def close_document(document_id: str) -> Response:
    _require(document_id)
    registry.remove(document_id)
    return _json({"closed": document_id})


@app.get("/api/documents/{document_id}/report.json")
async def download_document_report(document_id: str) -> Response:
    record = _require_ready(document_id)
    return _json(record.report, filename=f"{record.file_prefix}--document.json")


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #


@app.get("/api/documents/{document_id}/pages/{page_number}")
async def get_page(document_id: str, page_number: int) -> Response:
    record = _require_ready(document_id)
    try:
        return _json(await _page_report(record, page_number))
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"page analysis failed: {exc}") from exc


@app.get("/api/documents/{document_id}/pages/{page_number}/report.json")
async def download_page_report(document_id: str, page_number: int) -> Response:
    record = _require_ready(document_id)
    report = await _page_report(record, page_number)
    return _json(report, filename=f"{record.file_prefix}--page{page_number + 1:04d}.json")


def _parse_clip(clip: str | None) -> tuple[float, float, float, float] | None:
    """Parse a ``x0,y0,x1,y1`` query value into a rectangle."""
    if clip is None:
        return None
    parts = clip.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="clip must be four numbers: x0,y0,x1,y1")
    try:
        x0, y0, x1, y1 = (float(part) for part in parts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"clip is not numeric: {clip}") from exc
    return x0, y0, x1, y1


@app.get("/api/documents/{document_id}/pages/{page_number}/render.png")
async def render_page(
    document_id: str,
    page_number: int,
    dpi: int = Query(120, ge=24, le=400),
    clip: str | None = Query(None, description="x0,y0,x1,y1 in PyMuPDF page points"),
) -> Response:
    record = _require_ready(document_id)
    try:
        png, info = await pool.run(
            tasks.task_render_page,
            str(record.source_path),
            page_number,
            dpi,
            record.password,
            _parse_clip(clip),
        )
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"render failed: {exc}") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Render-Info": json.dumps(info),
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/documents/{document_id}/pages/{page_number}/text")
async def download_page_text(
    document_id: str,
    page_number: int,
    fmt: str = Query("txt", pattern="^(txt|md)$"),
) -> Response:
    record = _require_ready(document_id)
    body = await pool.run(
        tasks.task_page_text,
        str(record.source_path),
        page_number,
        record.password,
        fmt,
    )
    return _text_response(
        body,
        f"{record.file_prefix}--page{page_number + 1:04d}.{fmt}",
        "text/markdown" if fmt == "md" else "text/plain",
    )


@app.get("/api/documents/{document_id}/pages/{page_number}/content-stream")
async def download_content_stream(
    document_id: str,
    page_number: int,
    raw: bool = Query(False),
) -> Response:
    record = _require_ready(document_id)
    try:
        data = await pool.run(
            tasks.task_content_stream,
            str(record.source_path),
            page_number,
            record.password,
            raw,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"content stream failed: {exc}") from exc
    suffix = "raw" if raw else "decoded"
    return Response(
        content=data,
        media_type="application/octet-stream" if raw else "text/plain; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{record.file_prefix}'
                f'--page{page_number + 1:04d}--content-{suffix}.txt"'
            )
        },
    )


# --------------------------------------------------------------------------- #
# objects
# --------------------------------------------------------------------------- #


@app.get("/api/documents/{document_id}/objects/{xref}")
async def get_object(
    document_id: str,
    xref: int,
    include_stream: bool = Query(True),
) -> Response:
    record = _require_ready(document_id)
    try:
        data = await pool.run(
            tasks.task_describe_object,
            str(record.source_path),
            xref,
            record.password,
            include_stream,
        )
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"object read failed: {exc}") from exc
    return _json(data)


@app.get("/api/documents/{document_id}/objects/{xref}/stream")
async def download_object_stream(
    document_id: str,
    xref: int,
    raw: bool = Query(False),
) -> Response:
    record = _require_ready(document_id)
    try:
        data = await pool.run(
            tasks.task_object_stream,
            str(record.source_path),
            xref,
            record.password,
            raw,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"stream unavailable: {exc}") from exc
    suffix = "raw" if raw else "decoded"
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{record.file_prefix}--xref{xref}-{suffix}.bin"'
            )
        },
    )


# --------------------------------------------------------------------------- #
# images, attachments
# --------------------------------------------------------------------------- #


@app.get("/api/documents/{document_id}/images/{filename}")
async def get_image(document_id: str, filename: str) -> Response:
    record = _require_ready(document_id)
    target = (record.image_dir / filename).resolve()
    if not str(target).startswith(str(record.image_dir.resolve())) or not target.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(
        target,
        filename=f"{record.file_prefix}--{filename}",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/documents/{document_id}/images/{xref}/preview.png")
async def get_image_preview(
    document_id: str,
    xref: int,
    max_side: int = Query(2000, ge=16, le=8000),
) -> Response:
    """The same pixels as the stored image, re-encoded as PNG for display.

    Stored images keep the format the PDF used. Scanned documents often use
    JPEG 2000, JBIG2 or CCITT, which browsers cannot display, so the UI shows
    this instead and still offers the original bytes for download.
    """
    record = _require_ready(document_id)
    try:
        png, info = await pool.run(
            tasks.task_image_preview,
            str(record.source_path),
            xref,
            max_side,
            record.password,
        )
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ImageDecodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"image xref {xref} could not be previewed: {exc}"
        ) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Image-Preview-Info": json.dumps(info),
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/documents/{document_id}/images.zip")
async def download_images_zip(document_id: str) -> Response:
    record = _require_ready(document_id)
    await pool.run(
        tasks.task_extract_all_images,
        str(record.source_path),
        record.password,
        str(record.image_dir),
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(record.image_dir.glob("*")):
            if item.is_file():
                archive.write(item, f"{record.file_prefix}/images/{item.name}")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{record.file_prefix}--images.zip"'},
    )


@app.get("/api/documents/{document_id}/attachments/{index}")
async def download_attachment(document_id: str, index: int) -> Response:
    record = _require_ready(document_id)
    try:
        payload, name = await pool.run(
            tasks.task_attachment, str(record.source_path), index, record.password
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"attachment unavailable: {exc}") from exc
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{record.file_prefix}--{name}"'},
    )


# --------------------------------------------------------------------------- #
# whole-document exports
# --------------------------------------------------------------------------- #


@app.get("/api/documents/{document_id}/text")
async def download_document_text(
    document_id: str, fmt: str = Query("txt", pattern="^(txt|md)$")
) -> Response:
    record = _require_ready(document_id)
    body = await pool.run(
        tasks.task_document_text,
        str(record.source_path),
        record.password,
        fmt,
        record.source_name,
    )
    return _text_response(
        body,
        f"{record.file_prefix}--text.{fmt}",
        "text/markdown" if fmt == "md" else "text/plain",
    )


async def _bundle(record: DocumentRecord) -> Path:
    """Build (or reuse) the complete extraction bundle for one document."""
    output = record.export_dir / f"{record.file_prefix}--extraction.zip"
    record.stage = "building export bundle"
    try:
        path = await pool.run(
            tasks.task_build_bundle,
            str(record.source_path),
            str(output),
            record.password,
            record.document_id,
            record.source_name,
            str(record.image_dir),
        )
    finally:
        record.stage = "ready"
    return Path(path)


@app.get("/api/documents/{document_id}/export.zip")
async def download_document_bundle(document_id: str) -> Response:
    record = _require_ready(document_id)
    try:
        bundle = await _bundle(record)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"export failed: {exc}") from exc
    return FileResponse(
        bundle,
        media_type="application/zip",
        filename=bundle.name,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/export/all.zip")
async def download_all_bundles() -> Response:
    """One archive holding the complete extraction of every open document."""
    ready = [record for record in registry.list() if record.status == "ready"]
    if not ready:
        raise HTTPException(status_code=409, detail="no analysed documents are open")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as outer:
        for record in ready:
            try:
                bundle = await _bundle(record)
            except Exception as exc:
                outer.writestr(f"{record.file_prefix}/EXPORT-FAILED.txt", str(exc))
                continue
            with zipfile.ZipFile(bundle) as inner:
                for name in inner.namelist():
                    outer.writestr(f"{record.file_prefix}/{name}", inner.read(name))
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="pdf-decompiler-export.zip"'},
    )


# --------------------------------------------------------------------------- #
# meta + UI
# --------------------------------------------------------------------------- #


@app.get("/api/status")
async def status() -> Response:
    return _json(
        {
            "schema_version": SCHEMA_VERSION,
            "documents_open": len(registry),
            "max_documents": registry.max_documents,
            "workspace": str(registry.workspace),
            "pool": pool.status(),
        }
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text("utf-8"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
