import ipaddress
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

import tldextract

_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)


def _coerce_host(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None

    if "://" in candidate:
        parsed = urlparse(candidate)
        return (parsed.hostname or "").lower().rstrip(".") or None

    return candidate.lower().rstrip(".") or None


def normalize_host_to_site(host: str | None) -> str | None:
    normalized_host = _coerce_host(host)
    if not normalized_host:
        return None

    try:
        ipaddress.ip_address(normalized_host)
        return None
    except ValueError:
        pass

    extracted = _TLD_EXTRACT(normalized_host)
    if not extracted.domain or not extracted.suffix:
        return None
    return f"{extracted.domain}.{extracted.suffix}".lower()


def normalize_url_to_site(url: str | None) -> str | None:
    return normalize_host_to_site(url)


def derive_primary_host(actions: Sequence[Mapping[str, Any]]) -> str | None:
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        url = action.get("url")
        if not isinstance(url, str):
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        host = parsed.hostname
        if host:
            return host.lower().rstrip(".")
    return None


def derive_primary_site(actions: Sequence[Mapping[str, Any]]) -> str | None:
    return normalize_host_to_site(derive_primary_host(actions))
