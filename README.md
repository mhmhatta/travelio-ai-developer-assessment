# Travelio AI Developer Assessment

Complete submission for Parts A-E and bonus Part C4. The executable core is a
FastAPI service that classifies mixed Bahasa Indonesia and English guest
messages through the assessment's intentionally unreliable mock LLM client.
No API key or external database is required.

## Assessment answers

| Part | Answer |
|---|---|
| A | [Prompt, JSON schema, examples, and iteration](part-a-prompt.md) |
| B | [FastAPI application](src/travelio_classifier/app.py) and [tests](tests/) |
| C1-C3 | [MySQL, MongoDB, and GMV investigation](part-c-data-debugging.md) |
| C4 | [ClickHouse bonus](part-c-data-debugging.md#c4---clickhouse-bonus) |
| D | [Evaluation and observability](part-d-evaluation-observability.md) |
| E | [Dagster pipeline design](part-e-dagster-pipeline.md) |

## Architecture

```text
POST /classify-message
  -> ClassificationService
       -> LLMClient protocol -> provided MockLLMClient
       -> ClassificationRepository protocol -> in-memory repository
```

I kept the structure simple and separated each responsibility so the behavior is easier to understand and test.

- API layer: receives the request, handles request validation, and maps service errors into HTTP responses.
- Classification service: builds the prompt, calls the LLM, handles retries and timeouts, validates the result with Pydantic, measures latency, and persists valid classifications.
- LLM client: uses the provided `MockLLMClient` from the assessment.
- Repository: uses an in-memory implementation for local execution, but the same interface could later be implemented with MongoDB.

The main reason for separating these parts is testability. The tests can replace the random mock LLM with deterministic fake responses without changing the main service logic.

Only fully validated classifications are stored. This keeps invalid or malformed model output from reaching downstream systems.

## Quick start

First setup:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Start API:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn travelio_classifier.app:app --reload
```

Open `http://127.0.0.1:8000/docs`. Stop API with `Ctrl+C`.

## Test with Postman

Health check:

- Method: `GET`
- URL: `http://127.0.0.1:8000/health`
- Expected body: `{"status":"ok"}`

Classification:

- Method: `POST`
- URL: `http://127.0.0.1:8000/classify-message`
- Header: `Content-Type: application/json`
- Body type: raw JSON

```json
{
  "message": "AC di kamar bocor parah, tolong kirim teknisi secepatnya dong",
  "conversation_context": []
}
```

`conversation_context` is optional. When present, it accepts at most 10 items:

```json
{
  "message": "Can I extend until next Monday?",
  "conversation_context": [
    {
      "role": "guest",
      "content": "I am scheduled to check out tomorrow"
    }
  ]
}
```

Example HTTP 200 response:

```json
{
  "request_id": "9fc8e0c0-0f45-4c34-9ce7-d738747aae32",
  "classification": {
    "intent": "maintenance_request",
    "entities": {
      "dates": [],
      "location": null,
      "unit_type": null
    },
    "urgency": "high",
    "confidence": 0.91,
    "needs_human": false
  },
  "latency_ms": 142,
  "attempts": 1,
  "processed_at": "2026-09-15T10:00:00Z"
}
```

The provided client deliberately returns random classifications, malformed
JSON about 8% of the time, and timeouts about 4% of the time. The service
retries up to three total attempts. Therefore, the sample text does not
guarantee the sample intent; this assessment validates pipeline behavior, not
mock-model quality.

## Error contract

| HTTP | Code | Meaning |
|---|---|---|
| 422 | FastAPI validation detail | Request is blank, too large, or contains unknown fields. |
| 502 | `invalid_llm_output` | All three model outputs were malformed or violated the schema. |
| 503 | `llm_timeout` | All three model attempts timed out. |
| 503 | `persistence_unavailable` | A valid result could not be stored. |

Expected service-error shape:

```json
{
  "error": {
    "code": "llm_timeout",
    "message": "The classification service timed out after 3 attempts.",
    "request_id": "9fc8e0c0-0f45-4c34-9ce7-d738747aae32"
  }
}
```

Unknown is not treated as a server error. It means the request was processed successfully, but the classifier could not confidently route it. The API therefore returns HTTP 200 and forces needs_human=true.

```json
{
  "intent": "unknown",
  "needs_human": true
}
```

The actual response also includes the complete entity, urgency, and confidence
fields required by the schema.

## Key decisions

- Validate every LLM response: I do not trust the model output directly. Every response must pass the Pydantic schema before it can be returned or stored.
- Keep the intent list closed: The model can only return the supported intents. unknown is a valid fallback and always sets needs_human=true. Any value outside the enum is treated as invalid model output and retried.
- Use limited retries: The mock LLM can time out or return malformed JSON, so the service allows up to three total attempts. This improves reliability without letting retries grow indefinitely and increase latency too much.
- Return explicit errors: If all attempts fail, or persistence fails, the API returns a clear typed error instead of silently falling back to a fake success response.
- Keep logs minimal: Logs only contain operational metadata such as request ID, attempt count, latency, and error category. Guest text, conversation context, prompts, and raw model output are not logged because they may contain private data.
- Keep dependencies replaceable: The LLM client and repository are behind small interfaces. This makes the service easier to test and allows the local in-memory repository to be replaced by MongoDB later.
- Keep local setup simple: No external database or API key is required. The goal is to make the assessment runnable immediately while still keeping the code structure close to what a production service would need.

## Assumptions

- Relative dates: Dates such as “tomorrow” or “next Monday” are resolved using the request processing date in UTC and available conversation context. If a date cannot be resolved safely, it is omitted instead of guessed.
- Confidence threshold: I use 0.65 as an initial threshold for human review. This is only a starting assumption and should later be calibrated using labeled production data.
- Three total attempts: I chose three attempts as a balance between reliability and endpoint latency. In production, this should be adjusted using real timeout rates and service-level targets.
- Persist only valid results: A classification is stored only after it passes full schema validation. Invalid model output should not enter storage because downstream systems may assume stored records are already valid.
- In-memory storage is temporary: The in-memory repository is used only to keep the take-home easy to run locally. A production version would use the same repository interface with MongoDB.
- Currency handling: GMV should not be combined across currencies unless amounts have first been converted into a common reporting currency using appropriate FX rates.
- Dagster is design-level only: The Dagster section is written as pseudocode

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m mypy
```

Tests cover valid classification and persistence, malformed output followed by
success, exhausted timeouts, invalid intent, unknown fallback, low-confidence
escalation, repository failure, request validation, health, HTTP status mapping,
and log redaction.

## What I would add for production

- Replace the in-memory repository with MongoDB and add proper indexes, retention rules, encryption, and access control.
- Add authentication, authorization, rate limiting, and stricter request-size limits at the API boundary.
- Replace the mock LLM with a real provider that supports native structured output, while still validating the response with Pydantic.
- Add metrics and tracing for request volume, latency, retries, timeouts, invalid model output, and persistence failures.
- Store prompt version, model version, and schema version with each classification so regressions are easier to investigate.
- Add a human-feedback loop so incorrect classifications and manual overrides can become labeled evaluation data.
- Run automated regression tests before changing prompts or models, followed by a small canary rollout before full release.
