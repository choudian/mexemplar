"""Tool gap detection and fix proposal service for agent self-improvement.

Detects missing tools, repeated tool-call patterns, high-iteration sessions,
and bug patterns from workflow transitions and message traces.  Gap reports
that reach a configurable confidence threshold can be forwarded to LLM for
auto-tool-creation proposals.  A separate ToolFixProposalService manages the
lifecycle of fix proposals (proposed -> trial_pending -> applied | rejected).
"""

import hashlib
import json
import logging
from collections import Counter
from typing import Optional

from src.business.debug.service import get_debug_service
from src.business.self_improvement.audit_service import SelfImprovementAuditService
from src.business.self_improvement.safety_governor import SafetyGovernor
from src.data.repos.self_improvement_repository import SelfImprovementRepository
from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)


def _safe_redact_error(text: str) -> str:
    """Redact tool error text for evidence with a fail-safe fallback (026 M8).

    Prefer the registered-secret redactor; if it is unavailable, fall back to the
    proposal denylist sanitizer; only if both fail use a fixed placeholder so
    untrusted error text never reaches evidence/LLM unredacted.
    """
    try:
        return get_debug_service().redactor.redact(text)[:200]
    except Exception:
        logger.warning("debug redactor unavailable for tool-gap evidence", exc_info=True)
    try:
        from src.business.self_improvement.proposal_service import (
            sanitize_proposal_public_text,
        )

        return (sanitize_proposal_public_text(text) or "")[:200]
    except Exception:
        logger.warning("denylist sanitizer also unavailable; using placeholder", exc_info=True)
        return "redaction-unavailable"


class ToolGapDetector:
    """Scans workflow transitions and messages for tool capability gaps.

    Four gap types are recognised (matching the ``tool_gap_reports`` check
    constraint):

    - ``missing_tool``: the agent repeatedly attempts a task that no available
      tool can accomplish.
    - ``repeated_pattern``: an identical tool-call sequence appears across
      multiple sessions, suggesting a composite tool opportunity.
    - ``high_iteration``: a single task requires an unusually high number of
      tool calls, indicating the tool surface may be too low-level.
    - ``bug_pattern``: the same tool fails in the same way more than once.
    """

    def __init__(
        self,
        si_repo: SelfImprovementRepository,
        audit_service: SelfImprovementAuditService,
        safety_governor: SafetyGovernor,
    ):
        self._si_repo = si_repo
        self._audit = audit_service
        self._safety = safety_governor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_for_gaps(
        self,
        workflow_transitions: list[dict],
        messages: list[dict],
    ) -> list[str]:
        """Run a full gap-detection scan over the provided traces.

        Args:
            workflow_transitions: List of workflow transition dicts, each with
                at least ``tool_name``, ``status``, ``session_id`` keys.
            messages: List of message dicts, each with at least
                ``role``, ``content``, ``session_id`` keys.

        Returns:
            List of newly created ``report_id`` values (may be empty).
        """
        config = get_unified_config()
        created_ids: list[str] = []

        # 1. Missing-tool detection
        missing_ids = self._detect_missing_tools(messages, config)
        created_ids.extend(missing_ids)

        # 2. Repeated-pattern detection
        repeated_ids = self._detect_repeated_patterns(workflow_transitions, config)
        created_ids.extend(repeated_ids)

        # 3. High-iteration detection
        high_iter_ids = self._detect_high_iterations(workflow_transitions, config)
        created_ids.extend(high_iter_ids)

        # 4. Bug-pattern detection
        bug_ids = self._detect_bug_patterns(workflow_transitions, config)
        created_ids.extend(bug_ids)

        return created_ids

    def get_gaps_above_threshold(self) -> list[dict]:
        """Get gap reports whose occurrence count reaches the action threshold.

        Returns:
            List of dicts with ``report_id``, ``gap_type``, ``tool_name``,
            ``pattern_signature``, ``occurrence_count``, ``confidence``,
            ``evidence`` keys.
        """
        config = get_unified_config()
        threshold = config.get_self_improvement_tool_gap_threshold()
        reports = self._si_repo.get_unresolved_gap_reports(min_confidence=0.0)

        results: list[dict] = []
        for report in reports:
            if (report.occurrence_count or 0) >= threshold:
                evidence = getattr(report, "evidence", None)
                if isinstance(evidence, str):
                    try:
                        evidence = json.loads(evidence)
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(
                    {
                        "report_id": report.report_id,
                        "gap_type": report.gap_type,
                        "tool_name": getattr(report, "tool_name", None),
                        "pattern_signature": getattr(report, "pattern_signature", None),
                        "occurrence_count": report.occurrence_count,
                        "confidence": report.confidence,
                        "evidence": evidence,
                    }
                )
        return results

    def propose_auto_tool_creation(
        self,
        report: dict,
        llm_client=None,
    ) -> Optional[str]:
        """Propose an auto-created tool for a gap report that has reached threshold.

        Args:
            report: A gap report dict (as returned by ``get_gaps_above_threshold``).
            llm_client: Optional LLM client with a ``call(messages, max_tokens,
                temperature)`` interface.

        Returns:
            The ``proposal_id`` of the created fix proposal, or None on failure.
        """
        # 1. Rate limit
        if not self._safety.check_rate_limit(SafetyGovernor.TOOL_AUTO_CREATED):
            logger.debug("Tool auto-creation rate limit reached")
            return None

        if llm_client is None:
            logger.debug("No LLM client available for auto-tool proposal")
            return None

        # 2. Ask LLM to propose a tool
        proposal_data = self._generate_tool_proposal(llm_client, report)
        if proposal_data is None:
            return None

        # 3. Store as a fix proposal
        tool_name = report.get("tool_name") or report.get("pattern_signature", "unknown")
        created = self._si_repo.create_fix_proposal(
            tool_id=tool_name,
            gap_report_id=report.get("report_id"),
            proposed_code=proposal_data.get("proposed_code"),
            rationale=proposal_data.get("rationale"),
            before_code=None,
        )

        # 4. Audit
        self._audit.log_action(
            action_type="tool_auto_created",
            target_type="tool_fix_proposal",
            target_id=created.proposal_id,
            rationale=proposal_data.get("rationale", "Auto-proposed from gap report"),
            metric_evidence={
                "gap_type": report.get("gap_type"),
                "occurrence_count": report.get("occurrence_count"),
                "confidence": report.get("confidence"),
            },
        )

        return created.proposal_id

    # ------------------------------------------------------------------
    # Private: detection helpers
    # ------------------------------------------------------------------

    def _detect_missing_tools(
        self,
        messages: list[dict],
        config,
    ) -> list[str]:
        """Detect missing-tool gaps from assistant messages that indicate inability.

        Looks for assistant messages containing phrases like "I don't have a tool"
        or "no tool available" and records a ``missing_tool`` gap.
        """
        created: list[str] = []
        inability_keywords = [
            "i don't have a tool",
            "no tool available",
            "no suitable tool",
            "cannot find a tool",
            "i am unable to",
            "there is no tool",
        ]

        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = (msg.get("content") or "").lower()
            if not any(kw in content for kw in inability_keywords):
                continue

            # Build a pattern signature from the message snippet
            snippet = content[:200]
            signature = "missing_tool:" + hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:12]
            session_id = msg.get("session_id", "unknown")

            report = self._si_repo.create_gap_report(
                gap_type="missing_tool",
                tool_name=None,
                pattern_signature=signature,
                evidence={"session_id": session_id, "snippet": snippet},
            )
            created.append(report.report_id)

        return created

    def _detect_repeated_patterns(
        self,
        workflow_transitions: list[dict],
        config,
    ) -> list[str]:
        """Detect repeated tool-call patterns that suggest a composite tool.

        Groups consecutive tool calls within the same session into sequences,
        then looks for sequences that appear across multiple sessions.
        """
        created: list[str] = []

        # Group transitions by session
        session_sequences: dict[str, list[str]] = {}
        for t in workflow_transitions:
            sid = t.get("session_id", "unknown")
            tool = t.get("tool_name", "")
            if not tool:
                continue
            session_sequences.setdefault(sid, []).append(tool)

        # Build n-gram sequences (triplets) and count across sessions
        n = 3
        sequence_sessions: dict[str, set[str]] = {}
        for sid, tools in session_sequences.items():
            if len(tools) < n:
                continue
            for i in range(len(tools) - n + 1):
                seq = " -> ".join(tools[i : i + n])
                sequence_sessions.setdefault(seq, set()).add(sid)

        # Any sequence appearing in 2+ sessions is a repeated pattern
        for seq, sids in sequence_sessions.items():
            if len(sids) < 2:
                continue

            signature = "repeated:" + hashlib.sha256(seq.encode("utf-8")).hexdigest()[:12]
            report = self._si_repo.create_gap_report(
                gap_type="repeated_pattern",
                tool_name=None,
                pattern_signature=signature,
                evidence={
                    "sequence": seq,
                    "session_count": len(sids),
                    "session_ids": sorted(sids)[:10],
                },
            )
            created.append(report.report_id)

        return created

    def _detect_high_iterations(
        self,
        workflow_transitions: list[dict],
        config,
    ) -> list[str]:
        """Detect sessions with unusually high tool-call counts.

        Uses ``self_improvement.tool_gap_threshold`` as the minimum iteration
        count to flag.
        """
        created: list[str] = []
        threshold = config.get_self_improvement_tool_gap_threshold()

        # Count tool calls per session
        session_counts: dict[str, int] = {}
        session_tools: dict[str, list[str]] = {}
        for t in workflow_transitions:
            sid = t.get("session_id", "unknown")
            tool = t.get("tool_name", "")
            if not tool:
                continue
            session_counts[sid] = session_counts.get(sid, 0) + 1
            session_tools.setdefault(sid, []).append(tool)

        for sid, count in session_counts.items():
            if count < threshold:
                continue

            tools_used = session_tools.get(sid, [])
            signature = "high_iter:" + hashlib.sha256(sid.encode("utf-8")).hexdigest()[:12]
            report = self._si_repo.create_gap_report(
                gap_type="high_iteration",
                tool_name=None,
                pattern_signature=signature,
                evidence={
                    "session_id": sid,
                    "iteration_count": count,
                    "tools_used": Counter(tools_used).most_common(10),
                },
            )
            created.append(report.report_id)

        return created

    def _detect_bug_patterns(
        self,
        workflow_transitions: list[dict],
        config,
    ) -> list[str]:
        """Detect tools that fail repeatedly in the same way.

        Groups failed transitions by (tool_name, error_fingerprint) and flags
        any pair appearing across multiple sessions.
        """
        created: list[str] = []

        # Collect failures with error fingerprints
        failure_map: dict[str, dict] = {}  # fingerprint -> {tool, sessions, errors}
        for t in workflow_transitions:
            status = t.get("status", "")
            if status not in ("error", "failed"):
                continue
            tool = t.get("tool_name", "")
            if not tool:
                continue

            # 先脱敏再截断/算指纹：error_message 可能含已注册 secret（API key 等），
            # 不得原样入库 evidence 或喂 LLM（026 C3）。相同 secret 产生相同指纹，
            # 不影响去重。
            raw_error = t.get("error_message") or t.get("error") or "unknown"
            error_msg = _safe_redact_error(str(raw_error))
            fingerprint = f"{tool}:{hashlib.sha256(error_msg.encode('utf-8')).hexdigest()[:8]}"
            sid = t.get("session_id", "unknown")

            if fingerprint not in failure_map:
                failure_map[fingerprint] = {
                    "tool": tool,
                    "sessions": set(),
                    "errors": [],
                }
            failure_map[fingerprint]["sessions"].add(sid)
            failure_map[fingerprint]["errors"].append(error_msg)

        # Any fingerprint seen in 2+ sessions is a bug pattern
        for fingerprint, info in failure_map.items():
            if len(info["sessions"]) < 2:
                continue

            signature = "bug:" + fingerprint
            report = self._si_repo.create_gap_report(
                gap_type="bug_pattern",
                tool_name=info["tool"],
                pattern_signature=signature,
                evidence={
                    "tool_name": info["tool"],
                    "session_count": len(info["sessions"]),
                    "session_ids": sorted(info["sessions"])[:10],
                    "sample_errors": info["errors"][:5],
                },
            )
            created.append(report.report_id)

        return created

    # ------------------------------------------------------------------
    # Private: LLM proposal generation
    # ------------------------------------------------------------------

    def _generate_tool_proposal(self, llm_client, report: dict) -> Optional[dict]:
        """Ask the LLM to propose a new tool definition for the given gap."""
        gap_type = report.get("gap_type", "unknown")
        evidence = report.get("evidence", {})
        occurrence_count = report.get("occurrence_count", 0)

        # evidence 可能来自存量库（历史泄漏），喂 LLM 前再 redact 一道（026 C3）。
        # redactor 不可用时回退空 evidence,绝不把未脱敏历史 evidence 喂 LLM（026 M8）。
        if evidence:
            try:
                redacted_evidence = get_debug_service().redactor.redact_json(evidence)
            except Exception:
                logger.warning(
                    "debug redactor unavailable for LLM tool-proposal evidence; sending empty",
                    exc_info=True,
                )
                redacted_evidence = {}
        else:
            redacted_evidence = {}
        prompt = (
            "You are analyzing tool capability gaps in an AI assistant system.\n"
            "\n"
            f"## Gap Type\n{gap_type}\n\n"
            f"## Occurrence Count\n{occurrence_count}\n\n"
            f"## Evidence\n{json.dumps(redacted_evidence, ensure_ascii=False, indent=2)[:2000]}\n\n"
            "## Task\n"
            "Propose a new tool that would address this gap. The tool should:\n"
            "- Have a clear, specific purpose\n"
            "- Reduce the need for repeated manual workarounds\n"
            "- Be safe to execute (read-only or idempotent where possible)\n"
            "\n"
            "Return a JSON object with:\n"
            '- "proposed_code": a Python function signature and docstring for the tool\n'
            '- "rationale": why this tool would address the gap\n'
            "\n"
            "Return ONLY the JSON object."
        )

        try:
            response = llm_client.call(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.3,
            )
            if not response or not response.strip():
                return None

            json_str = response.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1])

            result = json.loads(json_str)
            if not isinstance(result, dict) or "proposed_code" not in result:
                logger.warning("Invalid tool proposal format from LLM")
                return None

            result.setdefault("rationale", "Auto-generated from gap detection")
            return result

        except Exception as e:
            # ``(json.JSONDecodeError, Exception)`` 等价于 ``Exception`` 且会误导读者
            # 以为在精确捕获 JSON 错误；此处 LLM 调用 + JSON 解析均属 best-effort，
            # 任何异常都回退到 None。补 report 上下文便于关联具体 gap（026 errors I2）。
            logger.warning(
                "LLM tool proposal generation failed (gap=%s, report=%s): %s",
                report.get("gap_type"),
                report.get("report_id"),
                e,
            )
            return None


class ToolFixProposalService:
    """Manages the lifecycle of tool fix proposals.

    Status transitions::

        proposed -> trial_pending -> applied
            |                    \\-> rejected
            \\-> rejected (manual review without trial)
    """

    def __init__(
        self,
        si_repo: SelfImprovementRepository,
        audit_service: SelfImprovementAuditService,
        safety_governor: SafetyGovernor,
    ):
        self._si_repo = si_repo
        self._audit = audit_service
        self._safety = safety_governor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_pending_proposals(self) -> list[dict]:
        """Get all fix proposals awaiting action (status ``proposed`` or ``trial_pending``).

        Returns:
            List of dicts with ``proposal_id``, ``tool_id``, ``gap_report_id``,
            ``proposed_code``, ``rationale``, ``status``, ``before_code``,
            ``trial_result``, ``created_at`` keys.
        """
        proposals = self._si_repo.get_pending_fix_proposals()
        return [self._proposal_to_dict(p) for p in proposals]

    def mark_trial_pending(self, proposal_id: str) -> Optional[dict]:
        """Transition a fix proposal from ``proposed`` to ``trial_pending``.

        Args:
            proposal_id: The proposal to transition.

        Returns:
            Updated proposal dict, or None if the proposal was not found or
            not in ``proposed`` status.
        """
        proposal = self._si_repo.transition_fix_proposal(
            proposal_id=proposal_id,
            new_status="trial_pending",
        )
        if proposal is None:
            logger.warning("Cannot mark trial_pending: proposal %s not found", proposal_id)
            return None

        self._audit.log_action(
            action_type="fix_proposal_trial_started",
            target_type="tool_fix_proposal",
            target_id=proposal_id,
            rationale="Proposal moved to trial_pending for evaluation",
        )

        return self._proposal_to_dict(proposal)

    def apply_fix(self, proposal_id: str, trial_result: dict) -> Optional[dict]:
        """Mark a fix proposal as ``applied`` after a successful trial.

        Also resolves the associated gap report if one exists.

        Args:
            proposal_id: The proposal to apply.
            trial_result: Dict with trial outcome details (e.g. success metrics).

        Returns:
            Updated proposal dict, or None if not found or not in
            ``trial_pending`` status.
        """
        proposal = self._si_repo.transition_fix_proposal(
            proposal_id=proposal_id,
            new_status="applied",
            trial_result=trial_result,
        )
        if proposal is None:
            logger.warning("Cannot apply fix: proposal %s not found", proposal_id)
            return None

        # Resolve the associated gap report, if any
        gap_report_id = getattr(proposal, "gap_report_id", None)
        if gap_report_id:
            try:
                self._si_repo.resolve_gap_report(gap_report_id)
            except Exception as e:
                logger.warning("Failed to resolve gap report %s: %s", gap_report_id, e)

        self._audit.log_action(
            action_type="fix_proposal_applied",
            target_type="tool_fix_proposal",
            target_id=proposal_id,
            rationale="Fix applied after successful trial",
            metric_evidence=trial_result,
        )

        return self._proposal_to_dict(proposal)

    def reject_fix(self, proposal_id: str, reason: str) -> Optional[dict]:
        """Reject a fix proposal after a failed trial or manual review.

        Also marks the associated gap report as ``trial_failed`` if one exists.

        Args:
            proposal_id: The proposal to reject.
            reason: Human-readable explanation for the rejection.

        Returns:
            Updated proposal dict, or None if not found or not in a
            rejectable status.
        """
        proposal = self._si_repo.transition_fix_proposal(
            proposal_id=proposal_id,
            new_status="rejected",
            trial_result={"rejection_reason": reason},
        )
        if proposal is None:
            logger.warning("Cannot reject fix: proposal %s not found", proposal_id)
            return None

        # Mark the associated gap report as trial_failed
        gap_report_id = getattr(proposal, "gap_report_id", None)
        if gap_report_id:
            try:
                self._si_repo.fail_gap_report(gap_report_id)
            except Exception as e:
                logger.warning("Failed to mark gap report %s as trial_failed: %s", gap_report_id, e)

        self._audit.log_action(
            action_type="fix_proposal_rejected",
            target_type="tool_fix_proposal",
            target_id=proposal_id,
            rationale=reason,
        )

        return self._proposal_to_dict(proposal)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _proposal_to_dict(proposal) -> dict:
        """Convert a ToolFixProposal ORM object to a plain dict."""
        trial_result = getattr(proposal, "trial_result", None)
        if isinstance(trial_result, str):
            try:
                trial_result = json.loads(trial_result)
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "proposal_id": getattr(proposal, "proposal_id", ""),
            "tool_id": getattr(proposal, "tool_id", ""),
            "gap_report_id": getattr(proposal, "gap_report_id", None),
            "proposed_code": getattr(proposal, "proposed_code", None),
            "rationale": getattr(proposal, "rationale", None),
            "status": getattr(proposal, "status", ""),
            "before_code": getattr(proposal, "before_code", None),
            "trial_result": trial_result,
            "created_at": getattr(proposal, "created_at", None),
        }
