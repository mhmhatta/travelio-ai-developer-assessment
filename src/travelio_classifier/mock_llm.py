import asyncio
import json
import random


class MockLLMClient:
    """Simulate malformed JSON, timeouts, and valid model responses."""

    async def complete(self, prompt: str, *, timeout: float = 5.0) -> str:
        """Return one randomized response using the assessment behavior."""
        await asyncio.sleep(random.uniform(0.05, 0.3))
        roll = random.random()
        if roll < 0.08:
            return '{"intent": "booking_inquiry", "confidence": 0.9'
        if roll < 0.12:
            raise TimeoutError("LLM timed out")
        return json.dumps(
            {
                "intent": random.choice(
                    [
                        "booking_inquiry",
                        "maintenance_request",
                        "extension_request",
                        "out_of_scope",
                        "unknown",
                    ]
                ),
                "entities": {"dates": [], "location": None, "unit_type": None},
                "urgency": random.choice(["low", "medium", "high"]),
                "confidence": round(random.uniform(0.4, 0.99), 2),
                "needs_human": False,
            }
        )
