from __future__ import annotations

import json

import pytest

from src.business.debug.observation import observe_multimodal
from src.business.debug.redaction import SecretRedactor
from src.business.debug.trace_buffer import TraceBuffer


def test_multimodal_trace_keeps_text_and_media_metadata_without_raw_image_bytes() -> None:
    redactor = SecretRedactor()
    redactor.register_secret("vision-secret")
    buffer = TraceBuffer()
    epoch = buffer.new_epoch()
    data_url = "data:image/png;base64,RAW_IMAGE_BYTES_SHOULD_NOT_APPEAR"

    result = observe_multimodal(
        buffer=buffer,
        redactor=redactor,
        epoch=epoch,
        content=[
            {"type": "text", "text": "inspect this with vision-secret"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
        invoke_fn=lambda _content: "vision-secret response",
    )

    assert result == "vision-secret response"
    [record] = buffer.get_records()
    assert record.method == "multimodal"
    assert record.output_content == "***REDACTED*** response"
    assert "vision-secret" not in (record.input_messages or "")
    assert "RAW_IMAGE_BYTES_SHOULD_NOT_APPEAR" not in (record.input_media or "")
    assert "data:image" not in (record.input_media or "")

    media = json.loads(record.input_media or "[]")
    assert media == [{"type": "image_url", "media_type": "image", "byte_count": len(data_url)}]
    assert record.detail_availability == "full_text"


def test_failed_multimodal_trace_keeps_safe_text_and_metadata_only() -> None:
    redactor = SecretRedactor()
    redactor.register_secret("vision-secret")
    buffer = TraceBuffer()
    epoch = buffer.new_epoch()
    data_url = "data:image/png;base64,RAW_IMAGE_BYTES_SHOULD_NOT_APPEAR"

    with pytest.raises(RuntimeError, match="vision failed"):
        observe_multimodal(
            buffer=buffer,
            redactor=redactor,
            epoch=epoch,
            content=[
                {"type": "text", "text": "inspect vision-secret"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
            invoke_fn=lambda _content: (_ for _ in ()).throw(RuntimeError("vision failed")),
        )

    [record] = buffer.get_records()
    assert record.outcome == "failed"
    assert "***REDACTED***" in (record.input_messages or "")
    assert "RAW_IMAGE_BYTES_SHOULD_NOT_APPEAR" not in (record.input_media or "")
    assert json.loads(record.input_media or "[]")[0]["byte_count"] == len(data_url)
