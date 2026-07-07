"""Read-only source evidence packages for improvement proposal discussion.

The inspector is shared by the desktop API and the proposal discussion agent
tool.  It returns deterministic evidence and anchors only; interpretation stays
in the discussion itself.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.business.self_improvement.execution_trace_builder import build_skeleton
from src.business.services.ui_event_safety_service import redact_public_ui_event_text
from src.data.repos.execution_review_repository import ExecutionReviewRepository
from src.data.repos.improvement_proposal_repository import ImprovementProposalRepository
from src.data.repositories import MessageRepository


class ProposalSourceError(RuntimeError):
    """Base class for source inspection errors."""


class ProposalSourceNotFound(ProposalSourceError):
    """Proposal or requested source row does not exist."""


class ProposalSourceForbidden(ProposalSourceError):
    """The caller session is not bound to the requested proposal discussion."""


class ProposalSourceInvalidView(ProposalSourceError):
    """Unsupported source inspection view."""


_SUPPORTED_VIEWS = frozenset({"overview", "messages"})
_MAX_OVERVIEW_EVIDENCE = 5
_MESSAGE_LIMIT_MAX = 50
_MESSAGE_LIMIT_DEFAULT = 20
_USER_ASSISTANT_PREVIEW_CHARS = 1200
_TOOL_PREVIEW_CHARS = 500
_EVIDENCE_PREVIEW_CHARS = 700


def _parse_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _safe_text(value: Any, *, max_chars: int) -> tuple[str, bool]:
    raw = "" if value is None else str(value)
    redacted = redact_public_ui_event_text(
        "text",
        raw,
        max_preview_chars=min(max_chars, 1200),
        max_len=max_chars,
    )
    text = str(redacted or "")
    return text, len(raw) > max_chars


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return _MESSAGE_LIMIT_DEFAULT
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        return _MESSAGE_LIMIT_DEFAULT
    return max(1, min(_MESSAGE_LIMIT_MAX, parsed))


def _cursor_sequence(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0


def _proposal_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "sourceReviewId": row.source_review_id,
        "findingIndex": row.finding_index,
        "status": row.status,
        "severity": row.severity,
        "findingType": row.finding_type,
        "what": row.what,
        "evidence": row.evidence,
        "suggestion": row.suggestion,
        "discussionSessionId": row.discussion_session_id,
        "createdAt": row.created_at,
    }


def _review_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    findings = _parse_json(row.findings_json, [])
    if not isinstance(findings, list):
        findings = []
    return {
        "id": row.id,
        "turnSessionId": row.turn_session_id,
        "status": row.status,
        "verdict": row.verdict or "",
        "findings": [item for item in findings if isinstance(item, dict)],
        "modelUsed": row.model_used or "",
        "createdAt": row.created_at,
        "reviewedAt": row.reviewed_at,
        "error": row.error,
    }


def _anchor(**kwargs: Any) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if value is not None}


def _message_to_item(message: Any, *, include_content: bool = True) -> dict[str, Any]:
    role = str(getattr(message, "role", "") or "")
    cap = _TOOL_PREVIEW_CHARS if role == "tool" else _USER_ASSISTANT_PREVIEW_CHARS
    excerpt, truncated = _safe_text(
        getattr(message, "content", "") if include_content else "",
        max_chars=cap,
    )
    return {
        "kind": "message",
        "messageId": getattr(message, "message_id", None),
        "sessionId": getattr(message, "session_id", None),
        "sequence": getattr(message, "sequence", None),
        "role": role,
        "toolName": getattr(message, "tool_name", None),
        "excerpt": excerpt,
        "truncated": truncated,
        "createdAt": _iso(getattr(message, "created_at", None)),
        "anchor": _anchor(
            sessionId=getattr(message, "session_id", None),
            messageId=getattr(message, "message_id", None),
            sequence=getattr(message, "sequence", None),
        ),
    }


def _evidence_item(
    *,
    item_id: str,
    kind: str,
    label: str,
    excerpt: Any,
    anchor: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    safe_excerpt, truncated = _safe_text(excerpt, max_chars=_EVIDENCE_PREVIEW_CHARS)
    return {
        "id": item_id,
        "kind": kind,
        "label": label,
        "excerpt": safe_excerpt,
        "truncated": truncated,
        "anchor": anchor,
        "reason": reason,
    }


def _terms_from(*values: Any) -> list[str]:
    terms: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if len(text) <= 80:
            terms.append(text)
        for part in re.split(r"[\s,，。；;：:\n\r]+", text):
            part = part.strip()
            if len(part) >= 4:
                terms.append(part)
    deduped: list[str] = []
    for term in terms:
        lowered = term.lower()
        if lowered not in {item.lower() for item in deduped}:
            deduped.append(term)
    return deduped[:12]


def _matching_messages(messages: list[Any], terms: list[str], *, limit: int) -> list[Any]:
    if not terms:
        return []
    result: list[Any] = []
    seen: set[str] = set()
    for message in reversed(messages):
        content = str(getattr(message, "content", "") or "")
        lowered = content.lower()
        if any(term.lower() in lowered for term in terms):
            msg_id = str(getattr(message, "message_id", ""))
            if msg_id and msg_id not in seen:
                seen.add(msg_id)
                result.append(message)
        if len(result) >= limit:
            break
    return list(reversed(result))


def _latest_message(messages: list[Any], role: str, *, after_sequence: int | None = None) -> Any | None:
    for message in reversed(messages):
        if str(getattr(message, "role", "") or "") != role:
            continue
        if after_sequence is not None and int(getattr(message, "sequence", 0) or 0) < after_sequence:
            continue
        return message
    return None


def _tool_evidence_from_skeleton(skeleton: dict[str, Any], *, session_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    steps = skeleton.get("steps") if isinstance(skeleton, dict) else []
    if not isinstance(steps, list):
        return items
    interesting = [
        step
        for step in steps
        if isinstance(step, dict)
        and (step.get("ok") is False or int(step.get("result_size") or 0) > 2000 or step.get("output_ref"))
    ]
    if not interesting:
        interesting = [step for step in steps if isinstance(step, dict)][-2:]
    for index, step in enumerate(interesting[:2]):
        tool = str(step.get("tool") or "?")
        size = int(step.get("result_size") or 0)
        ok = bool(step.get("ok"))
        output_ref = step.get("output_ref")
        summary = f"工具 {tool} {'成功' if ok else '失败'}，结果约 {size} 字符。"
        if output_ref:
            summary += f" 大输出引用：{output_ref}。"
        items.append(
            _evidence_item(
                item_id=f"tool_step_{index}",
                kind="tool_call_summary",
                label=f"工具调用：{tool}",
                excerpt=summary,
                anchor=_anchor(
                    sessionId=session_id,
                    stepIndex=step.get("index"),
                    toolName=tool,
                    outputRef=output_ref,
                ),
                reason="复盘输入 skeleton 中的工具调用节点",
            )
        )
    return items


class ProposalSourceInspector:
    """Build deterministic source evidence packages for improvement proposals."""

    def bound_proposal_id_for_session(self, session_id: str) -> str | None:
        with ImprovementProposalRepository() as repo:
            row = repo.get_by_discussion_session(session_id)
            return row.id if row is not None else None

    def inspect(
        self,
        proposal_id: str | None,
        *,
        view: str = "overview",
        cursor: str | None = None,
        limit: int | None = None,
        discussion_session_id: str | None = None,
        enforce_discussion: bool = False,
    ) -> dict[str, Any]:
        selected_view = (view or "overview").strip() or "overview"
        if selected_view not in _SUPPORTED_VIEWS:
            raise ProposalSourceInvalidView(selected_view)

        resolved_proposal_id = proposal_id
        if not resolved_proposal_id and discussion_session_id:
            resolved_proposal_id = self.bound_proposal_id_for_session(discussion_session_id)
        if not resolved_proposal_id:
            raise ProposalSourceNotFound("proposal not found")

        with ImprovementProposalRepository() as proposal_repo:
            row = proposal_repo.get_by_id(resolved_proposal_id)
            if row is None:
                raise ProposalSourceNotFound("proposal not found")
            proposal = _proposal_dict(row)

        if enforce_discussion and proposal.get("discussionSessionId") != discussion_session_id:
            raise ProposalSourceForbidden("session is not bound to this proposal discussion")

        review = self._load_review(proposal["sourceReviewId"])
        if selected_view == "messages":
            return self._messages_package(proposal, review, cursor=cursor, limit=limit)
        return self._overview_package(proposal, review)

    def _load_review(self, review_id: str) -> dict[str, Any] | None:
        with ExecutionReviewRepository() as repo:
            row = repo.get_by_id(review_id)
            return _review_dict(row)

    def _overview_package(
        self,
        proposal: dict[str, Any],
        review: dict[str, Any] | None,
    ) -> dict[str, Any]:
        messages: list[Any] = []
        skeleton: dict[str, Any] = {}
        turn_session_id = review.get("turnSessionId") if review else None
        if turn_session_id:
            with MessageRepository() as message_repo:
                messages = message_repo.get_all(str(turn_session_id))
                skeleton = build_skeleton(str(turn_session_id), message_repo)

        evidence: list[dict[str, Any]] = []
        finding_text = "\n".join(
            part
            for part in (proposal.get("what"), proposal.get("evidence"), proposal.get("suggestion"))
            if part
        )
        if finding_text:
            evidence.append(
                _evidence_item(
                    item_id="proposal_finding",
                    kind="review_finding",
                    label="当前 finding",
                    excerpt=finding_text,
                    anchor=_anchor(
                        sourceReviewId=proposal.get("sourceReviewId"),
                        findingIndex=proposal.get("findingIndex"),
                    ),
                    reason="提案直接来自这条复盘 finding",
                )
            )
        if review and review.get("verdict"):
            evidence.append(
                _evidence_item(
                    item_id="review_verdict",
                    kind="review_summary",
                    label="复盘结论",
                    excerpt=review.get("verdict"),
                    anchor=_anchor(sourceReviewId=review.get("id")),
                    reason="执行复盘写回的总体判断",
                )
            )

        terms = _terms_from(proposal.get("what"), proposal.get("evidence"), proposal.get("suggestion"))
        for index, message in enumerate(_matching_messages(messages, terms, limit=2)):
            item = _message_to_item(message)
            evidence.append(
                _evidence_item(
                    item_id=f"matched_message_{index}",
                    kind=f"{item['role']}_message",
                    label=f"命中原始消息 #{item['sequence']}",
                    excerpt=item["excerpt"],
                    anchor=item["anchor"],
                    reason="消息内容命中了当前 finding 的问题、证据或建议文本",
                )
            )

        latest_user = _latest_message(messages, "user")
        latest_user_seq = int(getattr(latest_user, "sequence", 0) or 0) if latest_user else None
        latest_assistant = _latest_message(messages, "assistant", after_sequence=latest_user_seq)
        for label, role, message in (
            ("最近用户消息", "user_message", latest_user),
            ("最近助理回复", "assistant_message", latest_assistant),
        ):
            if message is None:
                continue
            item = _message_to_item(message)
            if any(existing.get("anchor", {}).get("messageId") == item["messageId"] for existing in evidence):
                continue
            evidence.append(
                _evidence_item(
                    item_id=f"tail_{role}_{item['sequence']}",
                    kind=role,
                    label=label,
                    excerpt=item["excerpt"],
                    anchor=item["anchor"],
                    reason="未找到精确消息范围时，用复盘会话尾部辅助定位",
                )
            )

        evidence.extend(_tool_evidence_from_skeleton(skeleton, session_id=str(turn_session_id or "")))

        current_finding = None
        if review:
            findings = review.get("findings") or []
            index = int(proposal.get("findingIndex") or 0)
            if isinstance(findings, list) and 0 <= index < len(findings):
                current_finding = findings[index]

        return {
            "proposalId": proposal["id"],
            "view": "overview",
            "scope": "session_tail",
            "scopeNote": "第一版未存精确消息范围，以下为复盘会话尾部、文本命中和 skeleton 异常片段。",
            "proposal": proposal,
            "source": {
                "sourceReviewId": proposal.get("sourceReviewId"),
                "findingIndex": proposal.get("findingIndex"),
                "turnSessionId": turn_session_id,
                "reviewStatus": review.get("status") if review else None,
                "reviewedAt": review.get("reviewedAt") if review else None,
                "createdAt": review.get("createdAt") if review else None,
                "modelUsed": review.get("modelUsed") if review else None,
                "available": review is not None,
            },
            "review": {
                "verdict": review.get("verdict") if review else "",
                "currentFinding": current_finding,
                "findingCount": len(review.get("findings") or []) if review else 0,
            },
            "evidence": evidence[:_MAX_OVERVIEW_EVIDENCE],
            "nextActions": [
                {
                    "view": "messages",
                    "label": "查看原始消息片段",
                    "description": "分页读取来源会话的用户、助理和工具消息预览。",
                }
            ],
        }

    def _messages_package(
        self,
        proposal: dict[str, Any],
        review: dict[str, Any] | None,
        *,
        cursor: str | None,
        limit: int | None,
    ) -> dict[str, Any]:
        turn_session_id = review.get("turnSessionId") if review else None
        after = _cursor_sequence(cursor)
        count = _clamp_limit(limit)
        messages: list[Any] = []
        if turn_session_id:
            with MessageRepository() as message_repo:
                messages = [
                    message
                    for message in message_repo.get_all(str(turn_session_id))
                    if int(getattr(message, "sequence", 0) or 0) > after
                ]
        page = messages[:count]
        has_more = len(messages) > count
        next_cursor = str(getattr(page[-1], "sequence", "")) if has_more and page else None
        return {
            "proposalId": proposal["id"],
            "view": "messages",
            "scope": "session_messages",
            "proposal": {
                "id": proposal["id"],
                "sourceReviewId": proposal.get("sourceReviewId"),
                "findingIndex": proposal.get("findingIndex"),
                "what": proposal.get("what"),
            },
            "source": {
                "sourceReviewId": proposal.get("sourceReviewId"),
                "turnSessionId": turn_session_id,
                "available": review is not None and bool(turn_session_id),
            },
            "items": [_message_to_item(message) for message in page],
            "page": {
                "cursor": cursor,
                "nextCursor": next_cursor,
                "limit": count,
                "hasMore": has_more,
            },
        }
