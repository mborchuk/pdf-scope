"""Process pool used for all PDF work.

PyMuPDF's documentation is explicit: "PyMuPDF does not support running on
multiple threads - doing so may cause incorrect behaviour or even crash Python
itself", and recommends ``multiprocessing`` instead. Extraction is also
CPU-bound, so running it in the event loop would block every other request.

All PDF work therefore goes through a ``ProcessPoolExecutor`` whose size caps
how many extractions can run at once; a semaphore queues the rest so a burst of
uploads cannot spawn unbounded work.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")


def default_worker_count() -> int:
    """Worker count: overridable, otherwise a small share of the CPUs."""
    configured = os.environ.get("PDF_DECOMPILER_WORKERS")
    if configured and configured.isdigit() and int(configured) > 0:
        return int(configured)
    return max(1, min(4, (os.cpu_count() or 2)))


class ExtractionPool:
    """Async facade over a process pool with a concurrency cap."""

    def __init__(self, workers: int | None = None) -> None:
        self.workers = workers or default_worker_count()
        self._executor: ProcessPoolExecutor | None = None
        self._semaphore = asyncio.Semaphore(self.workers)
        self._running = 0

    def start(self) -> None:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=self.workers)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    @property
    def running(self) -> int:
        return self._running

    def status(self) -> dict[str, Any]:
        return {
            "workers": self.workers,
            "running": self._running,
            "started": self._executor is not None,
        }

    async def run(self, func: Callable[..., T], *args: Any) -> T:
        """Run ``func(*args)`` in a worker process, waiting for a free slot."""
        if self._executor is None:
            self.start()
        assert self._executor is not None
        async with self._semaphore:
            self._running += 1
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(self._executor, func, *args)
            finally:
                self._running -= 1
