from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.business.debug.context import TraceContext
from src.business.debug.observation import observe_chat, observe_chat_with_tools
from src.business.debug.redaction import SecretRedactor
from src.business.debug.trace_buffer import TraceBuffer


class FailingBuffer(TraceBuffer):
    def add_record(self, record):  # type: ignore[no-untyped-def]
        raise RuntimeError("buffer unavailable")


class FailingRedactor(SecretRedactor):
    def redact(self, text: str) -> str:
        raise RuntimeError("redaction unavailable")


def test_provider_success_is_returned_even_when_buffer_write_fails() -> None:
    buffer = FailingBuffer()
    epoch = buffer.new_epoch()

    result = observe_chat(
        buffer=buffer,
        redactor=SecretRedactor(),
        epoch=epoch,
        prompt="hello",
        invoke_fn=lambda prompt: f"provider:{prompt}",
    )

    assert result == "provider:hello"


def test_redaction_failure_records_diagnostic_unavailable_without_changing_success() -> None:
    buffer = TraceBuffer()
    epoch = buffer.new_epoch()

    result = observe_chat(
        buffer=buffer,
        redactor=FailingRedactor(),
        epoch=epoch,
        prompt="do not retain",
        invoke_fn=lambda prompt: f"provider:{prompt}",
    )

    assert result == "provider:do not retain"
    [record] = buffer.get_records()
    assert record.detail_availability == "diagnostic_unavailable"
    assert record.input_messages is None
    assert record.output_content is None


def test_provider_failure_semantics_are_preserved_when_diagnostics_fail() -> None:
    buffer = FailingBuffer()
    epoch = buffer.new_epoch()

    def provider(_prompt: str) -> str:
        raise ValueError("provider original failure")

    with pytest.raises(ValueError, match="provider original failure"):
        observe_chat(
            buffer=buffer,
            redactor=FailingRedactor(),
            epoch=epoch,
            prompt="hello",
            invoke_fn=provider,
        )


def test_provider_failure_trace_retains_redacted_request_detail() -> None:
    redactor = SecretRedactor()
    redactor.register_secret("request-secret")
    buffer = TraceBuffer()
    epoch = buffer.new_epoch()

    def provider(_prompt: str) -> str:
        raise ValueError("provider failed for request-secret")

    with pytest.raises(ValueError, match="provider failed"):
        observe_chat(
            buffer=buffer,
            redactor=redactor,
            epoch=epoch,
            prompt="inspect request-secret",
            invoke_fn=provider,
        )

    [record] = buffer.get_records()
    assert record.outcome == "failed"
    assert record.input_messages == "inspect ***REDACTED***"
    assert record.error_summary == "provider failed for ***REDACTED***"


def test_tool_provider_failure_trace_retains_redacted_messages_and_tools() -> None:
    redactor = SecretRedactor()
    redactor.register_secret("tool-secret")
    buffer = TraceBuffer()
    epoch = buffer.new_epoch()

    def provider(_messages, _tools):  # type: ignore[no-untyped-def]
        raise RuntimeError("tool provider failed")

    with pytest.raises(RuntimeError, match="tool provider failed"):
        observe_chat_with_tools(
            buffer=buffer,
            redactor=redactor,
            epoch=epoch,
            messages=[{"role": "user", "content": "tool-secret input"}],
            tools=[{"name": "lookup", "description": "tool-secret"}],
            invoke_fn=provider,
        )

    [record] = buffer.get_records()
    assert "tool-secret" not in (record.input_messages or "")
    assert "***REDACTED***" in (record.input_messages or "")
    assert "tool-secret" not in (record.input_tools or "")


def test_disabled_observation_calls_provider_without_recording() -> None:
    called: list[str] = []

    result = observe_chat(
        buffer=None,
        redactor=None,
        epoch=None,
        prompt="hello",
        invoke_fn=lambda prompt: called.append(prompt) or "ok",
    )

    assert result == "ok"
    assert called == ["hello"]


def test_context_metadata_is_attached_to_successful_tool_trace() -> None:
    class Response:
        content = "done"
        tool_calls = []

    buffer = TraceBuffer()
    epoch = buffer.new_epoch()

    with TraceContext(
        source="agent_loop",
        agent_type="assistant",
        session_id="s1",
        workflow_id="w1",
        iteration=2,
        transition_id="tr_1",
    ):
        response = observe_chat_with_tools(
            buffer=buffer,
            redactor=SecretRedactor(),
            epoch=epoch,
            messages=[{"role": "user", "content": "do it"}],
            tools=[{"type": "function", "function": {"name": "delegate"}}],
            invoke_fn=lambda _messages, _tools: Response(),
        )

    assert response.content == "done"
    [record] = buffer.get_records()
    assert record.source == "agent_loop"
    assert record.agent_type == "assistant"
    assert record.session_id == "s1"
    assert record.workflow_id == "w1"
    assert record.iteration == 2
    assert record.linked_transition_ids == ["tr_1"]


def test_metadata_capture_failure_does_not_block_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = TraceBuffer()
    epoch = buffer.new_epoch()
    monkeypatch.setattr(
        "src.business.debug.observation.get_current_context",
        lambda: (_ for _ in ()).throw(RuntimeError("context unavailable")),
    )

    result = observe_chat(
        buffer=buffer,
        redactor=SecretRedactor(),
        epoch=epoch,
        prompt="hello",
        invoke_fn=lambda prompt: f"provider:{prompt}",
    )

    assert result == "provider:hello"
    assert buffer.get_records() == []


def test_llm_wrapper_calls_provider_when_capture_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.business.ai.llm_client import LangChainLLMClient

    client = object.__new__(LangChainLLMClient)
    client.llm = SimpleNamespace(
        invoke=lambda messages, **_kwargs: SimpleNamespace(content=f"ok:{messages[0].content}")
    )
    monkeypatch.setattr(
        "src.business.debug.service.get_active_capture",
        lambda: (_ for _ in ()).throw(RuntimeError("debug service unavailable")),
    )

    assert client.chat("hello") == "ok:hello"
