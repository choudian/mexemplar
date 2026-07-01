"""Prompt effectiveness tracking and optimization service for self-improvement.

Implements a DSPy GEPA-inspired pattern: collect lightweight effectiveness
metrics per session, analyze weak dimensions, and generate targeted prompt
supplements via LLM. Candidates are evaluated against active supplements
and auto-promoted or retracted based on metric evidence.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from src.business.self_improvement.audit_service import SelfImprovementAuditService
from src.business.self_improvement.safety_governor import SafetyGovernor
from src.data.repos.self_improvement_repository import SelfImprovementRepository

logger = logging.getLogger(__name__)


class PromptEffectivenessTracker:
    """Collects and aggregates prompt effectiveness metrics at session end."""

    def __init__(
        self, si_repo: SelfImprovementRepository, audit_service: SelfImprovementAuditService
    ):
        self._si_repo = si_repo
        self._audit = audit_service

    def record_session_metrics(
        self,
        session_id: str,
        prompt_hash: str,
        task_completion_rate: float,
        avg_iteration_count: float,
        first_tool_accuracy: float,
        user_implicit_feedback: float = 0.5,
    ) -> str:
        """Record effectiveness metrics for a completed session.

        Computes a composite effectiveness score and stores it.
        Returns the metric_id.
        """
        # Composite score: weighted average
        composite = (
            0.35 * task_completion_rate
            + 0.25
            * (1.0 - min(avg_iteration_count / 20.0, 1.0))  # normalize: lower iterations = better
            + 0.25 * first_tool_accuracy
            + 0.15 * user_implicit_feedback  # 1.0 = no rephrasing, 0.0 = user rephrased
        )
        entry = self._si_repo.record_metric(
            metric_type="prompt_effectiveness",
            metric_key=prompt_hash,
            metric_value=composite,
            sample_size=1,
            metadata={
                "session_id": session_id,
                "task_completion_rate": task_completion_rate,
                "avg_iteration_count": avg_iteration_count,
                "first_tool_accuracy": first_tool_accuracy,
                "user_implicit_feedback": user_implicit_feedback,
            },
        )
        return entry.metric_id

    def get_effectiveness_for_prompt(
        self, prompt_hash: str, since_days: int = 7
    ) -> Optional[float]:
        """Get average effectiveness score for a prompt version over the last N days."""
        metrics = self._si_repo.get_metrics(
            metric_type="prompt_effectiveness",
            metric_key=prompt_hash,
            limit=100,
        )
        if not metrics:
            return None
        # Filter to recent metrics
        cutoff = datetime.utcnow() - timedelta(days=since_days)
        recent = [m for m in metrics if m.measured_at >= cutoff]
        if not recent:
            return None
        return sum(m.metric_value for m in recent) / len(recent)

    def compute_prompt_hash(self, prompt_text: str) -> str:
        """Compute a deterministic hash of the assembled prompt text."""
        return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]


class PromptOptimizationService:
    """Generates prompt supplements from effectiveness metrics (DSPy GEPA pattern)."""

    # Known prompt sections that can be optimized
    TARGETABLE_SECTIONS = [
        "delegation_rules",
        "complexity_classification",
        "tool_selection",
        "task_routing",
        "user_interaction",
    ]

    def __init__(
        self,
        si_repo: SelfImprovementRepository,
        tracker: PromptEffectivenessTracker,
        audit_service: SelfImprovementAuditService,
        safety_governor: SafetyGovernor,
    ):
        self._si_repo = si_repo
        self._tracker = tracker
        self._audit = audit_service
        self._safety = safety_governor

    def run_optimization_cycle(self, llm_client=None) -> Optional[str]:
        """Run one optimization cycle: analyze metrics -> generate supplement -> store as candidate.

        Returns the supplement_id if a new supplement was created, None otherwise.
        """
        # 1. Check rate limit
        if not self._safety.check_rate_limit(SafetyGovernor.PROMPT_SUPPLEMENT_CREATED):
            logger.debug("Prompt optimization rate limit reached")
            return None

        # 2. Get recent metrics to identify weak areas
        metrics = self._si_repo.get_metrics(
            metric_type="prompt_effectiveness",
            limit=50,
        )
        if len(metrics) < 5:
            logger.debug("Not enough metrics for optimization (need >= 5)")
            return None

        # 3. Identify the weakest dimension
        analysis = self._analyze_metrics(metrics)
        if analysis is None:
            return None

        # 4. Check convergence
        if not self._safety.record_effectiveness_delta(analysis["improvement_potential"]):
            logger.info("Convergence detected, skipping optimization")
            return None

        # 5. Generate supplement via LLM
        if llm_client is None:
            return None

        supplement = self._generate_supplement(llm_client, analysis)
        if supplement is None:
            return None

        # 6. Store as candidate
        created = self._si_repo.create_supplement(
            target_section=supplement["target_section"],
            content=supplement["content"],
            rationale=supplement["rationale"],
            metric_evidence=supplement.get("metric_evidence"),
            prompt_hash=None,  # candidate, not yet tied to a specific prompt hash
        )

        # 7. Audit
        self._audit.log_action(
            action_type="prompt_supplement_created",
            target_type="prompt_supplement",
            target_id=created.supplement_id,
            rationale=supplement["rationale"],
            metric_evidence=analysis,
        )

        return created.supplement_id

    def evaluate_candidates(self) -> list[str]:
        """Evaluate candidate supplements against active ones.

        Compares effectiveness metrics for sessions using candidates vs
        sessions using current active supplements. Promotes candidates
        that show better metrics.

        Returns list of promoted supplement IDs.
        """
        promoted = []
        candidates = self._si_repo.get_candidate_supplements()

        for candidate in candidates:
            # Check if we have enough data to evaluate
            candidate_hash = getattr(candidate, "prompt_hash", None)
            if candidate_hash is None:
                continue

            candidate_score = self._tracker.get_effectiveness_for_prompt(candidate_hash)
            if candidate_score is None:
                continue

            # Get the current active supplement for the same section
            active = self._si_repo.get_active_supplements()
            active_for_section = [s for s in active if s.target_section == candidate.target_section]

            if active_for_section:
                active_hash = getattr(active_for_section[0], "prompt_hash", None)
                if active_hash:
                    active_score = self._tracker.get_effectiveness_for_prompt(active_hash)
                    if active_score is not None:
                        # Check for regressive change
                        if self._safety.check_regressive_change(active_score, candidate_score):
                            # Retract the candidate
                            self._si_repo.retract_supplement(
                                candidate.supplement_id,
                                reason="auto_retracted: regressive change detected",
                            )
                            self._audit.log_action(
                                action_type="prompt_supplement_retracted",
                                target_type="prompt_supplement",
                                target_id=candidate.supplement_id,
                                rationale="Candidate shows worse metrics than active",
                            )
                            continue

            # Promote the candidate（CAS 失败返回 None 时不报成功，026 I7 follow-up）
            if self._si_repo.promote_supplement(candidate.supplement_id) is None:
                continue
            promoted.append(candidate.supplement_id)

            self._audit.log_action(
                action_type="prompt_supplement_promoted",
                target_type="prompt_supplement",
                target_id=candidate.supplement_id,
                rationale="Candidate shows equal or better metrics",
            )

        return promoted

    def check_rollback(self) -> list[str]:
        """Check recently promoted supplements for regressive changes.

        If a supplement was promoted but subsequent sessions show worse
        metrics than the pre-promotion baseline, automatically rollback.

        Returns list of retracted supplement IDs.
        """
        retracted = []
        # Get recently promoted supplements (last 10 sessions worth)
        active = self._si_repo.get_active_supplements()

        for supplement in active:
            supplement_hash = getattr(supplement, "prompt_hash", None)
            if supplement_hash is None:
                continue

            current_score = self._tracker.get_effectiveness_for_prompt(
                supplement_hash, since_days=1
            )
            if current_score is None:
                continue

            # Compare against the metric evidence stored when the supplement was created
            evidence = getattr(supplement, "metric_evidence", None)
            if evidence is None:
                continue

            if isinstance(evidence, str):
                try:
                    evidence = json.loads(evidence)
                except (json.JSONDecodeError, TypeError):
                    continue

            baseline_score = evidence.get("baseline_score") if isinstance(evidence, dict) else None
            if baseline_score is None:
                continue

            if self._safety.check_regressive_change(baseline_score, current_score):
                self._si_repo.retract_supplement(
                    supplement.supplement_id,
                    reason="auto_rollback: regressive change detected after promotion",
                )
                retracted.append(supplement.supplement_id)

                self._audit.log_action(
                    action_type="prompt_supplement_retracted",
                    target_type="prompt_supplement",
                    target_id=supplement.supplement_id,
                    rationale="auto_rollback:regressive_change",
                    metric_evidence={"baseline": baseline_score, "current": current_score},
                )

        return retracted

    # --- Private methods ---

    def _analyze_metrics(self, metrics: list) -> Optional[dict]:
        """Analyze recent metrics to identify the weakest prompt dimension."""
        if not metrics:
            return None

        # Aggregate by dimension
        completion_rates = []
        iteration_counts = []
        tool_accuracies = []
        feedback_scores = []

        for m in metrics:
            meta = getattr(m, "metadata_", None) or getattr(m, "metadata", None)
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(meta, dict):
                continue
            completion_rates.append(meta.get("task_completion_rate", 0.5))
            iteration_counts.append(meta.get("avg_iteration_count", 10))
            tool_accuracies.append(meta.get("first_tool_accuracy", 0.5))
            feedback_scores.append(meta.get("user_implicit_feedback", 0.5))

        if not completion_rates:
            return None

        avg_completion = sum(completion_rates) / len(completion_rates)
        avg_iteration = sum(iteration_counts) / len(iteration_counts)
        avg_tool_accuracy = sum(tool_accuracies) / len(tool_accuracies)
        avg_feedback = sum(feedback_scores) / len(feedback_scores)

        # Identify weakest dimension
        dimensions = {
            "task_routing": avg_completion,
            "complexity_classification": 1.0 - min(avg_iteration / 20.0, 1.0),
            "tool_selection": avg_tool_accuracy,
            "user_interaction": avg_feedback,
        }

        weakest_section = min(dimensions, key=dimensions.get)
        weakest_score = dimensions[weakest_section]
        overall = sum(dimensions.values()) / len(dimensions)

        return {
            "weakest_section": weakest_section,
            "weakest_score": weakest_score,
            "overall_score": overall,
            "improvement_potential": max(0, 1.0 - weakest_score),
            "dimensions": dimensions,
        }

    def _generate_supplement(self, llm_client, analysis: dict) -> Optional[dict]:
        """Use LLM to generate a prompt supplement targeting the weakest section."""
        section = analysis["weakest_section"]
        score = analysis["weakest_score"]
        dimensions = analysis["dimensions"]

        prompt = (
            f"You are optimizing an AI assistant's system prompt. The current prompt "
            f"has weak performance in the '{section}' dimension (score: {score:.2f}/1.0).\n"
            "\n"
            "All dimension scores:\n"
            + "\n".join(f"- {k}: {v:.2f}" for k, v in dimensions.items())
            + "\n\n"
            f"Generate a concise prompt supplement that improves the '{section}' dimension. "
            f"The supplement will be inserted into the prompt's '{section}' section.\n"
            "\n"
            "Requirements:\n"
            "- Be specific and actionable\n"
            "- Focus on the weakest aspect identified\n"
            "- Keep it under 200 words\n"
            "- Do not contradict existing prompt instructions\n"
            "\n"
            "Return a JSON object with:\n"
            f'- "target_section": "{section}"\n'
            '- "content": the supplement text to insert\n'
            '- "rationale": why this supplement should improve the score\n'
        )

        try:
            response = llm_client.call(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.3,
            )
            if not response or not response.strip():
                return None

            # Parse JSON from response
            json_str = response.strip()
            if json_str.startswith("```"):
                # Strip markdown code fences
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1])

            result = json.loads(json_str)
            if not isinstance(result, dict) or "content" not in result:
                return None

            result.setdefault("target_section", section)
            result["metric_evidence"] = {
                "weakest_score": score,
                "dimensions": dimensions,
            }
            return result

        except Exception as e:
            logger.warning("LLM supplement generation failed: %s", e)
            return None
