from __future__ import annotations

from src.business.agents.config import ResultType
from src.business.services.assistant_failure_classifier import classify_assistant_failure


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_classifier_maps_failure_categories_without_exposing_raw_details() -> None:
    fixtures = [
        (ProviderError("key=sk-secret endpoint=https://provider.test", 401), "authentication"),
        (ProviderError("raw request body", 422), "invalid_request"),
        (ProviderError("billing secret", 429), "quota"),
        (TimeoutError("socket payload secret"), "network"),
        (ProviderError("upstream response secret", 503), "provider"),
    ]

    for exception, expected in fixtures:
        classified = classify_assistant_failure(exception=exception)
        public_text = " ".join(
            [
                classified.category,
                classified.message,
                classified.suggestion,
                classified.internal_code,
                classified.exception_type or "",
            ]
        )
        assert classified.category == expected
        assert "secret" not in public_text
        assert "provider.test" not in public_text
        assert "sk-" not in public_text


def test_classifier_handles_iteration_limit_and_internal_fallback() -> None:
    iteration = classify_assistant_failure(
        result_type=ResultType.MAX_ITERATIONS_REACHED,
        error="raw loop detail",
    )
    internal = classify_assistant_failure(error="unknown raw body")

    assert iteration.category == "iteration_limit"
    assert internal.category == "internal"
    assert "raw" not in iteration.message + iteration.suggestion
    assert "unknown raw body" not in internal.message + internal.suggestion
