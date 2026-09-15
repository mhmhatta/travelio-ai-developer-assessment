"""Interfaces for external classification dependencies."""

from typing import Protocol

from travelio_classifier.models import ClassificationRecord


class LLMClient(Protocol):
    """Generate a raw classification response from a prompt."""

    async def complete(self, prompt: str, *, timeout: float = 5.0) -> str:
        """Return raw model text or raise a provider exception."""
        ...


class ClassificationRepository(Protocol):
    """Persist successfully validated classification records."""

    async def save(self, record: ClassificationRecord) -> None:
        """Persist one immutable classification record."""
        ...
