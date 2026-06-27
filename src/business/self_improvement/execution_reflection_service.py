"""Execution reflection and avoidance rule service for agent self-improvement.

Implements the Reflexion pattern: after each task execution, the agent generates
a verbal self-reflection that is stored in the brain and consulted in future
attempts. Failure reflections produce avoidance rules that are proactively
injected into the assistant prompt.
"""

import json
import logging
from typing import Any, Optional

from src.business.brain.models import EntryType, Zone
from src.business.self_improvement.audit_service import SelfImprovementAuditService
from src.business.self_improvement.safety_governor import SafetyGovernor
from src.data.repos.self_improvement_repository import SelfImprovementRepository
from src.data.unified_config import get_unified_config
from src.utils.ids import new_id

logger = logging.getLogger(__name__)


class ExecutionReflectionService:
    """Generates post-task reflections and manages avoidance rule injection."""

    def __init__(
        self,
        si_repo: SelfImprovementRepository,
        audit_service: SelfImprovementAuditService,
        safety_governor: SafetyGovernor,
        brain_repo=None,  # BrainRepository, optional to avoid circular imports
    ):
        self._si_repo = si_repo
        self._audit = audit_service
        self._safety = safety_governor
        self._brain_repo = brain_repo

    def generate_post_task_reflection(
        self,
        session_id: str,
        task_description: str,
        approach_taken: str,
        outcome: str,  # "success" | "failure" | "partial"
        tool_calls_summary: list[dict],
        error_message: Optional[str] = None,
        llm_client=None,
    ) -> Optional[str]:
        """Generate a structured reflection after task completion.

        For success: reflection goes to reflection zone with reusable lessons.
        For failure: deeper reflection goes to failure zone with avoidance rule.

        Returns the entry_id of the created brain entry, or None on failure.
        """
        # 1. Check rate limit
        if not self._safety.check_rate_limit(SafetyGovernor.REFLECTION_GENERATED):
            logger.debug("Reflection rate limit reached, skipping")
            return None

        # 2. Build reflection prompt based on outcome
        if outcome == "failure":
            prompt = self._build_failure_reflection_prompt(
                task_description, approach_taken, tool_calls_summary, error_message
            )
            target_zone = Zone.FAILURE
        else:
            prompt = self._build_success_reflection_prompt(
                task_description, approach_taken, tool_calls_summary
            )
            target_zone = Zone.REFLECTION

        # 3. Call LLM to generate reflection (if client available)
        if llm_client is None:
            logger.debug("No LLM client available for reflection generation")
            return None

        try:
            reflection_text = self._call_llm_for_reflection(llm_client, prompt)
        except Exception as e:
            logger.warning("LLM reflection generation failed: %s", e)
            return None

        if not reflection_text:
            return None

        # 4. Store in brain
        entry_id = self._store_reflection(
            session_id=session_id,
            zone=target_zone,
            content=reflection_text,
            task_description=task_description,
            outcome=outcome,
        )

        # 5. For failures, also generate an avoidance rule
        if outcome == "failure" and entry_id:
            self._generate_avoidance_rule(
                session_id=session_id,
                task_description=task_description,
                reflection_text=reflection_text,
                llm_client=llm_client,
            )

        # 6. Audit
        self._audit.log_action(
            action_type="reflection_generated",
            target_type="brain_memory_entry",
            target_id=entry_id,
            rationale=f"Post-task reflection for {outcome} outcome",
            metric_evidence={"outcome": outcome, "zone": str(target_zone)},
        )

        return entry_id

    def get_avoidance_rules_for_context(
        self,
        current_context: str,
        top_n: Optional[int] = None,
    ) -> list[dict]:
        """Load top-N most relevant avoidance rules from failure zone.

        Filters by context relevance (keyword matching against pattern field)
        and returns rules sorted by relevance_score * effectiveness.
        """
        if top_n is None:
            top_n = get_unified_config().get_self_improvement_avoidance_top_n()

        if self._brain_repo is None:
            return []

        try:
            # Query failure zone entries with entry_type='avoidance_rule'
            entries = self._brain_repo.get_entries_by_zone(
                zone=str(Zone.FAILURE),
                status="active",
                limit=top_n * 3,  # over-fetch for context filtering
            )
        except Exception as e:
            logger.warning("Failed to load avoidance rules: %s", e)
            return []

        # Filter by context relevance
        context_lower = current_context.lower()
        scored_rules = []
        for entry in entries:
            if getattr(entry, "entry_type", None) != EntryType.AVOIDANCE_RULE:
                continue
            try:
                rule_data = json.loads(entry.content)
            except (json.JSONDecodeError, TypeError):
                continue

            pattern = rule_data.get("pattern", "").lower()
            # Simple keyword overlap scoring
            context_words = set(context_lower.split())
            pattern_words = set(pattern.split())
            overlap = len(context_words & pattern_words)
            if overlap > 0 or not pattern:  # include rules with no pattern (universal)
                score = entry.relevance_score * (1 + overlap)
                scored_rules.append({
                    "entry_id": entry.entry_id,
                    "pattern": rule_data.get("pattern", ""),
                    "avoidance": rule_data.get("avoidance", ""),
                    "evidence_count": rule_data.get("evidence_count", 0),
                    "score": score,
                    "content": entry.content,
                })

        # Sort by score descending, take top-N
        scored_rules.sort(key=lambda r: r["score"], reverse=True)
        return scored_rules[:top_n]

    def record_avoidance_rule_effectiveness(
        self,
        entry_ids: list[str],
        task_succeeded: bool,
    ) -> None:
        """Track whether injected avoidance rules helped or hurt.

        If task succeeded with rules injected -> increment referenced_count.
        If task failed despite rules -> question rule effectiveness.
        """
        if self._brain_repo is None:
            return
        try:
            if task_succeeded:
                self._brain_repo.batch_update_referenced_counts(entry_ids)
            else:
                # Mark for potential invalidation review
                for entry_id in entry_ids:
                    self._audit.log_action(
                        action_type="avoidance_rule_miss",
                        target_type="brain_memory_entry",
                        target_id=entry_id,
                        rationale="Task failed despite avoidance rule being injected",
                    )
        except Exception as e:
            logger.warning("Failed to record avoidance rule effectiveness: %s", e)

    # --- Private methods ---

    def _build_failure_reflection_prompt(
        self,
        task_description: str,
        approach_taken: str,
        tool_calls_summary: list[dict],
        error_message: Optional[str],
    ) -> str:
        return (
            "Analyze this failed task execution and generate a structured reflection.\n"
            "\n"
            "## Task\n"
            f"{task_description}\n"
            "\n"
            "## Approach Taken\n"
            f"{approach_taken}\n"
            "\n"
            "## Tool Call Trace\n"
            f"{json.dumps(tool_calls_summary, ensure_ascii=False, indent=2)[:2000]}\n"
            "\n"
            "## Error\n"
            f"{error_message or 'Unknown error'}\n"
            "\n"
            "## Required Output Format\n"
            "Generate a reflection with:\n"
            "1. **Root Cause**: What went wrong and why\n"
            "2. **Avoidance Rule**: A specific, actionable rule to prevent this failure "
            '(format: "When doing X, do not do Y because Z")\n'
            "3. **Key Lesson**: One sentence summary of the lesson learned\n"
            "\n"
            "Keep the reflection concise and actionable. The avoidance rule will be stored "
            "and automatically injected into future sessions to prevent repeat failures."
        )

    def _build_success_reflection_prompt(
        self,
        task_description: str,
        approach_taken: str,
        tool_calls_summary: list[dict],
    ) -> str:
        return (
            "Analyze this successful task execution and extract reusable lessons.\n"
            "\n"
            "## Task\n"
            f"{task_description}\n"
            "\n"
            "## Approach Taken\n"
            f"{approach_taken}\n"
            "\n"
            "## Tool Call Summary\n"
            f"{json.dumps(tool_calls_summary, ensure_ascii=False, indent=2)[:1000]}\n"
            "\n"
            "## Required Output Format\n"
            "Generate a reflection with:\n"
            "1. **What Worked**: Which aspects of the approach were effective\n"
            "2. **Reusable Lesson**: A generalizable insight that could help in similar future tasks\n"
            "3. **Key Lesson**: One sentence summary\n"
            "\n"
            "Keep the reflection concise. Focus on lessons that would help the agent "
            "make better decisions in the future."
        )

    def _call_llm_for_reflection(self, llm_client, prompt: str) -> Optional[str]:
        """Call LLM to generate reflection text."""
        try:
            response = llm_client.call(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.3,
            )
            if response and response.strip():
                return response.strip()
        except Exception as e:
            logger.warning("LLM reflection call failed: %s", e)
        return None

    def _store_reflection(
        self,
        session_id: str,
        zone: Zone,
        content: str,
        task_description: str,
        outcome: str,
    ) -> Optional[str]:
        """Store reflection in brain memory entries."""
        if self._brain_repo is None:
            return None
        try:
            entry_id = new_id()
            entry_type = (
                str(EntryType.AVOIDANCE_RULE)
                if zone == Zone.FAILURE
                else str(EntryType.INSIGHT)
            )
            self._brain_repo.create_entry(
                zone=str(zone),
                content=content,
                status="active",
                origin="self_improvement_reflection",
                reason=f"Auto-reflection for {outcome} task: {task_description[:100]}",
                entry_type=entry_type,
                source_session_id=session_id,
                entry_id=entry_id,
            )
            return entry_id
        except Exception as e:
            logger.error("Failed to store reflection in brain: %s", e)
            return None

    def _generate_avoidance_rule(
        self,
        session_id: str,
        task_description: str,
        reflection_text: str,
        llm_client=None,
    ) -> None:
        """Generate a structured avoidance rule from a failure reflection.

        The avoidance rule is stored as a brain_memory_entry in the failure zone
        with entry_type='avoidance_rule' and structured JSON content.
        """
        if self._brain_repo is None or llm_client is None:
            return

        prompt = (
            "From this failure reflection, extract a specific avoidance rule.\n"
            "\n"
            "## Failure Reflection\n"
            f"{reflection_text}\n"
            "\n"
            "## Required Output\n"
            'Return a JSON object with:\n'
            '- "pattern": A brief description of the situation/pattern that leads to failure\n'
            '- "avoidance": A specific action to take instead\n'
            '- "evidence_count": 1\n'
            "\n"
            'Example: {"pattern": "using tool X for task type Y", '
            '"avoidance": "use tool Z instead because it handles edge case W", '
            '"evidence_count": 1}\n'
            "\n"
            "Return ONLY the JSON object, no other text."
        )

        try:
            response = self._call_llm_for_reflection(llm_client, prompt)
            if not response:
                return

            # Parse JSON from response
            json_str = response.strip()
            if json_str.startswith("```"):
                # Strip markdown code fences
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1])

            rule_data = json.loads(json_str)
            if (
                not isinstance(rule_data, dict)
                or "pattern" not in rule_data
                or "avoidance" not in rule_data
            ):
                logger.warning("Invalid avoidance rule format from LLM")
                return

            # Store as avoidance rule entry
            entry_id = new_id()
            self._brain_repo.create_entry(
                zone=str(Zone.FAILURE),
                content=json.dumps(rule_data, ensure_ascii=False),
                status="active",
                origin="self_improvement_avoidance",
                reason=f"Auto-generated avoidance rule from failure: {task_description[:80]}",
                entry_type=str(EntryType.AVOIDANCE_RULE),
                source_session_id=session_id,
                entry_id=entry_id,
                relevance_score=0.7,  # start with moderate confidence
            )

            self._audit.log_action(
                action_type="avoidance_rule_created",
                target_type="brain_memory_entry",
                target_id=entry_id,
                rationale="Auto-generated from failure reflection",
                metric_evidence={"pattern": rule_data.get("pattern", "")},
            )

        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Avoidance rule generation failed: %s", e)
