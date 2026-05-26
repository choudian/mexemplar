"""Reference expansion through the debug facade.

Provides on-demand expansion of trace detail references (e.g. large message
payloads or tool-call arguments) with response-size bounding and redaction.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from src.business.debug.redaction import SecretRedactor


class DebugReferenceService:
    """Expand opaque trace references into redacted, size-bounded content.

    Parameters
    ----------
    redactor:
        The secret redactor to apply to expanded content.
    max_response_bytes:
        Maximum UTF-8 byte length of the expanded content before truncation.
    """

    def __init__(
        self,
        redactor: SecretRedactor,
        max_response_bytes: int = 1_048_576,
    ) -> None:
        self._redactor = redactor
        self._max_bytes = max_response_bytes

    def expand(
        self,
        reference_id: str,
        loader_fn: Callable[[str], Optional[str]],
    ) -> dict[str, Any]:
        """Expand a reference using the provided loader function.

        Parameters
        ----------
        reference_id:
            The opaque reference identifier to expand.
        loader_fn:
            Callable that receives *reference_id* and returns the raw content
            string, or ``None`` if the reference cannot be resolved.

        Returns
        -------
        dict
            A dictionary with keys ``referenceId``, ``content``, ``available``,
            ``truncated``, and ``nextChunk``.
        """
        try:
            content = loader_fn(reference_id)
        except (LookupError, ValueError):
            content = None

        if content is None:
            return {
                "referenceId": reference_id,
                "content": None,
                "available": False,
                "truncated": False,
                "nextChunk": None,
            }

        redacted = self._redactor.redact(content)

        encoded = redacted.encode("utf-8")
        if len(encoded) > self._max_bytes:
            # Truncate to byte boundary, then decode safely
            truncated_bytes = encoded[: self._max_bytes]
            # Decode without raising on partial multi-byte sequences
            truncated_content = truncated_bytes.decode("utf-8", errors="ignore")
            return {
                "referenceId": reference_id,
                "content": truncated_content,
                "available": True,
                "truncated": True,
                "nextChunk": None,  # chunking not implemented in v1
            }

        return {
            "referenceId": reference_id,
            "content": redacted,
            "available": True,
            "truncated": False,
            "nextChunk": None,
        }
