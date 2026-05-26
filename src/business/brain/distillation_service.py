"""
Distillation Service - Segment 沉淀 LLM 调用 + 状态机管理
"""

import json
import logging
from typing import Any, Optional

from src.business.brain.models import DistillationOutput, SegmentStatus, Zone
from src.utils.events import emit

logger = logging.getLogger(__name__)


P1_DISTILLATION_TOOL_SCHEMA = {
    "name": "distillation_output",
    "description": "输出对该 Segment 的多分区记忆沉淀结果",
    "input_schema": {
        "type": "object",
        "required": ["hot_zone", "persistent_zone"],
        "properties": {
            "hot_zone": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["content", "entry_type", "reason"],
                    "properties": {
                        "content": {"type": "string"},
                        "entry_type": {"type": "string", "enum": ["event", "insight"]},
                        "scope": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "persistent_zone": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["content", "reason"],
                    "properties": {
                        "content": {"type": "string"},
                        "scope": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
        },
    },
}


P2_DISTILLATION_TOOL_SCHEMA = {
    "name": "distillation_output",
    "description": "输出对该 Segment 的多分区记忆沉淀结果（含归档区）",
    "input_schema": {
        "type": "object",
        "required": ["hot_zone", "persistent_zone", "archive_zone"],
        "properties": {
            "hot_zone": P1_DISTILLATION_TOOL_SCHEMA["input_schema"]["properties"]["hot_zone"],
            "persistent_zone": P1_DISTILLATION_TOOL_SCHEMA["input_schema"]["properties"][
                "persistent_zone"
            ],
            "archive_zone": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["content", "reason"],
                    "properties": {
                        "content": {"type": "string"},
                        "reason": {"type": "string"},
                        "scope": {"type": "string"},
                    },
                },
            },
        },
    },
}


P4_DISTILLATION_TOOL_SCHEMA = {
    "name": "distillation_output",
    "description": "输出对该 Segment 的多分区记忆沉淀结果（含潜意识区和失败区）",
    "input_schema": {
        "type": "object",
        "required": [
            "hot_zone",
            "persistent_zone",
            "archive_zone",
            "subconscious_zone",
            "failure_zone",
        ],
        "properties": {
            "hot_zone": P1_DISTILLATION_TOOL_SCHEMA["input_schema"]["properties"]["hot_zone"],
            "persistent_zone": P1_DISTILLATION_TOOL_SCHEMA["input_schema"]["properties"][
                "persistent_zone"
            ],
            "archive_zone": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["content", "reason"],
                    "properties": {
                        "content": {"type": "string"},
                        "reason": {"type": "string"},
                        "scope": {"type": "string"},
                    },
                },
            },
            "subconscious_zone": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["content", "reason"],
                    "properties": {
                        "content": {"type": "string"},
                        "reason": {"type": "string"},
                        "scope": {"type": "string"},
                    },
                },
            },
            "failure_zone": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["content", "reason"],
                    "properties": {
                        "content": {"type": "string"},
                        "reason": {"type": "string"},
                        "scope": {"type": "string"},
                    },
                },
            },
        },
    },
}


SUBCONSCIOUS_DISTILLATION_TOOL_SCHEMA = {
    "name": "subconscious_distillation_output",
    "description": "输出跨 Segment 潜意识区沉淀结果",
    "input_schema": {
        "type": "object",
        "required": ["subconscious_zone"],
        "properties": {
            "subconscious_zone": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["content", "reason"],
                    "properties": {
                        "content": {"type": "string"},
                        "reason": {"type": "string"},
                        "scope": {"type": "string"},
                    },
                },
            },
        },
    },
}


class DistillationService:
    """Segment 沉淀服务 - 处理 pending segments 的蒸馏分析"""

    def __init__(self, repo=None, config=None, brain_repo=None):
        self._repo = repo or brain_repo
        self._config = config

    def _get_repo(self):
        if self._repo is None:
            from src.data.repos.brain_repository import BrainRepository

            self._repo = BrainRepository()
        return self._repo

    def _get_config(self):
        if self._config is None:
            from src.data.unified_config import get_unified_config

            self._config = get_unified_config()
        return self._config

    def handle_distillation_result(
        self,
        segment_id: str,
        output: DistillationOutput,
    ) -> dict:
        """Persist structured distillation output for an already locked segment."""
        repo = self._get_repo()
        segment = self._get_segment(repo, segment_id)
        if segment is None:
            return {"success": False, "status": "missing"}

        entries = self._entries_from_output(output, segment)
        if not entries:
            already_retried = bool(getattr(segment, "all_empty_retried", False))
            retry_count = int(getattr(segment, "retry_count", 0) or 0)
            max_retries = self._max_retries()
            if not already_retried:
                repo.transition_segment_status(
                    segment_id,
                    from_status=SegmentStatus.DISTILLING.value,
                    to_status=SegmentStatus.PENDING.value,
                    all_empty_retried=True,
                )
                return {"success": True, "status": "retry"}
            if retry_count >= max_retries:
                repo.transition_segment_status(
                    segment_id,
                    from_status=SegmentStatus.DISTILLING.value,
                    to_status=SegmentStatus.FAILED.value,
                )
                return {"success": False, "status": "failed"}
            self._retry_or_fail_segment(
                repo, segment, "Empty entries after retry in handle_distillation_result"
            )
            return {"success": False, "status": "failed"}

        created_ids = self._complete_segment_with_entries(repo, segment_id, entries)
        if len(created_ids) != len(entries):
            return {"success": False, "status": "transition_conflict", "entries": 0}
        self._emit_created_entries(entries, created_ids)
        return {"success": True, "status": "completed", "entries": len(entries)}

    def _get_segment(self, repo, segment_id: str):
        getter = getattr(repo, "get_segment_by_id", None) or getattr(repo, "get_segment")
        return getter(segment_id)

    def _max_retries(self) -> int:
        getter = getattr(self._get_config(), "get_brain_segment_max_distillation_retries", None)
        if getter is None:
            return 3
        try:
            return int(getter())
        except (TypeError, ValueError):
            return 3

    def _entries_from_output(self, output: DistillationOutput, segment) -> list[dict]:
        segment_id = getattr(segment, "segment_id", "")
        session_id = getattr(segment, "session_id", "")
        zone_specs = [
            (Zone.HOT.value, output.hot_zone),
            (Zone.PERSISTENT.value, output.persistent_zone),
            (Zone.ARCHIVE.value, output.archive_zone),
            (Zone.SUBCONSCIOUS.value, output.subconscious_zone),
            (Zone.FAILURE.value, output.failure_zone),
        ]
        entries: list[dict] = []
        for zone, items in zone_specs:
            for item in items:
                content = (getattr(item, "content", "") or "").strip()
                reason = (getattr(item, "reason", "") or "").strip()
                if not content or not reason:
                    continue
                entries.append(
                    {
                        "zone": zone,
                        "content": content,
                        "reason": reason,
                        "origin": "distillation",
                        "entry_type": getattr(item, "entry_type", None),
                        "scope": getattr(item, "scope", None),
                        "source_segment_id": segment_id,
                        "source_session_id": session_id,
                    }
                )
        return entries

    def distill_segment(self, segment_id: str, llm_client=None, phase: str = "p1") -> bool:
        """对单个 segment 执行沉淀。

        Args:
            segment_id: 要沉淀的 segment ID
            llm_client: LLM 客户端（可选，用于实际 LLM 调用）
            phase: 沉淀阶段 ("p1", "p2", "p4")

        Returns:
            True if distillation succeeded
        """
        repo = self._get_repo()

        # CAS: pending -> distilling
        acquired = repo.transition_segment(
            segment_id,
            from_status=SegmentStatus.PENDING.value,
            to_status=SegmentStatus.DISTILLING.value,
        )
        if not acquired:
            logger.info("Segment %s already being processed", segment_id)
            return False

        segment = repo.get_segment(segment_id)
        if segment is None:
            logger.error("Segment %s disappeared after CAS lock", segment_id)
            return False

        try:
            if llm_client is None:
                self._retry_or_fail_segment(repo, segment, "No LLM client available")
                return False

            # 获取 segment 对应的消息
            messages = self._get_segment_messages(segment)
            if not messages:
                logger.info("Segment %s has no messages, marking completed", segment_id)
                repo.transition_segment(
                    segment_id,
                    from_status=SegmentStatus.DISTILLING.value,
                    to_status=SegmentStatus.COMPLETED.value,
                )
                return True

            # 根据 phase 选择 schema
            tool_schema = self._get_tool_schema_for_phase(phase)

            # 调用 LLM 进行沉淀
            result = llm_client.chat_with_tools(
                messages=[
                    {"role": "system", "content": self._build_distillation_prompt(phase)},
                    *messages,
                ],
                tools=[tool_schema],
            )

            if result is None:
                all_empty_retried = getattr(segment, "all_empty_retried", False)
                if not all_empty_retried:
                    logger.info("Segment %s returned empty, retrying once", segment_id)
                    repo.transition_segment(
                        segment_id,
                        from_status=SegmentStatus.DISTILLING.value,
                        to_status=SegmentStatus.PENDING.value,
                        all_empty_retried=True,
                    )
                    return False
                logger.warning(
                    "Segment %s returned empty after retry, marking FAILED",
                    segment_id,
                )
                self._retry_or_fail_segment(repo, segment, "LLM returned empty result after retry")
                return False

            # 验证结构
            entries = self._validate_distillation_output(result, phase=phase)
            if entries is None:
                self._retry_or_fail_segment(
                    repo,
                    segment,
                    "Invalid distillation output structure",
                )
                return False
            if not entries:
                all_empty_retried = getattr(segment, "all_empty_retried", False)
                if not all_empty_retried:
                    repo.transition_segment(
                        segment_id,
                        from_status=SegmentStatus.DISTILLING.value,
                        to_status=SegmentStatus.PENDING.value,
                        all_empty_retried=True,
                    )
                    return False
                logger.warning(
                    "Segment %s has no entries after retry, marking FAILED",
                    segment_id,
                )
                self._retry_or_fail_segment(repo, segment, "No entries extracted after retry")
                return False

            # 事务写入：entries + segment completed
            session_id = getattr(segment, "session_id", "")
            entries_with_source = [
                {
                    **entry,
                    "source_segment_id": segment_id,
                    "source_session_id": session_id,
                }
                for entry in entries
            ]
            created_ids = self._complete_segment_with_entries(
                repo,
                segment_id,
                entries_with_source,
            )
            if len(created_ids) != len(entries_with_source):
                logger.warning("Segment %s completion conflicted after distillation", segment_id)
                return False

            self._emit_created_entries(entries_with_source, created_ids)
            logger.info(
                "Segment %s distilled successfully: %d entries (phase=%s)",
                segment_id,
                len(entries),
                phase,
            )
            return True

        except Exception as e:
            logger.error("Distillation failed for segment %s: %s", segment_id, e)
            self._retry_or_fail_segment(repo, segment, str(e))
            return False

    def _get_tool_schema_for_phase(self, phase: str) -> dict:
        """根据沉淀阶段选择对应的工具 schema。"""
        if phase == "p2":
            return P2_DISTILLATION_TOOL_SCHEMA
        if phase == "p4":
            return P4_DISTILLATION_TOOL_SCHEMA
        return P1_DISTILLATION_TOOL_SCHEMA

    def _get_segment_messages(self, segment) -> list[dict]:
        """获取 segment 覆盖范围内的消息"""
        from src.data.repositories import MessageRepository

        msg_start = getattr(segment, "message_id_start", None)
        msg_end = getattr(segment, "message_id_end", None)
        session_id = getattr(segment, "session_id", "")

        msg_repo = MessageRepository()
        try:
            messages = msg_repo.get_context(session_id)
        finally:
            msg_repo.close()
        messages = [
            msg
            for msg in messages
            if msg.role in {"user", "assistant"} and (msg.content or "").strip()
        ]
        if not msg_start or not msg_end:
            selected = messages
        else:
            start_seq = next((m.sequence for m in messages if m.message_id == msg_start), None)
            end_seq = next((m.sequence for m in messages if m.message_id == msg_end), None)
            if start_seq is None or end_seq is None:
                selected = messages
            else:
                selected = [m for m in messages if start_seq <= m.sequence <= end_seq]
        return [{"role": msg.role, "content": msg.content} for msg in selected]

    def _build_distillation_prompt(self, phase: str = "p1") -> str:
        base = (
            "你是一个记忆分析系统。分析以下对话内容，提取重要信息并分类到不同记忆分区。\n\n"
            "热区(hot_zone): 近期对话中的重要事件和洞察，每条必须有 entry_type ('event' 或 'insight')\n"
            "持久区(persistent_zone): 用户长期偏好、稳定事实、重要决策记录\n"
        )
        if phase in ("p2", "p4"):
            base += (
                "归档区(archive_zone): 对话中涉及但不太可能近期再参考的背景信息、"
                "已完成事件、非核心话题的讨论摘要\n"
            )
        if phase == "p4":
            base += (
                "潜意识区(subconscious_zone): 对话中隐含的模式、潜在需求、"
                "用户未明确表达但可推测的偏好\n"
                "失败区(failure_zone): 尝试失败的操作、被否决的方案、需要避免的做法\n"
            )
        base += (
            "\n每条记忆必须有:\n"
            "- content: 简洁的记忆内容\n"
            "- reason: 为什么这条记忆值得保留\n"
            "- scope (可选): 适用范围描述\n\n"
        )
        feedback_guidance = self._format_feedback_guidance()
        if feedback_guidance:
            base += "\n近期用户反馈信号：\n" + feedback_guidance + "\n\n"
        base += "请调用 distillation_output 工具输出结果。"
        return base

    def _format_feedback_guidance(self) -> str:
        try:
            signals = self._get_repo().get_recent_feedback_signals(limit=10)
        except Exception as exc:
            logger.warning("Failed to load feedback signals for distillation prompt: %s", exc)
            return ""
        lines = []
        for signal in signals:
            operation = getattr(signal, "operation", "")
            zone = getattr(signal, "zone", "")
            summary = getattr(signal, "context_summary", "")
            if not operation or not summary:
                continue
            lines.append(f"- [{zone}/{operation}] {summary}")
        return "\n".join(lines)

    def run_subconscious_distillation(self, llm_client=None) -> int:
        """Run periodic cross-segment distillation into the subconscious zone."""
        if llm_client is None:
            return 0
        context = self._build_subconscious_context()
        if not context:
            return 0
        response = llm_client.chat_with_tools(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是潜意识区沉淀器。基于跨 Segment 记忆，提取用户隐含的偏好、"
                        "价值观、风格或反感。条目是参考性判断，不是硬规则。"
                    ),
                },
                {"role": "user", "content": context},
            ],
            tools=[SUBCONSCIOUS_DISTILLATION_TOOL_SCHEMA],
        )
        items = self._subconscious_items_from_response(response)
        if not items:
            return 0
        repo = self._get_repo()
        created = 0
        for item in items:
            content = str(item.get("content", "") or "").strip()
            reason = str(item.get("reason", "") or "").strip()
            if not content or not reason:
                continue
            entry_id = repo.create_entry(
                zone=Zone.SUBCONSCIOUS.value,
                content=content,
                origin="subconscious_distillation",
                reason=reason,
                scope=item.get("scope"),
            )
            emit(
                "brain_zone_changed",
                zone=Zone.SUBCONSCIOUS.value,
                entry_id=str(entry_id),
                operation="create",
            )
            created += 1
        return created

    def _build_subconscious_context(self) -> str:
        try:
            grouped = self._get_repo().get_prediction_context_entries(
                hot_limit=20,
                persistent_limit=20,
                verified_limit=0,
            )
        except Exception as exc:
            logger.warning("Failed to load subconscious distillation context: %s", exc)
            return ""
        lines = []
        for zone in ("hot", "persistent"):
            for entry in grouped.get(zone, []):
                content = str(getattr(entry, "content", "") or "").strip()
                if content:
                    lines.append(f"[{zone}] {content}")
        feedback = self._format_feedback_guidance()
        if feedback:
            lines.append("近期用户反馈信号：")
            lines.append(feedback)
        return "\n".join(lines)

    @staticmethod
    def _subconscious_items_from_response(response: Any) -> list[dict]:
        for tool_call in DistillationService._tool_calls_from_result(response):
            name = getattr(tool_call, "name", None) or tool_call.get("name")
            if name != "subconscious_distillation_output":
                continue
            args = getattr(tool_call, "args", None) or tool_call.get("args", {})
            if not isinstance(args, dict):
                return []
            items = args.get("subconscious_zone", [])
            if not isinstance(items, list):
                return []
            return [item for item in items if isinstance(item, dict)]
        return []

    def _validate_distillation_output(self, result: Any, phase: str = "p1") -> Optional[list[dict]]:
        """验证沉淀输出结构。

        Args:
            result: LLM 返回的原始结果
            phase: 沉淀阶段 ("p1", "p2", "p4")
        """
        try:
            tool_calls = self._tool_calls_from_result(result)
            if not tool_calls:
                return None

            # 根据 phase 决定处理的 zone 列表
            if phase == "p2":
                zone_keys = ["hot_zone", "persistent_zone", "archive_zone"]
            elif phase == "p4":
                zone_keys = [
                    "hot_zone",
                    "persistent_zone",
                    "archive_zone",
                    "subconscious_zone",
                    "failure_zone",
                ]
            else:
                zone_keys = ["hot_zone", "persistent_zone"]
            active_zone_keys = set(zone_keys)
            all_zone_keys = {
                "hot_zone",
                "persistent_zone",
                "archive_zone",
                "subconscious_zone",
                "failure_zone",
                "prediction_zone",
            }

            for tc in tool_calls:
                name = getattr(tc, "name", None) or tc.get("name")
                if name == "distillation_output":
                    args = getattr(tc, "args", None) or tc.get("args", {})
                    if not isinstance(args, dict):
                        return None
                    if not active_zone_keys.issubset(args.keys()):
                        return None
                    if any(key in args for key in all_zone_keys - active_zone_keys):
                        logger.warning(
                            "Distillation output contains unexpected zone keys: %s, ignoring extra keys",
                            [k for k in args if k in (all_zone_keys - active_zone_keys)],
                        )
                    entries = []

                    for zone_key in zone_keys:
                        zone_items = args.get(zone_key, [])
                        if not isinstance(zone_items, list):
                            return None
                        for item in zone_items:
                            if not isinstance(item, dict):
                                return None
                            if not item.get("content") or not item.get("reason"):
                                return None
                            if zone_key == "hot_zone" and item.get("entry_type") not in {
                                "event",
                                "insight",
                            }:
                                return None
                            entry = {
                                "zone": zone_key.replace("_zone", ""),
                                "content": item["content"],
                                "reason": item["reason"],
                                "origin": "distillation",
                            }
                            if zone_key == "hot_zone" and item.get("entry_type"):
                                entry["entry_type"] = item["entry_type"]
                            if item.get("scope"):
                                entry["scope"] = item["scope"]
                            entries.append(entry)

                    return entries

            return None
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.error("Failed to validate distillation output: %s", e)
            return None

    @staticmethod
    def _tool_calls_from_result(result: Any) -> list:
        if result is None:
            return []
        if isinstance(result, dict):
            return result.get("tool_calls", []) or []
        return list(getattr(result, "tool_calls", []) or [])

    def _complete_segment_with_entries(
        self,
        repo,
        segment_id: str,
        entries: list[dict],
    ) -> list[str]:
        if hasattr(type(repo), "complete_segment_with_entries"):
            return repo.complete_segment_with_entries(segment_id, entries)
        # CAS first: if another worker already completed this segment, don't insert duplicate entries
        ok = repo.transition_segment_status(
            segment_id,
            from_status=SegmentStatus.DISTILLING.value,
            to_status=SegmentStatus.COMPLETED.value,
        )
        if not ok:
            logger.warning(
                "Segment %s CAS failed in fallback path, skipping entry creation", segment_id
            )
            return []
        try:
            repo.create_entries_for_segment(entries)
        except Exception:
            logger.error(
                "Segment %s entry creation failed after CAS, rolling back to DISTILLING",
                segment_id,
                exc_info=True,
            )
            repo.transition_segment_status(
                segment_id,
                from_status=SegmentStatus.COMPLETED.value,
                to_status=SegmentStatus.DISTILLING.value,
            )
            raise
        return [entry.get("entry_id", "") for entry in entries]

    @staticmethod
    def _emit_created_entries(entries: list[dict], entry_ids: list[str]) -> None:
        for entry, entry_id in zip(entries, entry_ids):
            emit(
                "brain_zone_changed",
                zone=str(entry.get("zone", "")),
                entry_id=str(entry_id),
                operation="create",
            )

    def _retry_or_fail_segment(self, repo, segment, reason: str) -> None:
        """Retry a failed distillation unit until the configured retry budget is exhausted."""
        segment_id = getattr(segment, "segment_id", "")
        retry_count = int(getattr(segment, "retry_count", 0) or 0)
        max_retries = self._max_retries()
        if retry_count + 1 >= max_retries:
            self._fail_segment(repo, segment_id, reason)
            return
        logger.warning("Segment %s retrying distillation after failure: %s", segment_id, reason)
        repo.retry_distilling_segment(segment_id)

    def _fail_segment(self, repo, segment_id: str, reason: str):
        """将 segment 标记为 failed"""
        logger.warning("Segment %s failed: %s", segment_id, reason)
        repo.transition_segment(
            segment_id,
            from_status=SegmentStatus.DISTILLING.value,
            to_status=SegmentStatus.FAILED.value,
        )
