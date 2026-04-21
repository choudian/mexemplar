from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Optional, Protocol
import logging

from src.data.config_models import RecordingNoiseFilterConfig
from src.data.unified_config import get_unified_config
from src.utils.timezone import coerce_timestamp

from .decision import FilterDecision
from .llm_judge import LLMNoiseJudge
from .pipeline import NoiseFilterPipeline
from .primary_host import derive_primary_site


@dataclass
class IngestBatch:
    recording_id: Optional[str]
    actions: list[dict[str, Any]]
    network_requests: list[dict[str, Any]]


@dataclass
class FilteredRequestResult:
    request: dict[str, Any]
    decision: FilterDecision | None
    batch_index: int
    action_list_index: int | None

    @property
    def filtered(self) -> bool:
        return self.decision is not None and self.decision.decision == "filter"

    @property
    def filter_reason(self) -> dict[str, Any] | None:
        if not self.filtered or self.decision is None:
            return None
        return self.decision.to_summary()

    @property
    def filtered_at(self):
        if not self.filtered or self.decision is None:
            return None
        return self.decision.timestamp


def flatten_recording_requests(
    action_network_requests: Mapping[int, list[dict[str, Any]]],
    standalone_network_requests: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []

    for action_list_index in sorted(action_network_requests):
        for request in action_network_requests[action_list_index]:
            row = dict(request)
            row["_action_list_index"] = action_list_index
            flattened.append(row)

    for request in standalone_network_requests:
        flattened.append(dict(request))

    return flattened


def run_filter_hook(
    batch: IngestBatch,
    config: RecordingNoiseFilterConfig,
) -> list[FilteredRequestResult]:
    if not config.enabled:
        return [
            FilteredRequestResult(
                request=dict(request),
                decision=None,
                batch_index=batch_index,
                action_list_index=_extract_action_list_index(request),
            )
            for batch_index, request in enumerate(batch.network_requests)
        ]

    pipeline = NoiseFilterPipeline(config)
    llm_judge = LLMNoiseJudge()
    primary_site = derive_primary_site(batch.actions)
    first_party_sites = list(config.first_party_whitelist)

    results: list[FilteredRequestResult] = []
    for batch_index, request in enumerate(batch.network_requests):
        request_copy = dict(request)
        decision = pipeline.evaluate(
            request_copy,
            primary_site=primary_site,
            first_party_sites=first_party_sites,
        )
        if decision is None:
            decision = llm_judge.judge(request_copy)

        results.append(
            FilteredRequestResult(
                request=request_copy,
                decision=decision,
                batch_index=batch_index,
                action_list_index=_extract_action_list_index(request_copy),
            )
        )

    return results


def build_request_rows(
    results: Iterable[FilteredRequestResult],
    action_id_by_list_index: Mapping[int, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for result in results:
        row = dict(result.request)
        row.pop("_action_list_index", None)
        row["action_id"] = (
            action_id_by_list_index.get(result.action_list_index)
            if result.action_list_index is not None
            else None
        )
        row["filtered"] = result.filtered
        row["filter_reason"] = result.filter_reason
        row["filtered_at"] = result.filtered_at
        rows.append(row)

    return rows


def build_filter_decisions(
    results: Iterable[FilteredRequestResult],
    request_id_by_batch_index: Mapping[int, int],
    *,
    recording_id: Optional[str],
    actions: list[dict[str, Any]],
    action_id_by_list_index: Mapping[int, int],
) -> list[FilterDecision]:
    decisions: list[FilterDecision] = []

    for result in results:
        if result.decision is None:
            continue

        request_id = request_id_by_batch_index.get(result.batch_index)
        if request_id is None:
            continue

        action_id = (
            action_id_by_list_index.get(result.action_list_index)
            if result.action_list_index is not None
            else None
        )
        action_timestamp = None
        if result.action_list_index is not None and result.action_list_index < len(actions):
            action_timestamp = coerce_timestamp(actions[result.action_list_index].get("timestamp"))

        decisions.append(
            replace(
                result.decision,
                request_id=str(request_id),
                action_id=action_id,
                recording_id=recording_id,
                request_timestamp=coerce_timestamp(result.request.get("timestamp")),
                action_timestamp=action_timestamp,
            )
        )

    return decisions


def _extract_action_list_index(request: Mapping[str, Any]) -> int | None:
    value = request.get("_action_list_index")
    if isinstance(value, int):
        return value
    return None


class _Repository(Protocol):
    def save_network_requests(
        self, network_requests: list[dict[str, Any]], recording_id: str | None = None
    ) -> dict[int, int]: ...
    def save_filter_decisions(self, decisions: list[FilterDecision]) -> list[int]: ...


_log = logging.getLogger(__name__)


def persist_filtered_network_requests(
    repository: _Repository,
    recording_id: str,
    actions: list[dict[str, Any]],
    action_ids: list[int],
    action_network_requests: Mapping[int, list[dict[str, Any]]],
    standalone_network_requests: Iterable[dict[str, Any]],
    *,
    log_prefix: str = "已保存",
) -> None:
    """执行过滤并持久化网络请求和过滤决策。"""
    flattened = flatten_recording_requests(action_network_requests, standalone_network_requests)
    if not flattened:
        return

    config = get_unified_config().get_recording_noise_filter_config()
    filtered_results = run_filter_hook(
        IngestBatch(recording_id=recording_id, actions=actions, network_requests=flattened),
        config,
    )

    action_id_by_index = {i: aid for i, aid in enumerate(action_ids)}
    request_rows = build_request_rows(filtered_results, action_id_by_index)
    request_id_map = repository.save_network_requests(request_rows, recording_id)
    _log.info("%s %d 条网络请求", log_prefix, len(request_id_map))

    decisions = build_filter_decisions(
        filtered_results,
        request_id_map,
        recording_id=recording_id,
        actions=actions,
        action_id_by_list_index=action_id_by_index,
    )
    if decisions:
        repository.save_filter_decisions(decisions)
        _log.info("%s %d 条过滤决策", log_prefix, len(decisions))
