from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .primary_host import coerce_host, normalize_host_to_site


def _request_host(request: Mapping[str, Any]) -> str | None:
    url = request.get("url")
    if not isinstance(url, str):
        return None
    return coerce_host(url)


def _response_content_type(request: Mapping[str, Any]) -> str | None:
    headers = request.get("response_headers")
    if not isinstance(headers, Mapping):
        return None

    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "content-type" and isinstance(value, str):
            return value.strip()
    return None


def is_options_preflight(request: Mapping[str, Any]) -> bool:
    method = request.get("method")
    return isinstance(method, str) and method.upper() == "OPTIONS"


def is_redirect_3xx(request: Mapping[str, Any]) -> bool:
    status = request.get("response_status")
    try:
        status_code = int(status)
    except (TypeError, ValueError):
        return False
    return 300 <= status_code < 400


def is_static_asset(
    request: Mapping[str, Any],
    *,
    static_extensions: Iterable[str],
    static_content_type_prefixes: Iterable[str],
) -> str | None:
    url = request.get("url")
    if isinstance(url, str):
        path = urlparse(url).path or ""
        suffix = PurePosixPath(path).suffix.lower()
        if suffix and suffix in {ext.lower() for ext in static_extensions}:
            return suffix

    content_type = _response_content_type(request)
    if not content_type:
        return None

    normalized = content_type.split(";", 1)[0].strip().lower()
    for prefix in static_content_type_prefixes:
        lowered = prefix.lower()
        if normalized == lowered or normalized.startswith(lowered):
            return normalized
    return None


def matches_blacklist(
    request: Mapping[str, Any], *, blacklist_domains: Iterable[str]
) -> str | None:
    host = _request_host(request)
    if not host:
        return None

    for pattern in blacklist_domains:
        lowered = pattern.lower().strip()
        if lowered and lowered in host:
            return pattern
    return None


def is_third_party(
    request: Mapping[str, Any],
    *,
    primary_site: str | None,
    first_party_sites: Iterable[str] = (),
) -> bool:
    if not primary_site:
        return False

    request_site = normalize_host_to_site(_request_host(request))
    if not request_site:
        return False

    allowed_sites = {primary_site.lower()}
    allowed_sites.update(
        site.lower()
        for site in (normalize_host_to_site(item) for item in first_party_sites)
        if site
    )
    return request_site not in allowed_sites
