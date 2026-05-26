from __future__ import annotations

import pytest

from src.data.credential_resolver import (
    CredentialMutationAudit,
    CredentialMutationError,
    ReadOnlyCredentialResolver,
)


class FakeKeyring:
    def __init__(self, values: dict[tuple[str, str], str | None]) -> None:
        self.values = values
        self.get_calls: list[tuple[str, str]] = []
        self.set_calls: list[tuple] = []
        self.delete_calls: list[tuple] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.get_calls.append((service, username))
        return self.values.get((service, username))

    def set_password(self, *args):
        self.set_calls.append(args)

    def delete_password(self, *args):
        self.delete_calls.append(args)


def test_read_only_resolver_reads_existing_keyring_without_mutation() -> None:
    keyring = FakeKeyring(
        {
            ("MexemplarTest", "anthropic_api_key"): "sk-main",
            ("MexemplarTest", "anthropic_vision_api_key"): "sk-vision",
            ("MexemplarTest", "openai_api_key"): "sk-embedding",
        }
    )
    audit = CredentialMutationAudit()
    resolver = ReadOnlyCredentialResolver(
        service_name="MexemplarTest",
        keyring_module=keyring,
        audit=audit,
    )

    assert resolver.get_ai_api_key() == "sk-main"
    assert resolver.get_ai_vision_api_key() == "sk-vision"
    assert resolver.get_embedding_api_key() == "sk-embedding"
    assert resolver.get_compression_model_api_key() == "sk-main"
    assert keyring.set_calls == []
    assert keyring.delete_calls == []
    audit.assert_clean()


def test_vision_key_falls_back_to_main_key_without_plaintext_config_migration() -> None:
    keyring = FakeKeyring({("MexemplarTest", "anthropic_api_key"): "sk-main"})
    resolver = ReadOnlyCredentialResolver(
        service_name="MexemplarTest",
        keyring_module=keyring,
    )

    assert resolver.get_ai_vision_api_key() == "sk-main"
    assert ("MexemplarTest", "anthropic_vision_api_key") in keyring.get_calls
    assert keyring.set_calls == []
    assert keyring.delete_calls == []


def test_missing_key_returns_none_instead_of_config_plaintext_fallback() -> None:
    keyring = FakeKeyring({})
    resolver = ReadOnlyCredentialResolver(
        service_name="MexemplarTest",
        keyring_module=keyring,
    )

    assert resolver.get_ai_api_key() is None
    assert resolver.get_embedding_api_key() is None
    assert keyring.set_calls == []
    assert keyring.delete_calls == []


def test_mutation_guard_rejects_and_counts_set_delete_attempts() -> None:
    audit = CredentialMutationAudit()
    resolver = ReadOnlyCredentialResolver(
        service_name="MexemplarTest",
        keyring_module=FakeKeyring({}),
        audit=audit,
    )

    with pytest.raises(CredentialMutationError):
        resolver.set_password("MexemplarTest", "anthropic_api_key", "sk-new")
    with pytest.raises(CredentialMutationError):
        resolver.delete_password("MexemplarTest", "anthropic_api_key")

    assert audit.mutation_count == 2
    with pytest.raises(CredentialMutationError, match="credential_mutation_attempted"):
        audit.assert_clean()


def test_fingerprint_is_non_reversible_and_stable() -> None:
    resolver = ReadOnlyCredentialResolver(
        service_name="MexemplarTest",
        keyring_module=FakeKeyring({("MexemplarTest", "anthropic_api_key"): "sk-main"}),
    )

    first = resolver.fingerprint()
    second = resolver.fingerprint()

    assert first.present is True
    assert first.digest == second.digest
    assert first.digest != "sk-main"
