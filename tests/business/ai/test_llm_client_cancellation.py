from __future__ import annotations

import threading

import pytest

from src.business.agents.run_context import CancelReason, CancelToken
from src.business.ai.llm_client import LangChainLLMClient


class _ClosingTransport:
    def __init__(self) -> None:
        self.closed = threading.Event()
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        self.closed.set()


class _BlockingProvider:
    def __init__(self) -> None:
        self.root_client = _ClosingTransport()
        self.entered = threading.Event()

    def bind_tools(self, _tools, **_kwargs):
        return self

    def invoke(self, _messages, **_kwargs):
        self.entered.set()
        if not self.root_client.closed.wait(timeout=3):
            raise AssertionError("provider transport was not closed by cancellation")
        raise RuntimeError("transport closed")


class _ImmediateProvider:
    def __init__(self) -> None:
        self.root_client = _ClosingTransport()
        self.invocations = 0

    def bind_tools(self, _tools, **_kwargs):
        return self

    def invoke(self, _messages, **_kwargs):
        self.invocations += 1
        return object()


def _client_with_provider(provider: _BlockingProvider) -> LangChainLLMClient:
    client = object.__new__(LangChainLLMClient)
    client.provider = "openai"
    client.audit_source = None
    client.llm = provider
    client._create_llm = lambda: provider
    client._convert_to_langchain_messages = lambda messages: messages
    return client


def test_cancel_closes_provider_transport_and_unblocks_sync_invoke():
    provider = _BlockingProvider()
    client = _client_with_provider(provider)
    token = CancelToken()
    failure = []

    def invoke() -> None:
        try:
            client.chat_with_tools([], [], cancel_token=token)
        except Exception as exc:
            failure.append(exc)

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    assert provider.entered.wait(timeout=2)

    token.cancel(CancelReason.USER_CANCEL)

    thread.join(timeout=2)
    assert not thread.is_alive()
    assert provider.root_client.close_count == 1
    assert failure and "transport closed" in str(failure[0])


def test_concurrent_requests_cancel_only_their_own_transport():
    first = _BlockingProvider()
    second = _BlockingProvider()
    providers = iter((first, second))
    client = object.__new__(LangChainLLMClient)
    client.provider = "openai"
    client.audit_source = None
    client.llm = object()
    client._create_llm = lambda: next(providers)
    client._convert_to_langchain_messages = lambda messages: messages
    first_token = CancelToken()
    second_token = CancelToken()

    first_thread = threading.Thread(
        target=lambda: pytest.raises(
            RuntimeError,
            client.chat_with_tools,
            [],
            [],
            cancel_token=first_token,
        ),
        daemon=True,
    )
    first_thread.start()
    assert first.entered.wait(timeout=2)
    second_thread = threading.Thread(
        target=lambda: pytest.raises(
            RuntimeError,
            client.chat_with_tools,
            [],
            [],
            cancel_token=second_token,
        ),
        daemon=True,
    )
    second_thread.start()
    assert second.entered.wait(timeout=2)

    first_token.cancel(CancelReason.USER_CANCEL)

    first_thread.join(timeout=2)
    assert not first_thread.is_alive()
    assert first.root_client.closed.is_set()
    assert first.root_client.close_count == 1
    assert second.root_client.closed.wait(timeout=0.1) is False
    assert second_thread.is_alive()

    second_token.cancel(CancelReason.USER_CANCEL)
    second_thread.join(timeout=2)
    assert not second_thread.is_alive()
    assert second.root_client.close_count == 1


def test_request_without_cancel_token_reuses_and_does_not_close_shared_provider():
    provider = _ImmediateProvider()
    client = object.__new__(LangChainLLMClient)
    client.provider = "openai"
    client.audit_source = None
    client.llm = provider
    client._create_llm = lambda: pytest.fail("non-cancellable request rebuilt provider")
    client._convert_to_langchain_messages = lambda messages: messages
    client._extract_response = lambda _message: "ok"

    assert client.chat_with_tools([], []) == "ok"
    assert provider.invocations == 1
    assert provider.root_client.close_count == 0
