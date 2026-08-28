"""Document registry: identity, artifact directories and lifecycle.

State model (deliberately the simple one):

* the registry lives in memory for the lifetime of the server process,
* artifacts live on disk under the workspace directory, one directory per
  document id,
* the workspace is emptied when the server starts, so a restart is a clean
  slate and no stale files survive.

Every document gets a fresh UUID, so uploading the same file twice, or two
different files with the same name, produces two independent entries that
cannot collide.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Maximum number of documents that may be open at once.
MAX_OPEN_DOCUMENTS = 25

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_stem(name: str) -> str:
    """Make a filename fragment that is safe for downloads and archives."""
    stem = Path(name).stem or "document"
    cleaned = _SAFE_NAME.sub("_", stem).strip("._-")
    return (cleaned or "document")[:60]


@dataclass
class DocumentRecord:
    """One open document and everything the server knows about it."""

    document_id: str
    source_name: str
    directory: Path
    size_bytes: int
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending | analyzing | ready | needs_password | error
    stage: str = "queued"
    error: str | None = None
    page_count: int | None = None
    sha256: str | None = None
    password: str | None = None
    report: dict[str, Any] | None = None
    duplicate_of: str | None = None

    @property
    def source_path(self) -> Path:
        return self.directory / "source.pdf"

    @property
    def image_dir(self) -> Path:
        return self.directory / "images"

    @property
    def cache_dir(self) -> Path:
        return self.directory / "cache"

    @property
    def export_dir(self) -> Path:
        return self.directory / "exports"

    @property
    def file_prefix(self) -> str:
        """Prefix identifying source PDF and document id in download names."""
        return f"{safe_stem(self.source_name)}--{self.document_id[:8]}"

    def to_json(self) -> dict[str, Any]:
        """Summary used by the document list in the UI."""
        return {
            "document_id": self.document_id,
            "source_name": self.source_name,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "status": self.status,
            "stage": self.stage,
            "error": self.error,
            "page_count": self.page_count,
            "sha256": self.sha256,
            "duplicate_of": self.duplicate_of,
            "file_prefix": self.file_prefix,
        }


class DocumentRegistry:
    """In-memory registry over an on-disk workspace."""

    def __init__(self, workspace: Path, *, max_documents: int = MAX_OPEN_DOCUMENTS) -> None:
        self.workspace = workspace
        self.max_documents = max_documents
        self._documents: dict[str, DocumentRecord] = {}

    def reset_workspace(self) -> None:
        """Clear the workspace directory; called once on server start."""
        if self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)
        self.workspace.mkdir(parents=True, exist_ok=True)

    def __contains__(self, document_id: str) -> bool:
        return document_id in self._documents

    def __len__(self) -> int:
        return len(self._documents)

    def list(self) -> list[DocumentRecord]:
        return sorted(self._documents.values(), key=lambda record: record.created_at)

    def get(self, document_id: str) -> DocumentRecord | None:
        return self._documents.get(document_id)

    def create(self, source_name: str, payload: bytes) -> DocumentRecord:
        """Store an uploaded file and register it under a new document id."""
        if len(self._documents) >= self.max_documents:
            raise ValueError(
                f"limit of {self.max_documents} open documents reached; close one first"
            )
        document_id = uuid.uuid4().hex
        directory = self.workspace / document_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "images").mkdir(exist_ok=True)
        (directory / "cache").mkdir(exist_ok=True)
        (directory / "exports").mkdir(exist_ok=True)
        record = DocumentRecord(
            document_id=document_id,
            source_name=source_name or "document.pdf",
            directory=directory,
            size_bytes=len(payload),
        )
        record.source_path.write_bytes(payload)
        self._documents[document_id] = record
        return record

    def find_duplicate(self, sha256: str, *, exclude: str) -> DocumentRecord | None:
        """Return an already-open document with the same content, if any."""
        for record in self._documents.values():
            if record.document_id != exclude and record.sha256 == sha256:
                return record
        return None

    def remove(self, document_id: str) -> bool:
        """Close a document and delete every artifact belonging to it."""
        record = self._documents.pop(document_id, None)
        if record is None:
            return False
        shutil.rmtree(record.directory, ignore_errors=True)
        return True

    def clear(self) -> None:
        for document_id in list(self._documents):
            self.remove(document_id)
