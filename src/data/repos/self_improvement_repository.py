"""Self-improvement persistence: metrics, audit log, prompt supplements, tool gaps and fix proposals."""

import logging
from datetime import datetime
from typing import Optional

from src.utils.timezone import local_now, to_naive_utc, utc_now_naive

from sqlalchemy import case, func

from ..models_sqlite import (
    PromptSupplement,
    SelfImprovementAuditLogEntry,
    SelfImprovementMetric,
    ToolFixProposal,
    ToolGapReport,
)
from .base_repository import BaseRepository
from src.utils.ids import new_id

logger = logging.getLogger(__name__)

# Allowed ToolFixProposal transitions {(from, to)}: proposed -> trial_pending
# -> applied|rejected, or proposed -> rejected directly (manual review without
# trial).  Matches ToolFixProposalService docstring; enforced via CAS UPDATE so
# illegal jumps (skip trial_pending, leave a terminal status) match no row and
# return None — consistent with ImprovementProposalRepository._cas_transition
# (026 类型审查 I1).
_FIX_PROPOSAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("proposed", "trial_pending"),
        ("proposed", "rejected"),
        ("trial_pending", "applied"),
        ("trial_pending", "rejected"),
    }
)

# Allowed ToolGapReport transitions: detected/trial_pending -> resolved|trial_failed.
# ``trial_pending`` is a legal intermediate status (dedup/query accept it) even
# though no current code path enters it proactively (026 类型审查 I1).
_GAP_REPORT_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("detected", "trial_pending"),
        ("detected", "resolved"),
        ("detected", "trial_failed"),
        ("trial_pending", "resolved"),
        ("trial_pending", "trial_failed"),
    }
)


def _transition_sources(transitions: frozenset[tuple[str, str]], to_status: str) -> frozenset[str]:
    """Source statuses allowed to transition to ``to_status``."""
    return frozenset(src for src, tgt in transitions if tgt == to_status)


class SelfImprovementRepository(BaseRepository):
    """Repository for self-improvement metrics, audit, prompt supplements and tool gaps."""

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def log_action(
        self,
        action_type: str,
        target_type: Optional[str],
        target_id: Optional[str],
        before_snapshot: Optional[dict],
        after_snapshot: Optional[dict],
        rationale: Optional[str],
        metric_evidence: Optional[dict],
        triggered_by: str = "auto",
    ) -> SelfImprovementAuditLogEntry:
        """Write an audit entry for a self-improvement action."""
        entry = SelfImprovementAuditLogEntry(
            audit_id=new_id(),
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            rationale=rationale,
            metric_evidence=metric_evidence,
            triggered_by=triggered_by,
        )
        try:
            self.session.add(entry)
            self._commit()
            self.session.refresh(entry)
            logger.info(
                "Audit entry logged: %s (action=%s, target=%s/%s)",
                entry.audit_id,
                action_type,
                target_type,
                target_id,
            )
            return entry
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to log audit entry: %s", e)
            raise

    def count_actions_today(self, action_type: str) -> int:
        """Count actions of a given type created today (for rate limiting).

        「今天」按用户本地日期算，但 ``created_at`` 存的是 naive UTC，所以要把本地
        零点换算成 UTC 再比较。原来直接拿本地零点当 UTC 用：在 UTC+8 下等于筛
        ``UTC >= 今天00:00``，而本地今天真正对应的是 ``[昨天16:00, 今天16:00)``——
        本地今天 00:00~08:00 产生的记录全被漏掉，限流在每天早上失效。
        """
        today_start_local = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start = to_naive_utc(today_start_local)
        return (
            self.session.query(SelfImprovementAuditLogEntry)
            .filter(
                SelfImprovementAuditLogEntry.action_type == action_type,
                SelfImprovementAuditLogEntry.created_at >= today_start,
            )
            .count()
        )

    def get_audit_history(
        self,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[SelfImprovementAuditLogEntry]:
        """Query audit log, optionally filtered by target type/id."""
        query = self.session.query(SelfImprovementAuditLogEntry)
        if target_type is not None:
            query = query.filter(SelfImprovementAuditLogEntry.target_type == target_type)
        if target_id is not None:
            query = query.filter(SelfImprovementAuditLogEntry.target_id == target_id)
        return query.order_by(SelfImprovementAuditLogEntry.created_at.desc()).limit(limit).all()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def record_metric(
        self,
        metric_type: str,
        metric_key: Optional[str],
        metric_value: float,
        sample_size: int = 1,
        metadata: Optional[dict] = None,
    ) -> SelfImprovementMetric:
        """Write a time-series metric data point."""
        entry = SelfImprovementMetric(
            metric_id=new_id(),
            metric_type=metric_type,
            metric_key=metric_key,
            metric_value=metric_value,
            sample_size=sample_size,
            metadata_=metadata,
        )
        try:
            self.session.add(entry)
            self._commit()
            self.session.refresh(entry)
            logger.info(
                "Metric recorded: %s (type=%s, key=%s, value=%.4f)",
                entry.metric_id,
                metric_type,
                metric_key,
                metric_value,
            )
            return entry
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to record metric: %s", e)
            raise

    def get_metrics(
        self,
        metric_type: str,
        metric_key: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[SelfImprovementMetric]:
        """Query time-series metrics, optionally filtered by key and start time."""
        query = self.session.query(SelfImprovementMetric).filter(
            SelfImprovementMetric.metric_type == metric_type,
        )
        if metric_key is not None:
            query = query.filter(SelfImprovementMetric.metric_key == metric_key)
        if since is not None:
            query = query.filter(SelfImprovementMetric.measured_at >= since)
        return query.order_by(SelfImprovementMetric.measured_at.desc()).limit(limit).all()

    def get_latest_metric(
        self,
        metric_type: str,
        metric_key: Optional[str],
    ) -> Optional[SelfImprovementMetric]:
        """Get the most recent metric value for a type/key combination."""
        query = self.session.query(SelfImprovementMetric).filter(
            SelfImprovementMetric.metric_type == metric_type,
        )
        if metric_key is not None:
            query = query.filter(SelfImprovementMetric.metric_key == metric_key)
        return query.order_by(SelfImprovementMetric.measured_at.desc()).first()

    # ------------------------------------------------------------------
    # Prompt Supplements
    # ------------------------------------------------------------------

    def create_supplement(
        self,
        target_section: str,
        content: str,
        rationale: Optional[str],
        metric_evidence: Optional[dict],
        prompt_hash: Optional[str],
    ) -> PromptSupplement:
        """Create a candidate prompt supplement."""
        supplement = PromptSupplement(
            supplement_id=new_id(),
            target_section=target_section,
            content=content,
            rationale=rationale,
            metric_evidence=metric_evidence,
            status="candidate",
            version=1,
            prompt_hash=prompt_hash,
        )
        try:
            self.session.add(supplement)
            self._commit()
            self.session.refresh(supplement)
            logger.info(
                "Supplement created: %s (section=%s)",
                supplement.supplement_id,
                target_section,
            )
            return supplement
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to create supplement: %s", e)
            raise

    def get_active_supplements(self) -> list[PromptSupplement]:
        """Get all active supplements ordered by target_section."""
        return (
            self.session.query(PromptSupplement)
            .filter(PromptSupplement.status == "active")
            .order_by(PromptSupplement.target_section, PromptSupplement.version.desc())
            .all()
        )

    def get_candidate_supplements(self) -> list[PromptSupplement]:
        """Get all candidate supplements."""
        return (
            self.session.query(PromptSupplement)
            .filter(PromptSupplement.status == "candidate")
            .order_by(PromptSupplement.created_at.desc())
            .all()
        )

    def promote_supplement(self, supplement_id: str) -> Optional[PromptSupplement]:
        """Promote a candidate to active, superseding previous active for the same section."""
        supplement = (
            self.session.query(PromptSupplement)
            .filter(PromptSupplement.supplement_id == supplement_id)
            .first()
        )
        if supplement is None:
            return None
        if supplement.status != "candidate":
            logger.warning(
                "Cannot promote supplement %s: current status is %s, expected candidate",
                supplement_id,
                supplement.status,
            )
            return None
        try:
            now = utc_now_naive()
            # 原子 supersede 当前 active（批量 UPDATE，避免逐行 read-modify-write）
            self.session.query(PromptSupplement).filter(
                PromptSupplement.target_section == supplement.target_section,
                PromptSupplement.status == "active",
                PromptSupplement.supplement_id != supplement_id,
            ).update(
                {"status": "superseded", "retracted_at": now},
                synchronize_session=False,
            )
            # 原子 promote：version = (max version + 1) 进 SQL 子查询，CAS status=candidate，
            # 避免并发两 promote 读到同 max 落同 version（026 I7）。
            max_version_subq = (
                self.session.query(func.max(PromptSupplement.version))
                .filter(PromptSupplement.target_section == supplement.target_section)
                .scalar_subquery()
            )
            updated = (
                self.session.query(PromptSupplement)
                .filter(
                    PromptSupplement.supplement_id == supplement_id,
                    PromptSupplement.status == "candidate",
                )
                .update(
                    {
                        "version": func.coalesce(max_version_subq, 0) + 1,
                        "status": "active",
                        "applied_at": now,
                    },
                    synchronize_session=False,
                )
            )
            self._commit()
            if updated == 0:
                return None
            self.session.refresh(supplement)
            logger.info(
                "Supplement promoted: %s (section=%s, version=%d)",
                supplement.supplement_id,
                supplement.target_section,
                supplement.version,
            )
            return supplement
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to promote supplement %s: %s", supplement_id, e)
            raise

    def retract_supplement(
        self,
        supplement_id: str,
        reason: Optional[str],
    ) -> Optional[PromptSupplement]:
        """Retract a candidate or active supplement."""
        supplement = (
            self.session.query(PromptSupplement)
            .filter(PromptSupplement.supplement_id == supplement_id)
            .first()
        )
        if supplement is None:
            return None
        if supplement.status not in ("candidate", "active"):
            logger.warning(
                "Cannot retract supplement %s: current status is %s",
                supplement_id,
                supplement.status,
            )
            return None
        try:
            supplement.status = "retracted"
            supplement.retracted_at = utc_now_naive()
            if reason:
                supplement.rationale = (
                    f"{supplement.rationale}\n\nRetraction reason: {reason}"
                    if supplement.rationale
                    else f"Retraction reason: {reason}"
                )
            self._commit()
            self.session.refresh(supplement)
            logger.info(
                "Supplement retracted: %s (section=%s)",
                supplement.supplement_id,
                supplement.target_section,
            )
            return supplement
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to retract supplement %s: %s", supplement_id, e)
            raise

    def get_supplement_version_history(
        self,
        target_section: str,
        limit: int = 10,
    ) -> list[PromptSupplement]:
        """Get version history for a prompt section."""
        return (
            self.session.query(PromptSupplement)
            .filter(PromptSupplement.target_section == target_section)
            .order_by(PromptSupplement.version.desc())
            .limit(limit)
            .all()
        )

    # ------------------------------------------------------------------
    # Tool Gap Reports
    # ------------------------------------------------------------------

    def create_gap_report(
        self,
        gap_type: str,
        tool_name: Optional[str],
        pattern_signature: Optional[str],
        evidence: Optional[dict],
    ) -> ToolGapReport:
        """Create a gap report, or increment occurrence_count if same pattern_signature exists."""
        try:
            # Deduplicate by pattern_signature when present
            if pattern_signature:
                existing = (
                    self.session.query(ToolGapReport)
                    .filter(
                        ToolGapReport.pattern_signature == pattern_signature,
                        ToolGapReport.gap_type == gap_type,
                        ToolGapReport.status.in_(("detected", "trial_pending")),
                    )
                    .first()
                )
                if existing is not None:
                    # 原子条件 UPDATE：occurrence_count/confidence 自增进 SQL，避免
                    # read-modify-write 在并发自增下丢计数（026 I7）。
                    updates = {
                        "occurrence_count": ToolGapReport.occurrence_count + 1,
                        "confidence": case(
                            (
                                ToolGapReport.confidence + 0.1 < 1.0,
                                ToolGapReport.confidence + 0.1,
                            ),
                            else_=1.0,
                        ),
                    }
                    if evidence:
                        updates["evidence"] = evidence
                    updated = (
                        self.session.query(ToolGapReport)
                        .filter(
                            ToolGapReport.report_id == existing.report_id,
                            ToolGapReport.status.in_(("detected", "trial_pending")),
                        )
                        .update(updates, synchronize_session=False)
                    )
                    self._commit()
                    if updated == 0:
                        # CAS 失败（report 在 dedup 读后被 resolve/fail 移出
                        # detected/trial_pending）：返回当前行（不再自增，report 已终态），
                        # 避免 4 个调用方 report.report_id 崩溃（026 I7 follow-up）。
                        self.session.expire_all()
                        return (
                            self.session.query(ToolGapReport)
                            .filter(ToolGapReport.report_id == existing.report_id)
                            .first()
                        )
                    self.session.refresh(existing)
                    logger.info(
                        "Gap report occurrence incremented: %s (signature=%s, count=%d)",
                        existing.report_id,
                        pattern_signature,
                        existing.occurrence_count,
                    )
                    return existing

            report = ToolGapReport(
                report_id=new_id(),
                gap_type=gap_type,
                tool_name=tool_name,
                pattern_signature=pattern_signature,
                occurrence_count=1,
                confidence=0.1,
                status="detected",
                evidence=evidence,
            )
            self.session.add(report)
            self._commit()
            self.session.refresh(report)
            logger.info(
                "Gap report created: %s (type=%s, tool=%s)",
                report.report_id,
                gap_type,
                tool_name,
            )
            return report
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to create gap report: %s", e)
            raise

    def get_unresolved_gap_reports(
        self,
        min_confidence: float = 0.0,
    ) -> list[ToolGapReport]:
        """Get detected gaps above a confidence threshold, ordered by confidence descending."""
        return (
            self.session.query(ToolGapReport)
            .filter(
                ToolGapReport.status.in_(("detected", "trial_pending")),
                ToolGapReport.confidence >= min_confidence,
            )
            .order_by(ToolGapReport.confidence.desc(), ToolGapReport.occurrence_count.desc())
            .all()
        )

    def resolve_gap_report(self, report_id: str) -> Optional[ToolGapReport]:
        """Mark a gap report as resolved (CAS detected|trial_pending -> resolved).

        Returns the updated row, or None if the report does not exist or is not
        in a resolvable status (already resolved/trial_failed).
        """
        return self._cas_gap_report_transition(report_id, "resolved")

    def fail_gap_report(self, report_id: str) -> Optional[ToolGapReport]:
        """Mark a gap report as trial_failed (CAS detected|trial_pending -> trial_failed).

        Returns the updated row, or None if the report does not exist or is not
        in a failable status (already resolved/trial_failed).
        """
        return self._cas_gap_report_transition(report_id, "trial_failed")

    def _cas_gap_report_transition(
        self,
        report_id: str,
        to_status: str,
    ) -> Optional[ToolGapReport]:
        """Atomic conditional UPDATE with rowcount CAS guard for gap reports."""
        sources = _transition_sources(_GAP_REPORT_TRANSITIONS, to_status)
        if not sources:
            logger.warning(
                "Cannot transition gap report %s: %r is not a legal target",
                report_id,
                to_status,
            )
            return None
        try:
            updated = (
                self.session.query(ToolGapReport)
                .filter(
                    ToolGapReport.report_id == report_id,
                    ToolGapReport.status.in_(sources),
                )
                .update(
                    {"status": to_status, "updated_at": utc_now_naive()},
                    synchronize_session=False,
                )
            )
            self._commit()
            if updated == 0:
                return None
            logger.info("Gap report transitioned: %s -> %s", report_id, to_status)
            return self.session.get(ToolGapReport, report_id)
        except Exception as e:
            self.session.rollback()
            logger.error(
                "Failed to transition gap report %s -> %s: %s",
                report_id,
                to_status,
                e,
            )
            raise

    # ------------------------------------------------------------------
    # Tool Fix Proposals
    # ------------------------------------------------------------------

    def create_fix_proposal(
        self,
        tool_id: str,
        gap_report_id: Optional[str],
        proposed_code: Optional[str],
        rationale: Optional[str],
        before_code: Optional[str],
    ) -> ToolFixProposal:
        """Create a proposed tool fix."""
        proposal = ToolFixProposal(
            proposal_id=new_id(),
            tool_id=tool_id,
            gap_report_id=gap_report_id,
            proposed_code=proposed_code,
            rationale=rationale,
            status="proposed",
            before_code=before_code,
        )
        try:
            self.session.add(proposal)
            self._commit()
            self.session.refresh(proposal)
            logger.info("Fix proposal created: %s (tool=%s)", proposal.proposal_id, tool_id)
            return proposal
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to create fix proposal: %s", e)
            raise

    def get_pending_fix_proposals(self) -> list[ToolFixProposal]:
        """Get all proposed fixes awaiting action."""
        return (
            self.session.query(ToolFixProposal)
            .filter(ToolFixProposal.status.in_(("proposed", "trial_pending")))
            .order_by(ToolFixProposal.created_at.asc())
            .all()
        )

    def transition_fix_proposal(
        self,
        proposal_id: str,
        new_status: str,
        trial_result: Optional[dict] = None,
    ) -> Optional[ToolFixProposal]:
        """CAS transition a fix proposal along the legal state machine.

        Illegal transitions (skip ``trial_pending``, leave a terminal status,
        unknown target) match no row -> return None without writing.  Optional
        ``trial_result`` is attached and ``applied_at`` set when entering
        ``applied`` (026 类型审查 I1).
        """
        sources = _transition_sources(_FIX_PROPOSAL_TRANSITIONS, new_status)
        if not sources:
            logger.warning(
                "Cannot transition fix proposal %s: %r is not a legal target",
                proposal_id,
                new_status,
            )
            return None
        values: dict = {"status": new_status}
        if trial_result is not None:
            values["trial_result"] = trial_result
        if new_status == "applied":
            values["applied_at"] = utc_now_naive()
        try:
            updated = (
                self.session.query(ToolFixProposal)
                .filter(
                    ToolFixProposal.proposal_id == proposal_id,
                    ToolFixProposal.status.in_(sources),
                )
                .update(values, synchronize_session=False)
            )
            self._commit()
            if updated == 0:
                return None
            logger.info("Fix proposal transitioned: %s -> %s", proposal_id, new_status)
            return self.session.get(ToolFixProposal, proposal_id)
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to transition fix proposal %s: %s", proposal_id, e)
            raise
