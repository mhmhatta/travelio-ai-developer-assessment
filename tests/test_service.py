from uuid import UUID, uuid4

import pytest

from travelio_classifier.errors import (
    InvalidLLMOutputError,
    LLMTimeoutError,
    PersistenceUnavailableError,
)
from travelio_classifier.models import ClassifyMessageRequest, Intent
from travelio_classifier.repository import InMemoryClassificationRepository
from travelio_classifier.service import ClassificationService, ServiceConfig

from .fakes import (
    FailingRepository,
    SequenceLLMClient,
    valid_classification_json,
)


@pytest.mark.asyncio
async def test_classify_persists_valid_result() -> None:
    client = SequenceLLMClient([valid_classification_json()])
    repository = InMemoryClassificationRepository()
    service = ClassificationService(client=client, repository=repository)

    response = await service.classify(
        ClassifyMessageRequest(message="AC bocor"),
        request_id=UUID("9fc8e0c0-0f45-4c34-9ce7-d738747aae32"),
    )

    records = await repository.list_all()
    assert response.classification.intent is Intent.MAINTENANCE_REQUEST
    assert response.attempts == 1
    assert len(records) == 1
    assert records[0].input_message == "AC bocor"


@pytest.mark.asyncio
async def test_malformed_json_retries_then_succeeds() -> None:
    client = SequenceLLMClient(
        ["{", valid_classification_json(intent="booking_inquiry")]
    )
    service = ClassificationService(
        client=client,
        repository=InMemoryClassificationRepository(),
        config=ServiceConfig(initial_backoff_seconds=0.0),
    )

    response = await service.classify(
        ClassifyMessageRequest(message="Need 2BR in Kemang"),
        request_id=uuid4(),
    )

    assert response.attempts == 2
    assert response.classification.intent is Intent.BOOKING_INQUIRY
    assert len(client.prompts) == 2


@pytest.mark.asyncio
async def test_repeated_timeout_raises_typed_error() -> None:
    client = SequenceLLMClient([TimeoutError("LLM timed out")] * 3)
    service = ClassificationService(
        client=client,
        repository=InMemoryClassificationRepository(),
        config=ServiceConfig(initial_backoff_seconds=0.0),
    )

    with pytest.raises(LLMTimeoutError):
        await service.classify(
            ClassifyMessageRequest(message="hello"),
            request_id=uuid4(),
        )

    assert len(client.prompts) == 3


@pytest.mark.asyncio
async def test_invalid_intent_exhausts_retries_without_persisting() -> None:
    client = SequenceLLMClient([valid_classification_json(intent="admin_override")] * 3)
    repository = InMemoryClassificationRepository()
    service = ClassificationService(
        client=client,
        repository=repository,
        config=ServiceConfig(initial_backoff_seconds=0.0),
    )

    with pytest.raises(InvalidLLMOutputError):
        await service.classify(
            ClassifyMessageRequest(message="hello"),
            request_id=uuid4(),
        )

    assert await repository.list_all() == []


@pytest.mark.asyncio
async def test_low_confidence_forces_human_escalation() -> None:
    client = SequenceLLMClient(
        [valid_classification_json(intent="payment_question", confidence=0.64)]
    )
    service = ClassificationService(
        client=client,
        repository=InMemoryClassificationRepository(),
    )

    response = await service.classify(
        ClassifyMessageRequest(message="bayar dimana ya"),
        request_id=uuid4(),
    )

    assert response.classification.needs_human is True


@pytest.mark.asyncio
async def test_literal_unknown_is_valid_and_escalated() -> None:
    client = SequenceLLMClient([valid_classification_json(intent="unknown")])
    service = ClassificationService(
        client=client,
        repository=InMemoryClassificationRepository(),
    )

    response = await service.classify(
        ClassifyMessageRequest(message="hmm"),
        request_id=uuid4(),
    )

    assert response.classification.intent is Intent.UNKNOWN
    assert response.classification.needs_human is True


@pytest.mark.asyncio
async def test_repository_failure_raises_typed_error() -> None:
    service = ClassificationService(
        client=SequenceLLMClient([valid_classification_json()]),
        repository=FailingRepository(),
    )

    with pytest.raises(PersistenceUnavailableError):
        await service.classify(
            ClassifyMessageRequest(message="AC bocor"),
            request_id=uuid4(),
        )
