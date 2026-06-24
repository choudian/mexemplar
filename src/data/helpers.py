"""Shared helpers for the data layer (repositories)."""

from __future__ import annotations


def build_like_pattern(term: str, *, contains: bool = True) -> str:
    """Build an escaped SQL LIKE pattern.

    Escapes the LIKE metacharacters (backslash, ``%``, ``_``) for use with a
    query that specifies ``escape='\\'``. Backslash is escaped first so a
    literal backslash in the term cannot accidentally escape a following ``%``
    or ``_``.

    Args:
        term: Search term; surrounding whitespace is stripped.
        contains: When True (default) wrap as ``%term%``; when False wrap as
            ``term%`` (prefix match).

    Raises:
        ValueError: If the term is empty after stripping.
    """
    cleaned = str(term or "").strip()
    if not cleaned:
        raise ValueError("term must not be empty")
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%" if contains else f"{escaped}%"
