from typing import Any, Iterable, Mapping

from src.data.config_models import RecordingNoiseFilterConfig

from .decision import FilterDecision
from .rules import (
    is_options_preflight,
    is_redirect_3xx,
    is_static_asset,
    is_third_party,
    matches_blacklist,
)


class NoiseFilterPipeline:
    def __init__(self, config: RecordingNoiseFilterConfig) -> None:
        self._config = config

    def evaluate(
        self,
        request: Mapping[str, Any],
        *,
        primary_site: str | None,
        first_party_sites: Iterable[str] = (),
    ) -> FilterDecision | None:
        if is_options_preflight(request):
            return FilterDecision(decision="filter", source="rule", reason="options_preflight")

        if is_redirect_3xx(request):
            return FilterDecision(decision="filter", source="rule", reason="redirect_3xx")

        static_match = is_static_asset(
            request,
            static_extensions=self._config.static_extensions,
            static_content_type_prefixes=self._config.static_content_type_prefixes,
        )
        if static_match:
            return FilterDecision(
                decision="filter",
                source="rule",
                reason="static_asset",
                pattern_matched=static_match,
            )

        blacklist_match = matches_blacklist(
            request,
            blacklist_domains=self._config.blacklist_domains,
        )
        if blacklist_match:
            return FilterDecision(
                decision="filter",
                source="rule",
                reason="ad_tracking_blacklist",
                pattern_matched=blacklist_match,
            )

        if is_third_party(
            request,
            primary_site=primary_site,
            first_party_sites=first_party_sites,
        ):
            return FilterDecision(
                decision="filter",
                source="rule",
                reason="third_party_cross_origin",
            )

        return None
