"""Classification workflow with bounded retries and validated persistence."""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from travelio_classifier.errors import (
    InvalidLLMOutputError,
    LLMTimeoutError,
    PersistenceUnavailableError,
)
from travelio_classifier.models import (
    ClassificationRecord,
    ClassificationResult,
    ClassifyMessageRequest,
    ClassifyMessageResponse,
)
from travelio_classifier.ports import ClassificationRepository, LLMClient
from travelio_classifier.prompt import build_classification_prompt

FailureCategory = Literal["timeout", "invalid_output"]


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    """Bounded runtime policy for one classification request."""

    max_attempts: int = 3
    timeout_seconds: float = 5.0
    initial_backoff_seconds: float = 0.05
    human_confidence_threshold: float = 0.65

    def __post_init__(self) -> None:
        """Reject retry policies that violate the public response contract."""
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds cannot be negative")
        if not 0.0 <= self.human_confidence_threshold <= 1.0:
            raise ValueError("human_confidence_threshold must be between 0 and 1")


class ClassificationService:
    """Classify one message and persist only a validated result."""

    def __init__(
        self,
        client: LLMClient,
        repository: ClassificationRepository,
        config: ServiceConfig | None = None,
    ) -> None:
        self._client = client
        self._repository = repository
        self._config = config or ServiceConfig()

    async def classify(
        self,
        request: ClassifyMessageRequest,
        request_id: UUID,
    ) -> ClassifyMessageResponse:
        """Run bounded model attempts, validate output, and persist success."""
        started_at = time.perf_counter()
        now = datetime.now(UTC)
        prompt = build_classification_prompt(request, reference_date=now.date())
        classification, attempts = await self._complete_with_retries(prompt)

        if classification.confidence < self._config.human_confidence_threshold:
            classification = classification.model_copy(update={"needs_human": True})

        processed_at = datetime.now(UTC)
        latency_ms = max(0, round((time.perf_counter() - started_at) * 1_000))
        record = ClassificationRecord(
            request_id=request_id,
            input_message=request.message,
            conversation_context=request.conversation_context,
            parsed_output=classification,
            latency_ms=latency_ms,
            attempts=attempts,
            timestamp=processed_at,
        )

        try:
            await self._repository.save(record)
        except Exception as error:
            raise PersistenceUnavailableError from error

        return ClassifyMessageResponse(
            request_id=request_id,
            classification=classification,
            latency_ms=latency_ms,
            attempts=attempts,
            processed_at=processed_at,
        )

    async def _complete_with_retries(
        self,
        prompt: str,
    ) -> tuple[ClassificationResult, int]:
        """Retry expected provider failures and return one valid result."""
        last_failure: FailureCategory = "invalid_output"

        for attempt in range(1, self._config.max_attempts + 1):
            try:
                raw_output = await asyncio.wait_for(
                    self._client.complete(
                        prompt,
                        timeout=self._config.timeout_seconds,
                    ),
                    timeout=self._config.timeout_seconds,
                )
                payload: object = json.loads(raw_output)
                return ClassificationResult.model_validate(payload), attempt
            except TimeoutError:
                last_failure = "timeout"
            except (JSONDecodeError, ValidationError):
                last_failure = "invalid_output"

            if attempt < self._config.max_attempts:
                backoff = self._config.initial_backoff_seconds * 2 ** (attempt - 1)
                await asyncio.sleep(backoff)

        if last_failure == "timeout":
            raise LLMTimeoutError
        raise InvalidLLMOutputError
