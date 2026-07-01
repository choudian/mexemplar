"""Safety governor for self-improvement: rate limits, convergence, and rollback detection."""

import logging
from typing import Optional

from src.data.repos.self_improvement_repository import SelfImprovementRepository
from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)


class SafetyGovernor:
    """Enforces safety constraints on self-improvement actions.

    Three safety mechanisms:
    - Rate limiting: caps daily/session action counts per action type.
    - Convergence detection: stops optimization when improvement deltas plateau.
    - Regressive change detection: triggers rollback when metrics degrade beyond
      a configured threshold.
    """

    # Action type constants for rate limiting
    PROMPT_SUPPLEMENT_CREATED = "prompt_supplement_created"
    TOOL_AUTO_CREATED = "tool_auto_created"
    REFLECTION_GENERATED = "reflection_generated"

    def __init__(self, repo: Optional[SelfImprovementRepository] = None):
        self._repo = repo or SelfImprovementRepository()
        self._config = get_unified_config()
        self._convergence_history: list[float] = []  # rolling effectiveness deltas

    def check_rate_limit(self, action_type: str) -> bool:
        """Return True if the action is within rate limits, False if exceeded.

        Rate limits are read from ``get_unified_config()`` per action type.
        Unknown action types are unrestricted.

        Args:
            action_type: The action category to check.

        Returns:
            True if the action is allowed, False if the daily/session cap is reached.
        """
        config_map = {
            self.PROMPT_SUPPLEMENT_CREATED: self._config.get_self_improvement_max_prompt_supplements_per_day,
            self.TOOL_AUTO_CREATED: self._config.get_self_improvement_max_tool_creations_per_day,
            self.REFLECTION_GENERATED: self._config.get_self_improvement_max_reflections_per_session,
        }
        getter = config_map.get(action_type)
        if getter is None:
            return True  # unknown action types are unrestricted

        try:
            max_allowed = int(getter())
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Invalid rate limit config for %s, defaulting to unrestricted: %s",
                action_type,
                exc,
            )
            return True

        current_count = self._repo.count_actions_today(action_type)
        if current_count >= max_allowed:
            logger.warning(
                "Rate limit reached for %s: %d/%d",
                action_type,
                current_count,
                max_allowed,
            )
            return False
        return True

    def record_effectiveness_delta(self, delta: float) -> bool:
        """Record an effectiveness improvement delta for convergence tracking.

        Appends the delta to an in-memory rolling history. When the last 3 deltas
        all have absolute values below the convergence threshold, the system is
        considered converged and further optimization should stop.

        Args:
            delta: The change in effectiveness (positive = improvement,
                negative = regression).

        Returns:
            True if still improving (not converged), False if converged.
        """
        self._convergence_history.append(delta)
        if len(self._convergence_history) < 3:
            return True  # need at least 3 measurements

        last_three = self._convergence_history[-3:]
        try:
            threshold = float(self._config.get_self_improvement_convergence_threshold())
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Invalid convergence threshold config, using default 0.01: %s",
                exc,
            )
            threshold = 0.01

        if all(abs(d) < threshold for d in last_three):
            logger.info(
                "Convergence detected: last 3 deltas all below %.4f",
                threshold,
            )
            return False  # converged
        return True

    def check_regressive_change(
        self,
        before_metric: Optional[float],
        after_metric: Optional[float],
    ) -> bool:
        """Return True if the change is regressive (should rollback).

        A change is regressive if the after_metric is worse than the before_metric
        by more than the configured degradation threshold (proportion of the
        before value). For example, with a 10% threshold, a drop from 0.8 to 0.7
        (12.5% degradation) triggers rollback.

        Args:
            before_metric: Metric value before the change. None means no baseline
                and the check is skipped.
            after_metric: Metric value after the change. None means no measurement
                and the check is skipped.

        Returns:
            True if the change is regressive and should be rolled back.
        """
        if before_metric is None or after_metric is None:
            return False

        try:
            degradation_threshold = float(self._config.get_self_improvement_degradation_threshold())
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Invalid degradation threshold config, using default 0.10: %s",
                exc,
            )
            degradation_threshold = 0.10

        if (
            before_metric > 0
            and (after_metric - before_metric) / before_metric < -degradation_threshold
        ):
            logger.warning(
                "Regressive change detected: %.3f -> %.3f (threshold %.1f%%)",
                before_metric,
                after_metric,
                degradation_threshold * 100,
            )
            return True
        return False

    def reset_convergence(self) -> None:
        """Reset convergence tracking (e.g. after a significant metric shift).

        Clears the in-memory rolling delta history so that convergence detection
        starts fresh.
        """
        self._convergence_history.clear()
        logger.info("Convergence tracking reset")

    def get_convergence_status(self) -> dict:
        """Return the current convergence tracking state for diagnostics.

        Returns:
            Dict with keys: deltas (list of recent deltas), is_converged (bool),
            threshold (float).
        """
        try:
            threshold = float(self._config.get_self_improvement_convergence_threshold())
        except (TypeError, ValueError):
            threshold = 0.01

        is_converged = len(self._convergence_history) >= 3 and all(
            abs(d) < threshold for d in self._convergence_history[-3:]
        )
        return {
            "deltas": list(self._convergence_history),
            "is_converged": is_converged,
            "threshold": threshold,
        }

    def should_allow_action(self, action_type: str) -> tuple[bool, str]:
        """Combined safety check: rate limit + convergence.

        Convenience method that checks both rate limits and convergence status
        before allowing a self-improvement action.

        Args:
            action_type: The action category to check.

        Returns:
            Tuple of (allowed: bool, reason: str). reason is empty when allowed.
        """
        if not self.check_rate_limit(action_type):
            return False, f"Rate limit exceeded for {action_type}"

        try:
            threshold = float(self._config.get_self_improvement_convergence_threshold())
        except (TypeError, ValueError):
            threshold = 0.01

        if len(self._convergence_history) >= 3 and all(
            abs(d) < threshold for d in self._convergence_history[-3:]
        ):
            return False, "Convergence detected: optimization plateaued"

        return True, ""
