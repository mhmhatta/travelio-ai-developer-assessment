import json
import logging
from collections.abc import Sequence

import pytest
from httpx import ASGITransport, AsyncClient

from travelio_classifier.app import create_app
from travelio_classifier.logging_config import JsonFormatter
from travelio_classifier.ports import ClassificationRepository
from travelio_classifier.repository import InMemoryClassificationRepository
from travelio_classifier.service import ClassificationService, ServiceConfig

from .fakes import (
    FailingRepository,
    SequenceLLMClient,
    valid_classification_json,
)


def build_test_service(
    outcomes: Sequence[str | BaseException],
    repository: ClassificationRepository | None = None,
) -> ClassificationService:
    return ClassificationService(
        client=SequenceLLMClient(outcomes),
        repository=repository or InMemoryClassificationRepository(),
        config=ServiceConfig(initial_backoff_seconds=0.0),
    )


@pytest.mark.asyncio
async def test_classify_message_returns_200() -> None:
    app = create_app(service=build_test_service([valid_classification_json()]))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/classify-message",
            json={"message": "AC bocor, kirim teknisi"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["classification"]["intent"] == "maintenance_request"
    assert body["attempts"] == 1
    assert "request_id" in body


@pytest.mark.asyncio
async def test_timeout_returns_stable_503_response() -> None:
    app = create_app(service=build_test_service([TimeoutError("LLM timed out")] * 3))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/classify-message",
            json={"message": "hello"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_timeout"
    assert "request_id" in response.json()["error"]


@pytest.mark.asyncio
async def test_invalid_model_output_returns_502() -> None:
    app = create_app(service=build_test_service(["{"] * 3))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/classify-message",
            json={"message": "hello"},
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_llm_output"


@pytest.mark.asyncio
async def test_repository_failure_returns_503() -> None:
    app = create_app(
        service=build_test_service(
            [valid_classification_json()],
            repository=FailingRepository(),
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/classify-message",
            json={"message": "AC bocor"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "persistence_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"message": "   "},
        {"message": "hello", "unexpected": True},
    ],
)
async def test_invalid_request_returns_422(body: dict[str, object]) -> None:
    app = create_app(service=build_test_service([valid_classification_json()]))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/classify-message", json=body)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    app = create_app(service=build_test_service([valid_classification_json()]))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_json_formatter_emits_valid_json() -> None:
    record = logging.LogRecord(
        name="travelio_classifier.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="classification_completed",
        args=(),
        exc_info=None,
    )
    record.__dict__.update({"request_id": "request-123", "latency_ms": 42})

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "classification_completed"
    assert payload["request_id"] == "request-123"
    assert payload["latency_ms"] == 42


@pytest.mark.asyncio
async def test_success_log_excludes_guest_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guest_message = "AC bocor private-unit-123"
    app = create_app(service=build_test_service([valid_classification_json()]))
    api_logger = logging.getLogger("travelio_classifier.api")
    api_logger.addHandler(caplog.handler)

    try:
        with caplog.at_level(logging.INFO, logger="travelio_classifier.api"):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/classify-message",
                    json={"message": guest_message},
                )
    finally:
        api_logger.removeHandler(caplog.handler)

    completed = [
        record
        for record in caplog.records
        if record.getMessage() == "classification_completed"
    ]
    assert response.status_code == 200
    assert len(completed) == 1
    assert completed[0].__dict__["request_id"]
    assert completed[0].__dict__["latency_ms"] >= 0
    assert guest_message not in caplog.text
    assert "UNTRUSTED_GUEST_MESSAGE" not in caplog.text
