"""Deterministic test doubles for external boundaries."""

import json
from collections.abc import Sequence

from travelio_classifier.models import ClassificationRecord


def valid_classification_json(
    *,
    intent: str = "maintenance_request",
    confidence: float = 0.9,
    needs_human: bool = False,
) -> str:
    """Return one complete mock response matching the real provider shape."""
    return json.dumps(
        {
            "intent": intent,
            "entities": {"dates": [], "location": None, "unit_type": None},
            "urgency": "high" if intent == "maintenance_request" else "low",
            "confidence": confidence,
            "needs_human": needs_human,
        }
    )


class SequenceLLMClient:
    """Return or raise configured outcomes in order."""

    def __init__(self, outcomes: Sequence[str | BaseException]) -> None:
        self._outcomes = list(outcomes)
        self.prompts: list[str] = []
        self.timeouts: list[float] = []

    async def complete(self, prompt: str, *, timeout: float = 5.0) -> str:
        """Consume one configured result for an LLM call."""
        self.prompts.append(prompt)
        self.timeouts.append(timeout)
        if not self._outcomes:
            raise AssertionError("No configured LLM outcome remains")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FailingRepository:
    """Simulate an unavailable persistence boundary."""

    async def save(self, record: ClassificationRecord) -> None:
        """Fail every persistence attempt."""
        raise RuntimeError("repository unavailable")
