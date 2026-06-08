"""
Prediction Service - 猜测生成与验证服务
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from src.business.agents.tool_helpers import make_tool_schema
from src.utils.events import emit

logger = logging.getLogger(__name__)


PREDICTION_GENERATION_OUTPUT_SCHEMA = make_tool_schema(
    name="prediction_generation_output",
    description="输出可验证的猜测区条目",
    properties={
        "prediction_zone": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["content", "verification_checkpoint", "reason"],
                "properties": {
                    "content": {"type": "string"},
                    "verification_checkpoint": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
    required=["prediction_zone"],
)


class PredictionService:
    """猜测生成与验证服务。"""

    def __init__(self, repo=None, config=None):
        self._repo = repo
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

    def generate_predictions(self, llm_client=None) -> list[str]:
        """基于跨 Segment 上下文生成猜测区条目。无 LLM 时静默 no-op。

        段身份去重：以"最近完成且仍有 active hot/persistent 条目的 Segment"为输入标记，与上
        一次猜测输出记录的段标记比较；相同即说明没有新的可消费蒸馏材料，跳过本轮生成，避免后台
        worker 每个 tick 对同一段记忆重复生成猜测、浪费 LLM 调用。
        """
        if llm_client is None:
            return []

        repo = self._get_repo()
        latest_segment = repo.get_latest_distilled_segment_id()
        if latest_segment is not None:
            last_marker = repo.get_latest_output_segment_marker(
                "prediction", "prediction_generation"
            )
            if last_marker == latest_segment:
                logger.info(
                    "Prediction generation skipped: segment %s already processed",
                    latest_segment,
                )
                return []

        context = self._collect_prediction_context()
        if not context:
            return []

        try:
            response = llm_client.chat_with_tools(
                messages=[
                    {"role": "system", "content": self._build_prediction_prompt()},
                    {"role": "user", "content": context},
                ],
                tools=[PREDICTION_GENERATION_OUTPUT_SCHEMA],
            )
        except Exception as exc:
            logger.error("Prediction generation failed: %s", exc)
            return []

        prediction_items = self._prediction_items_from_response(response)
        created_ids: list[str] = []
        for item in prediction_items:
            content = (item.get("content") or "").strip()
            reason = (item.get("reason") or "").strip()
            checkpoint = (item.get("verification_checkpoint") or "").strip()
            if not content or not reason or not checkpoint:
                continue
            entry_id = repo.create_prediction_entry(
                content=content,
                reason=reason,
                verification_checkpoint=checkpoint,
                source_segment_id=latest_segment,
            )
            created_ids.append(entry_id)
            emit(
                "brain_zone_changed", zone="prediction", entry_id=str(entry_id), operation="create"
            )
        return created_ids

    def verify_predictions(self, llm_client=None) -> int:
        """验证到期的猜测条目。无 LLM 时静默 no-op。"""
        if llm_client is None:
            return 0

        repo = self._get_repo()
        verified_count = 0
        for entry in repo.get_pending_prediction_entries():
            if not self._is_checkpoint_due(getattr(entry, "verification_checkpoint", "")):
                continue
            try:
                evidence = self._verification_evidence(entry)
                status, rationale = self._verify_single(
                    llm_client,
                    getattr(entry, "content", ""),
                    getattr(entry, "verification_checkpoint", ""),
                    evidence,
                )
                if status and repo.update_prediction_verification(
                    getattr(entry, "entry_id", ""),
                    status,
                    rationale,
                ):
                    emit(
                        "brain_zone_changed",
                        zone="prediction",
                        entry_id=getattr(entry, "entry_id", ""),
                        operation="verify",
                    )
                    verified_count += 1
            except Exception as exc:
                entry_id = getattr(entry, "entry_id", "")
                logger.error("Verification failed for %s: %s", entry_id, exc)
                if self._record_failed_attempt_or_expire(entry, str(exc)):
                    verified_count += 1
        return verified_count

    def _collect_prediction_context(self) -> str:
        """收集跨 Segment 的近期上下文。"""
        repo = self._get_repo()
        grouped = repo.get_prediction_context_entries()
        parts: list[str] = []
        for entry in grouped.get("hot", []):
            parts.append(f"[热区] {getattr(entry, 'content', '')}")
        for entry in grouped.get("persistent", []):
            parts.append(f"[持久] {getattr(entry, 'content', '')}")
        for entry in grouped.get("verified_predictions", []):
            parts.append(
                f"[已验证猜测:{getattr(entry, 'verification_status', '')}] "
                f"{getattr(entry, 'content', '')}"
            )
        return "\n".join(part for part in parts if part.strip())

    def _build_prediction_prompt(self) -> str:
        return (
            "基于以下记忆条目，生成 1-3 个关于用户未来可能行为的可验证猜测。\n\n"
            "每个猜测必须包含 content、verification_checkpoint、reason。\n"
            "猜测必须能在未来某个对话或时间点被验证，不要生成无法验证的人格判断。\n"
            "请调用 prediction_generation_output 工具输出结果。"
        )

    def _prediction_items_from_response(self, response: Any) -> list[dict]:
        tool_calls = self._tool_calls_from_response(response)
        for tool_call in tool_calls:
            name = getattr(tool_call, "name", None) or tool_call.get("name")
            if name != "prediction_generation_output":
                continue
            args = getattr(tool_call, "args", None) or tool_call.get("args", {})
            items = args.get("prediction_zone", []) if isinstance(args, dict) else []
            return [item for item in items if isinstance(item, dict)]
        return []

    @staticmethod
    def _tool_calls_from_response(response: Any) -> list:
        if response is None:
            return []
        if isinstance(response, dict):
            return response.get("tool_calls", []) or []
        return list(getattr(response, "tool_calls", []) or [])

    def _verify_single(
        self,
        llm_client,
        content: str,
        checkpoint: str,
        evidence: str = "",
    ) -> tuple[Optional[str], str]:
        prompt = (
            "以下是一个关于用户行为的猜测，请判断其是否已验证。\n\n"
            f"猜测：{content}\n"
            f"验证点：{checkpoint}\n\n"
            "验证期内已沉淀的记忆证据：\n"
            f"{evidence or '（没有相关记忆证据）'}\n\n"
            "请以 hit、miss、partial 或 expired 开头，并在后面给出一句理由。"
        )
        response = llm_client.chat(prompt)
        text = str(response or "").strip()
        lowered = text.lower()
        if lowered.startswith("hit"):
            return "hit", text
        if lowered.startswith("partial"):
            return "partial", text
        if lowered.startswith("miss"):
            return "miss", text
        if lowered.startswith("expired"):
            return "expired", text
        raise ValueError(f"unrecognized verification response: {text[:120]}")

    def _verification_evidence(self, prediction_entry) -> str:
        try:
            entries = self._get_repo().get_entries_for_prediction_verification(prediction_entry)
        except Exception as exc:
            logger.warning("Failed to load prediction verification evidence: %s", exc)
            return ""
        lines = []
        for entry in entries:
            content = str(getattr(entry, "content", "") or "").strip()
            if not content:
                continue
            zone = getattr(entry, "zone", "")
            created_at = getattr(entry, "created_at", "")
            lines.append(f"- [{zone} {created_at}] {content}")
        return "\n".join(lines[:50])

    def _record_failed_attempt_or_expire(self, entry, reason: str) -> bool:
        repo = self._get_repo()
        entry_id = getattr(entry, "entry_id", "")
        attempts = repo.count_prediction_verification_failures(entry_id)
        max_retries = self._verification_retry_limit()
        if attempts + 1 >= max_retries:
            updated = repo.update_prediction_verification(
                entry_id,
                "expired",
                "verification call failed — could not be assessed",
            )
            if updated:
                emit("brain_zone_changed", zone="prediction", entry_id=entry_id, operation="verify")
            return updated
        repo.record_prediction_verification_failure(entry_id, reason)
        return False

    def _verification_retry_limit(self) -> int:
        getter = getattr(
            self._get_config(),
            "get_brain_worker_prediction_verification_retries",
            None,
        )
        if getter is None:
            return 3
        try:
            return max(int(getter()), 1)
        except (TypeError, ValueError):
            return 3

    @staticmethod
    def _is_checkpoint_due(checkpoint: str) -> bool:
        """ISO date/datetime checkpoints are time-gated; event descriptions are evaluated each tick."""
        text = str(checkpoint or "").strip()
        if not text:
            return False
        normalized = text.replace("Z", "+00:00")
        try:
            due_at = datetime.fromisoformat(normalized)
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            return due_at <= datetime.now(timezone.utc)
        except ValueError:
            pass
        try:
            due_date = date.fromisoformat(text)
            return due_date <= datetime.now(timezone.utc).date()
        except ValueError:
            return True
