"""Read-only credential resolver for manual Real Grand Tour runs.

The ordinary ``UnifiedConfigManager`` getters may migrate plaintext leftovers
into keyring.  Real Grand Tour must avoid those side effects, so this module
reads only existing keyring entries and exposes small audit hooks that fail
closed on any attempted mutation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from src.data.real_tour_audit import (
    is_real_tour_runtime as _is_real_tour_runtime,
    record_credential_mutation,
)
from src.data.unified_config import _get_keyring_service_name


class KeyringReader(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...


class CredentialMutationError(RuntimeError):
    """Raised when a real-tour path attempts to mutate keyring credentials."""


@dataclass
class CredentialMutationAudit:
    """Counts forbidden keyring mutation attempts."""

    mutation_count: int = 0

    def record_mutation(self) -> None:
        self.mutation_count += 1

    def assert_clean(self) -> None:
        if self.mutation_count:
            raise CredentialMutationError("credential_mutation_attempted")


@dataclass(frozen=True)
class CredentialFingerprint:
    """Non-reversible presence/fingerprint snapshot for mutation audits."""

    present: bool
    digest: str | None = None


class ReadOnlyCredentialResolver:
    """Side-effect-free keyring-only credential resolver."""

    MAIN_USERNAME = "anthropic_api_key"
    VISION_USERNAME = "anthropic_vision_api_key"
    EMBEDDING_USERNAME = "openai_api_key"

    def __init__(
        self,
        *,
        service_name: str | None = None,
        keyring_module: KeyringReader | None = None,
        audit: CredentialMutationAudit | None = None,
    ) -> None:
        self._service_name = service_name or _get_keyring_service_name()
        self._keyring = keyring_module or self._load_keyring()
        self._audit = audit or CredentialMutationAudit()

    @property
    def audit(self) -> CredentialMutationAudit:
        return self._audit

    def get_ai_api_key(self) -> str | None:
        return self._read_keyring(self.MAIN_USERNAME)

    def get_ai_vision_api_key(self) -> str | None:
        return self._read_keyring(self.VISION_USERNAME) or self.get_ai_api_key()

    def get_embedding_api_key(self) -> str | None:
        return self._read_keyring(self.EMBEDDING_USERNAME)

    def get_compression_model_api_key(self) -> str | None:
        return self.get_ai_api_key()

    def fingerprint(self, key_name: str = "ai.api_key") -> CredentialFingerprint:
        secret = self.get_secret(key_name)
        if not secret:
            return CredentialFingerprint(present=False)
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return CredentialFingerprint(present=True, digest=digest)

    def get_secret(self, key_name: str) -> str | None:
        if key_name == "ai.api_key":
            return self.get_ai_api_key()
        if key_name == "ai.vision_api_key":
            return self.get_ai_vision_api_key()
        if key_name == "ai.embedding_api_key":
            return self.get_embedding_api_key()
        if key_name == "ai.compression_model_api_key":
            return self.get_compression_model_api_key()
        return None

    def set_password(self, *_args: Any, **_kwargs: Any) -> None:
        self._audit.record_mutation()
        record_credential_mutation("set_password")
        raise CredentialMutationError("credential_mutation_forbidden")

    def delete_password(self, *_args: Any, **_kwargs: Any) -> None:
        self._audit.record_mutation()
        record_credential_mutation("delete_password")
        raise CredentialMutationError("credential_mutation_forbidden")

    def _read_keyring(self, username: str) -> str | None:
        try:
            value = self._keyring.get_password(self._service_name, username)
        except Exception:
            return None
        if value and value.strip():
            return value
        return None

    @staticmethod
    def _load_keyring() -> KeyringReader:
        import keyring

        return keyring


def is_real_tour_runtime() -> bool:
    return _is_real_tour_runtime()


def get_real_tour_credential_resolver() -> ReadOnlyCredentialResolver:
    return ReadOnlyCredentialResolver()


__all__ = [
    "CredentialFingerprint",
    "CredentialMutationAudit",
    "CredentialMutationError",
    "ReadOnlyCredentialResolver",
    "get_real_tour_credential_resolver",
    "is_real_tour_runtime",
]
