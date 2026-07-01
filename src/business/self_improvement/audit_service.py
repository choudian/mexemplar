"""Self-improvement audit and metric recording service."""

import json
import logging
from typing import Optional

from src.data.repos.self_improvement_repository import SelfImprovementRepository

logger = logging.getLogger(__name__)


class SelfImprovementAuditService:
    """High-level service for recording and querying self-improvement actions and metrics."""

    def __init__(self, repo: Optional[SelfImprovementRepository] = None):
        self._repo = repo or SelfImprovementRepository()

    def log_action(
        self,
        action_type: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        before_snapshot: Optional[dict] = None,
        after_snapshot: Optional[dict] = None,
        rationale: Optional[str] = None,
        metric_evidence: Optional[dict] = None,
        triggered_by: str = "auto",
    ) -> str:
        """Record a self-improvement action in the audit log.

        Args:
            action_type: Category of the action (e.g. prompt_supplement_created,
                tool_auto_created, reflection_generated).
            target_type: Type of the target entity (e.g. prompt, tool, specialist).
            target_id: Identifier of the target entity.
            before_snapshot: State before the action (serialized to JSON).
            after_snapshot: State after the action (serialized to JSON).
            rationale: Human-readable reason for the action.
            metric_evidence: Metric data supporting the action (serialized to JSON).
            triggered_by: Origin of the action (auto / user / system).

        Returns:
            The action_id of the recorded action.
        """
        before_json = json.dumps(before_snapshot, ensure_ascii=False) if before_snapshot else None
        after_json = json.dumps(after_snapshot, ensure_ascii=False) if after_snapshot else None
        evidence_json = json.dumps(metric_evidence, ensure_ascii=False) if metric_evidence else None

        action_id = self._repo.log_action(
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            before_snapshot=before_json,
            after_snapshot=after_json,
            rationale=rationale,
            metric_evidence=evidence_json,
            triggered_by=triggered_by,
        )
        logger.info(
            "Self-improvement action logged: %s (target=%s/%s, triggered_by=%s)",
            action_type,
            target_type,
            target_id,
            triggered_by,
        )
        return action_id

    def count_actions_today(self, action_type: str) -> int:
        """Count how many actions of a given type were logged today.

        Args:
            action_type: The action category to count.

        Returns:
            Number of actions of the given type recorded today.
        """
        return self._repo.count_actions_today(action_type)

    def get_recent_actions(
        self,
        action_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Query recent self-improvement actions.

        Args:
            action_type: Optional filter by action category.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            Tuple of (action_dicts, total_count).
        """
        rows, total = self._repo.get_recent_actions(
            action_type=action_type,
            limit=limit,
            offset=offset,
        )
        return [self._action_to_dict(row) for row in rows], total

    def get_action(self, action_id: str) -> Optional[dict]:
        """Retrieve a single action by ID.

        Args:
            action_id: The action identifier.

        Returns:
            Action dict or None if not found.
        """
        row = self._repo.get_action(action_id)
        if row is None:
            return None
        return self._action_to_dict(row)

    def record_metric(
        self,
        metric_type: str,
        metric_key: Optional[str] = None,
        metric_value: float = 0.0,
        sample_size: int = 1,
        metadata: Optional[dict] = None,
    ) -> str:
        """Record a performance metric measurement.

        Args:
            metric_type: Category of the metric (e.g. task_success_rate,
                tool_usage_efficiency, prompt_effectiveness).
            metric_key: Optional sub-key for disambiguation within a type.
            metric_value: The measured value.
            sample_size: Number of observations contributing to this value.
            metadata: Additional context (serialized to JSON).

        Returns:
            The metric_id of the recorded metric.
        """
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

        metric_id = self._repo.record_metric(
            metric_type=metric_type,
            metric_key=metric_key,
            metric_value=metric_value,
            sample_size=sample_size,
            metadata=metadata_json,
        )
        logger.info(
            "Self-improvement metric recorded: %s/%s = %.4f (n=%d)",
            metric_type,
            metric_key,
            metric_value,
            sample_size,
        )
        return metric_id

    def get_latest_metric(
        self,
        metric_type: str,
        metric_key: Optional[str] = None,
    ) -> Optional[dict]:
        """Retrieve the most recent measurement for a metric.

        Args:
            metric_type: Category of the metric.
            metric_key: Optional sub-key.

        Returns:
            Metric dict or None if no measurement exists.
        """
        row = self._repo.get_latest_metric(
            metric_type=metric_type,
            metric_key=metric_key,
        )
        if row is None:
            return None
        return self._metric_to_dict(row)

    def get_metric_history(
        self,
        metric_type: str,
        metric_key: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Query historical metric measurements.

        Args:
            metric_type: Category of the metric.
            metric_key: Optional sub-key.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            Tuple of (metric_dicts, total_count).
        """
        rows, total = self._repo.get_metric_history(
            metric_type=metric_type,
            metric_key=metric_key,
            limit=limit,
            offset=offset,
        )
        return [self._metric_to_dict(row) for row in rows], total

    def get_effectiveness_trend(
        self,
        metric_type: str,
        metric_key: Optional[str] = None,
        window: int = 10,
    ) -> list[float]:
        """Compute a rolling effectiveness trend from recent metric values.

        Args:
            metric_type: Category of the metric.
            metric_key: Optional sub-key.
            window: Number of recent measurements to include.

        Returns:
            List of metric values in chronological order (oldest first).
        """
        rows, _ = self._repo.get_metric_history(
            metric_type=metric_type,
            metric_key=metric_key,
            limit=window,
            offset=0,
        )
        values = [float(getattr(row, "metric_value", 0.0)) for row in reversed(rows)]
        return values

    @staticmethod
    def _action_to_dict(row) -> dict:
        """Convert an action ORM row to a response dict."""
        before_raw = getattr(row, "before_snapshot", None)
        after_raw = getattr(row, "after_snapshot", None)
        evidence_raw = getattr(row, "metric_evidence", None)

        before = None
        after = None
        evidence = None
        try:
            if before_raw:
                before = json.loads(before_raw)
        except (json.JSONDecodeError, TypeError):
            before = before_raw
        try:
            if after_raw:
                after = json.loads(after_raw)
        except (json.JSONDecodeError, TypeError):
            after = after_raw
        try:
            if evidence_raw:
                evidence = json.loads(evidence_raw)
        except (json.JSONDecodeError, TypeError):
            evidence = evidence_raw

        return {
            "action_id": getattr(row, "action_id", ""),
            "action_type": getattr(row, "action_type", ""),
            "target_type": getattr(row, "target_type", None),
            "target_id": getattr(row, "target_id", None),
            "before_snapshot": before,
            "after_snapshot": after,
            "rationale": getattr(row, "rationale", None),
            "metric_evidence": evidence,
            "triggered_by": getattr(row, "triggered_by", "auto"),
            "created_at": getattr(row, "created_at", None),
        }

    @staticmethod
    def _metric_to_dict(row) -> dict:
        """Convert a metric ORM row to a response dict."""
        metadata_raw = getattr(row, "metadata", None)
        metadata = None
        try:
            if metadata_raw:
                metadata = json.loads(metadata_raw)
        except (json.JSONDecodeError, TypeError):
            metadata = metadata_raw

        return {
            "metric_id": getattr(row, "metric_id", ""),
            "metric_type": getattr(row, "metric_type", ""),
            "metric_key": getattr(row, "metric_key", None),
            "metric_value": float(getattr(row, "metric_value", 0.0)),
            "sample_size": int(getattr(row, "sample_size", 1)),
            "metadata": metadata,
            "created_at": getattr(row, "created_at", None),
        }
