"""Typed application failures with stable public API metadata."""


class ServiceError(Exception):
    """Base failure translated by the HTTP boundary."""

    code: str = "service_error"
    message: str = "The classification service failed."
    status_code: int = 500

    def __init__(self) -> None:
        super().__init__(self.message)


class LLMTimeoutError(ServiceError):
    """Raised when every allowed model attempt times out."""

    code = "llm_timeout"
    message = "The classification service timed out after 3 attempts."
    status_code = 503


class InvalidLLMOutputError(ServiceError):
    """Raised when every allowed model response is invalid."""

    code = "invalid_llm_output"
    message = "The model returned invalid output after 3 attempts."
    status_code = 502


class PersistenceUnavailableError(ServiceError):
    """Raised when a valid classification cannot be stored."""

    code = "persistence_unavailable"
    message = "The classification result could not be stored."
    status_code = 503
