from __future__ import annotations

from src.business.debug.redaction import SecretRedactor


def test_secret_redactor_masks_registered_application_secrets() -> None:
    redactor = SecretRedactor()
    redactor.register_secret("sk-primary-secret")
    redactor.register_secret("runtime-token-123")

    safe = redactor.redact("key=sk-primary-secret token=runtime-token-123")

    assert safe == "key=***REDACTED*** token=***REDACTED***"


def test_secret_redactor_keeps_old_and_new_rotated_snapshots_masked() -> None:
    redactor = SecretRedactor()
    redactor.register_secret("old-secret")
    redactor.register_secret("new-secret")

    safe = redactor.redact("old-secret -> new-secret")

    assert safe == "***REDACTED*** -> ***REDACTED***"


def test_secret_redactor_recurses_without_mutating_json_payload() -> None:
    redactor = SecretRedactor()
    redactor.register_secret("secret-value")
    payload = {"messages": [{"content": "secret-value"}]}

    safe = redactor.redact_json(payload)

    assert safe == {"messages": [{"content": "***REDACTED***"}]}
    assert payload == {"messages": [{"content": "secret-value"}]}
