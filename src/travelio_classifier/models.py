"""Typed contracts shared by the API, service, and repository."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]
ContextText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
LatencyMilliseconds = Annotated[int, Field(ge=0)]
AttemptCount = Annotated[int, Field(ge=1, le=3)]


class Intent(StrEnum):
    """Closed set of routing outcomes."""

    BOOKING_INQUIRY = "booking_inquiry"
    MAINTENANCE_REQUEST = "maintenance_request"
    EXTENSION_REQUEST = "extension_request"
    PAYMENT_QUESTION = "payment_question"
    OUT_OF_SCOPE = "out_of_scope"
    UNKNOWN = "unknown"


class Urgency(StrEnum):
    """Operational urgency assigned to a message."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DateKind(StrEnum):
    """Meaning of a date extracted from guest text."""

    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    EXTENSION_UNTIL = "extension_until"
    OTHER = "other"


class UnitType(StrEnum):
    """Supported inventory unit types."""

    STUDIO = "studio"
    ONE_BEDROOM = "1br"
    TWO_BEDROOM = "2br"
    THREE_BEDROOM = "3br"


class ConversationRole(StrEnum):
    """Allowed authors in supplied conversation context."""

    GUEST = "guest"
    AGENT = "agent"


class ConversationMessage(BaseModel):
    """One bounded item of prior conversation context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ConversationRole
    content: ContextText


class ClassifyMessageRequest(BaseModel):
    """Validated API input for one guest message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: MessageText
    conversation_context: Annotated[
        tuple[ConversationMessage, ...],
        Field(max_length=10),
    ] = ()


class ExtractedDate(BaseModel):
    """ISO-normalized date and its semantic role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DateKind
    value: date


class ExtractedEntities(BaseModel):
    """Optional structured values extracted from guest text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dates: tuple[ExtractedDate, ...]
    location: ShortText | None
    unit_type: UnitType | None


class ClassificationResult(BaseModel):
    """Validated routing decision returned by the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Intent
    entities: ExtractedEntities
    urgency: Urgency
    confidence: Confidence
    needs_human: bool

    @model_validator(mode="after")
    def enforce_unknown_escalation(self) -> Self:
        """Route unknown classifications to a human even if the model forgets."""
        if self.intent is Intent.UNKNOWN and not self.needs_human:
            return self.model_copy(update={"needs_human": True})
        return self


class ClassificationRecord(BaseModel):
    """Successfully validated classification persisted for audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    input_message: MessageText
    conversation_context: tuple[ConversationMessage, ...]
    parsed_output: ClassificationResult
    latency_ms: LatencyMilliseconds
    attempts: AttemptCount
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Reject timestamps whose absolute instant is ambiguous."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class ClassifyMessageResponse(BaseModel):
    """Public successful API response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    classification: ClassificationResult
    latency_ms: LatencyMilliseconds
    attempts: AttemptCount
    processed_at: datetime

    @field_validator("processed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Reject timestamps whose absolute instant is ambiguous."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("processed_at must be timezone-aware")
        return value
