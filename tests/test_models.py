from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from travelio_classifier.models import (
    ClassificationRecord,
    ClassificationResult,
    ClassifyMessageRequest,
    Intent,
)


def test_request_rejects_blank_message() -> None:
    with pytest.raises(ValidationError):
        ClassifyMessageRequest(message="   ")


def test_classification_accepts_iso_dates() -> None:
    result = ClassificationResult.model_validate(
        {
            "intent": "booking_inquiry",
            "entities": {
                "dates": [
                    {"kind": "check_in", "value": "2027-03-12"},
                    {"kind": "check_out", "value": "2027-03-15"},
                ],
                "location": "Kemang",
                "unit_type": "2br",
            },
            "urgency": "low",
            "confidence": 0.94,
            "needs_human": False,
        }
    )

    assert result.entities.dates[0].value == date(2027, 3, 12)
    assert result.intent is Intent.BOOKING_INQUIRY


def test_unknown_intent_requires_human() -> None:
    result = ClassificationResult.model_validate(
        {
            "intent": "unknown",
            "entities": {"dates": [], "location": None, "unit_type": None},
            "urgency": "low",
            "confidence": 0.8,
            "needs_human": False,
        }
    )

    assert result.needs_human is True


def test_record_uses_utc_timestamp() -> None:
    record = ClassificationRecord(
        request_id="9fc8e0c0-0f45-4c34-9ce7-d738747aae32",
        input_message="bayar dimana ya",
        conversation_context=[],
        parsed_output=ClassificationResult(
            intent="payment_question",
            entities={"dates": [], "location": None, "unit_type": None},
            urgency="low",
            confidence=0.6,
            needs_human=True,
        ),
        latency_ms=25,
        attempts=1,
        timestamp=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert record.timestamp.utcoffset() == UTC.utcoffset(record.timestamp)
