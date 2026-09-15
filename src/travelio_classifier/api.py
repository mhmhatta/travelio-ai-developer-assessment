"""HTTP routes for message classification."""

import logging
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from travelio_classifier.errors import ServiceError
from travelio_classifier.models import ClassifyMessageRequest, ClassifyMessageResponse
from travelio_classifier.service import ClassificationService

logger = logging.getLogger(__name__)
router = APIRouter()


def get_classification_service(request: Request) -> ClassificationService:
    """Read the application-scoped service dependency."""
    return cast(ClassificationService, request.app.state.classification_service)


@router.post("/classify-message", response_model=ClassifyMessageResponse)
async def classify_message(
    payload: ClassifyMessageRequest,
    request: Request,
    service: Annotated[ClassificationService, Depends(get_classification_service)],
) -> ClassifyMessageResponse:
    """Classify and persist one validated guest message."""
    request_id = uuid4()
    request.state.request_id = request_id

    try:
        response = await service.classify(payload, request_id=request_id)
    except ServiceError as error:
        logger.warning(
            "classification_failed",
            extra={"request_id": str(request_id), "error_code": error.code},
        )
        raise

    logger.info(
        "classification_completed",
        extra={
            "request_id": str(request_id),
            "attempt": response.attempts,
            "latency_ms": response.latency_ms,
        },
    )
    return response
