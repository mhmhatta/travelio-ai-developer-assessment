"""FastAPI application factory and public error translation."""

from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from travelio_classifier.api import router
from travelio_classifier.errors import ServiceError
from travelio_classifier.logging_config import configure_logging
from travelio_classifier.mock_llm import MockLLMClient
from travelio_classifier.repository import InMemoryClassificationRepository
from travelio_classifier.service import ClassificationService


async def handle_service_error(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    """Translate an expected service failure into a stable public body."""
    error = cast(ServiceError, exception)
    request_id = getattr(request.state, "request_id", uuid4())
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": str(request_id),
            }
        },
    )


def create_app(service: ClassificationService | None = None) -> FastAPI:
    """Create an application with replaceable external dependencies."""
    configure_logging()
    application = FastAPI(title="Travelio Message Classifier", version="1.0.0")
    application.state.classification_service = service or ClassificationService(
        client=MockLLMClient(),
        repository=InMemoryClassificationRepository(),
    )
    application.include_router(router)
    application.add_exception_handler(ServiceError, handle_service_error)

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Report process liveness without calling external dependencies."""
        return {"status": "ok"}

    return application


app = create_app()
