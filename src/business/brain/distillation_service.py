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


# P3 只增加归档分层任务，不改变 LLM 沉淀输出 schema；P4 才扩展新分区。
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
            if messages is None:
                # 边界 ID 缺失或消息已被清除，不能静默完成
                self._retry_or_fail_segment(repo, segment, "segment message boundary unresolvable")
                return False
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
                self._retry_or_fail_segment(repo, segment, "Completion CAS conflict")
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

    def _get_segment_messages(self, segment) -> list[dict] | None:
        """获取 segment 覆盖范围内的消息"""
        from src.data.repos.message_repository import MessageRepository

        msg_start = getattr(segment, "message_id_start", None)
        msg_end = getattr(segment, "message_id_end", None)
        session_id = getattr(segment, "session_id", "")

        msg_repo = MessageRepository()
        try:
            all_messages = msg_repo.get_context(session_id)
        finally:
            msg_repo.close()

        if msg_start is None or msg_end is None:
            return None  # 边界 ID 缺失是数据错误，应走 retry/fail 而非静默 COMPLETED

        # 边界序号查找必须在内容过滤之前执行，避免空内容边界消息（如纯工具调用轮次）被过滤掉
        start_seq = next((m.sequence for m in all_messages if m.message_id == msg_start), None)
        end_seq = next((m.sequence for m in all_messages if m.message_id == msg_end), None)
        if start_seq is None or end_seq is None:
            return None  # 边界消息已被清除，同上

        selected = [m for m in all_messages if start_seq <= m.sequence <= end_seq]
        return [
            {"role": msg.role, "content": msg.content}
            for msg in selected
            if msg.role in {"user", "assistant"} and (msg.content or "").strip()
        ]

    def _build_distillation_prompt(self, phase: str = "p1") -> str:
        base = (
            "你是记忆提取器。从这段对话中筛选值得长期保存的记忆，供助理未来快速理解用户和项目。\n\n"
            "## 怎么判断该不该记\n"
            "对每个候选信息，问自己：如果三周后的对话需要用到这条信息，助理不看它会怎样？\n"
            "- 会做出错误决策或重复踩坑 → 必须记\n"
            "- 会多问用户一轮才能继续 → 值得记\n"
            "- 完全没影响 → 不记\n\n"
            "## 质量标准\n"
            "1. **自包含**：脱离这段对话也能理解\n"
            "   ✓「用户选择 DuckDB 替换 SQLite 做分析存储，因为需要列式查询性能」\n"
            "   ✗「用户决定换数据库」（换什么？为什么？）\n"
            "   ✗「用户在讨论数据库时提到了 DuckDB」（这不是记忆，是描述）\n"
            "2. **一条一事**：每个 content 只说一个事实或判断\n"
            "3. **宁缺毋滥**：不确定该不该记的，不记。提取 0 条完全没问题\n\n"
            "## 常见错误（避免）\n"
            "- 把对话过程当记忆：「用户和助理讨论了数据库选型」← 这是聊天记录摘要\n"
            "- 把通用知识当记忆：「FastAPI 是一个 Python Web 框架」← 用户没表达偏好\n"
            "- 把宽泛印象当记忆：「用户很注重代码质量」← 没有具体行为支撑\n"
            "- 把一次性事件当持久特征：「用户今天想用 Redis」← 单次提及不算稳定偏好\n\n"
            "## 分区规则\n"
            "### hot_zone（热区）\n"
            "判断问题：这条信息在接下来几次对话中会不会被用到？\n"
            "本轮对话产生的决策、发现、结论。每条标 entry_type：event（发生了什么）或 insight（发现了什么）。\n"
            "✓ event:「用户决定搁置 feature X，先修 Y 的性能问题——因为 Y 影响线上用户」\n"
            "✓ insight:「用户对并发性能的要求高于代码简洁性——从多次技术取舍中观察到」\n\n"
            "### persistent_zone（持久区）\n"
            "判断问题：如果用户两周后回来，这条信息还成立吗？\n"
            "用户的稳定偏好、技术栈、工作方式、长期目标。必须有依据（明确说过、或多次体现）。\n"
            "✓「用户偏好 immutable 数据模式——三次代码评审中都要求改成不可变写法」\n"
            "✓「项目技术栈：Python 3.11 + FastAPI + DuckDB + React」\n"
        )
        if phase in ("p2", "p4"):
            base += (
                "\n### archive_zone（归档区）\n"
                "判断问题：这条信息有历史价值，但未来对话大概率用不到？\n"
                "已完成的任务细节、一次性调试过程、已被新方案覆盖的旧决定。存着以防万一，但不会被主动检索。\n"
                "✓「v10 migration 把 assistant_run_failures 从 memory 表拆到独立表」\n"
                "✓「调试 DuckDB 并发写死锁花了两小时，最终改成串行写入」\n"
            )
        if phase == "p4":
            base += (
                "\n### subconscious_zone（潜意识区）\n"
                "判断问题：用户是不是在类似场景下反复做出相同选择？\n"
                "跨对话的行为模式——决策倾向、隐含优先级、工作习惯。**至少两条不同对话的证据**。\n"
                "✓「性能 vs 可读性冲突时倾向先选可读性，瓶颈明确才优化——三次技术讨论中的选择一致」\n"
                "✓「对「能跑就行」的方案会主动要求重构——两次 code review 中都追加了改进任务」\n\n"
                "### failure_zone（失败区）\n"
                "判断问题：记住这次失败能避免以后重蹈覆辙吗？\n"
                "失败操作、被否方案、走不通的路径。**必须含失败原因**，否则没有检索价值。\n"
                "✓「asyncio.gather 并发写 DuckDB 导致死锁——DuckDB 写锁不支持并发写入」\n"
                "✗「数据库迁移失败」← 失败原因是什么？哪个库？什么场景？\n"
            )
        base += (
            "\n## 输出\n"
            "每条记忆需 content + reason。\n"
            "reason 应回答：「什么场景下助理需要这条记忆？」（如：讨论数据库选型时、处理并发写入时）\n"
            "scope 可选（适用上下文，如模块名、技术领域）。\n"
        )
        feedback_guidance = self._format_feedback_guidance()
        if feedback_guidance:
            base += "\n近期用户反馈信号（参考，不要逐条转为记忆）\n" + feedback_guidance + "\n"
        base += "\n调用 distillation_output 输出。没有值得提取的，所有分区留空数组——这完全正常，不要为了填满而提取。"
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
        """Run periodic cross-segment distillation into the subconscious zone.

        段身份去重：以"最近完成且仍有 active hot/persistent 条目的 Segment"为输入标记，与上
        一次潜意识输出记录的段标记比较；相同即说明没有新的可消费蒸馏材料，跳过本轮沉淀，避免
        后台 worker 每个 tick 对同一段记忆重复抽取潜意识条目、浪费 LLM 调用。
        """
        if llm_client is None:
            return 0
        repo = self._get_repo()
        latest_segment = repo.get_latest_distilled_segment_id()
        if latest_segment is not None:
            last_marker = repo.get_latest_output_segment_marker(
                "subconscious", "subconscious_distillation"
            )
            if last_marker == latest_segment:
                logger.info(
                    "Subconscious distillation skipped: segment %s already processed",
                    latest_segment,
                )
                return 0
        context = self._build_subconscious_context()
        if not context:
            return 0
        response = llm_client.chat_with_tools(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "从记忆条目中发现用户反复出现的行为模式。这些模式要能让助理预判用户在类似场景下的反应。\n\n"
                        "## 怎么判断是不是模式\n"
                        "问自己：这个行为出现过几次？如果只见过一次，那只是事件，不是模式。\n"
                        "真正的模式是：类似情境下，用户做出了相同或相似的选择，且次数 ≥ 2。\n\n"
                        "## 值得提取的模式\n"
                        "- 反复出现的决策倾向（类似情境多次相同选择）\n"
                        "- 隐含的优先级排序（行为体现但未明说）\n"
                        "- 未明说的工作习惯\n"
                        "- 对特定技术/方式的持续倾向或回避\n\n"
                        "✓「性能 vs 可读性冲突时倾向先选可读性，瓶颈明确才优化——三次技术讨论中的选择一致」\n"
                        "✓「对「能跑就行」的方案会主动要求重构——两次 code review 中都追加了改进任务」\n"
                        "✓「遇到 bug 先写测试复现再修，不直接改代码——四次 bugfix 流程一致」\n\n"
                        "## 不提取\n"
                        "- 只出现过一次的行为（至少两条不同对话的证据）\n"
                        "- 用户明确说过的偏好（那属于持久区，不是潜意识）\n"
                        "- 泛泛的人格判断（「用户很注重质量」← 没有具体行为支撑）\n"
                        "- 对话过程描述（「用户经常讨论技术方案」← 这不是模式）\n\n"
                        "## 输出\n"
                        "- content: 具体模式 + 支撑证据摘要，让助理能预判用户反应\n"
                        "- reason: 引用支撑判断的记忆来源（哪几条记忆构成了这个模式）\n"
                        "- 2-5 条为佳，没有就留空——不要为了填满而提取"
                    ),
                },
                {"role": "user", "content": context},
            ],
            tools=[SUBCONSCIOUS_DISTILLATION_TOOL_SCHEMA],
        )
        items = self._subconscious_items_from_response(response)
        if not items:
            return 0
        created = 0
        created_entry_ids: list[str] = []
        try:
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
                    source_segment_id=latest_segment,
                    commit=False,
                )
                created_entry_ids.append(str(entry_id))
                created += 1
            repo.session.commit()
        except Exception:
            repo.session.rollback()
            raise

        for entry_id in created_entry_ids:
            emit(
                "brain_zone_changed",
                zone=Zone.SUBCONSCIOUS.value,
                entry_id=entry_id,
                operation="create",
            )
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
                return self._invalid_distillation_output("missing tool_calls", result)

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
                        return self._invalid_distillation_output("tool args is not object", result)
                    if not active_zone_keys.issubset(args.keys()):
                        return self._invalid_distillation_output(
                            "missing required zone keys",
                            result,
                        )
                    if any(key in args for key in all_zone_keys - active_zone_keys):
                        logger.warning(
                            "Distillation output contains unexpected zone keys: %s, ignoring extra keys",
                            [k for k in args if k in (all_zone_keys - active_zone_keys)],
                        )
                    entries = []

                    for zone_key in zone_keys:
                        zone_items = args.get(zone_key, [])
                        if not isinstance(zone_items, list):
                            return self._invalid_distillation_output(
                                f"{zone_key} is not a list",
                                result,
                            )
                        for item in zone_items:
                            if not isinstance(item, dict):
                                return self._invalid_distillation_output(
                                    f"{zone_key} item is not object",
                                    result,
                                )
                            if not item.get("content") or not item.get("reason"):
                                return self._invalid_distillation_output(
                                    f"{zone_key} item missing content or reason",
                                    result,
                                )
                            if zone_key == "hot_zone" and item.get("entry_type") not in {
                                "event",
                                "insight",
                            }:
                                return self._invalid_distillation_output(
                                    "hot_zone item has invalid entry_type",
                                    result,
                                )
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

            return self._invalid_distillation_output("missing distillation_output call", result)
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.error(
                "Failed to validate distillation output: %s raw_sample=%s",
                e,
                self._distillation_output_sample(result),
            )
            return None

    @staticmethod
    def _tool_calls_from_result(result: Any) -> list:
        if result is None:
            return []
        if isinstance(result, dict):
            return result.get("tool_calls", []) or []
        return list(getattr(result, "tool_calls", []) or [])

    def _invalid_distillation_output(self, reason: str, result: Any) -> Optional[list[dict]]:
        logger.warning(
            "Invalid distillation output: %s raw_sample=%s",
            reason,
            self._distillation_output_sample(result),
        )
        return None

    @staticmethod
    def _distillation_output_sample(result: Any, *, max_chars: int = 1200) -> str:
        try:
            if isinstance(result, dict):
                serializable = result
            else:
                serializable = {
                    "type": type(result).__name__,
                    "content": getattr(result, "content", None),
                    "tool_calls": getattr(result, "tool_calls", None),
                }
            sample = json.dumps(serializable, ensure_ascii=False, default=str)
        except Exception:
            sample = repr(result)
        if len(sample) > max_chars:
            return sample[:max_chars] + "...<truncated>"
        return sample

    def _complete_segment_with_entries(
        self,
        repo,
        segment_id: str,
        entries: list[dict],
    ) -> list[str]:
        if hasattr(type(repo), "complete_segment_with_entries"):
            return repo.complete_segment_with_entries(segment_id, entries)
        raise TypeError("Atomic segment completion requires repo.complete_segment_with_entries")

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
