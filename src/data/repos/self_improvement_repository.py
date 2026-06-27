"""Self-improvement persistence: metrics, audit log, prompt supplements, tool gaps and fix proposals."""

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import func

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
        """Count actions of a given type created today (for rate limiting)."""
        today_start = datetime.combine(date.today(), datetime.min.time())
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
            # Supersede current active supplements for the same section
            current_active = (
                self.session.query(PromptSupplement)
                .filter(
                    PromptSupplement.target_section == supplement.target_section,
                    PromptSupplement.status == "active",
                    PromptSupplement.supplement_id != supplement_id,
                )
                .all()
            )
            now = datetime.now()
            for active in current_active:
                active.status = "superseded"
                active.retracted_at = now

            # Compute version: max version for this section + 1
            max_version = (
                self.session.query(func.max(PromptSupplement.version))
                .filter(PromptSupplement.target_section == supplement.target_section)
                .scalar()
            )
            supplement.version = (max_version or 0) + 1
            supplement.status = "active"
            supplement.applied_at = now
            self._commit()
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
            supplement.retracted_at = datetime.now()
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
                    existing.occurrence_count = (existing.occurrence_count or 0) + 1
                    existing.confidence = min(1.0, (existing.confidence or 0.0) + 0.1)
                    if evidence:
                        existing.evidence = evidence
                    self._commit()
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
        """Mark a gap report as resolved."""
        report = (
            self.session.query(ToolGapReport)
            .filter(ToolGapReport.report_id == report_id)
            .first()
        )
        if report is None:
            return None
        try:
            report.status = "resolved"
            report.updated_at = datetime.now()
            self._commit()
            self.session.refresh(report)
            logger.info("Gap report resolved: %s", report_id)
            return report
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to resolve gap report %s: %s", report_id, e)
            raise

    def fail_gap_report(self, report_id: str) -> Optional[ToolGapReport]:
        """Mark a gap report as trial_failed."""
        report = (
            self.session.query(ToolGapReport)
            .filter(ToolGapReport.report_id == report_id)
            .first()
        )
        if report is None:
            return None
        try:
            report.status = "trial_failed"
            report.updated_at = datetime.now()
            self._commit()
            self.session.refresh(report)
            logger.info("Gap report marked as trial_failed: %s", report_id)
            return report
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to mark gap report %s as trial_failed: %s", report_id, e)
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
            logger.info(
                "Fix proposal created: %s (tool=%s)", proposal.proposal_id, tool_id
            )
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
        """Update the status of a fix proposal, optionally attaching trial results."""
        proposal = (
            self.session.query(ToolFixProposal)
            .filter(ToolFixProposal.proposal_id == proposal_id)
            .first()
        )
        if proposal is None:
            return None
        try:
            proposal.status = new_status
            if trial_result is not None:
                proposal.trial_result = trial_result
            if new_status == "applied":
                proposal.applied_at = datetime.now()
            self._commit()
            self.session.refresh(proposal)
            logger.info(
                "Fix proposal transitioned: %s -> %s", proposal_id, new_status
            )
            return proposal
        except Exception as e:
            self.session.rollback()
            logger.error("Failed to transition fix proposal %s: %s", proposal_id, e)
            raise
