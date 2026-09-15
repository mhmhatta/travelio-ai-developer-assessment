"""Local persistence adapter used by the runnable assessment."""

import asyncio

from travelio_classifier.models import ClassificationRecord


class InMemoryClassificationRepository:
    """Store records in process memory behind an async-safe boundary."""

    def __init__(self) -> None:
        self._records: list[ClassificationRecord] = []
        self._lock = asyncio.Lock()

    async def save(self, record: ClassificationRecord) -> None:
        """Append one validated record without exposing internal state."""
        async with self._lock:
            self._records.append(record)

    async def list_all(self) -> list[ClassificationRecord]:
        """Return a snapshot for tests and local inspection."""
        async with self._lock:
            return list(self._records)
