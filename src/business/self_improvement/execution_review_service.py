"""Read-only execution review service."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS

logger = logging.getLogger(__name__)

REVIEWER_TOOLS = [tool for tool in BUILTIN_GENERAL_TOOLS if tool.name == "load_tool_output"]

_REVIEW_PROMPT = (
    "你是独立的执行复盘审查员。基于这次执行的骨架轨迹，只评判执行效率与健壮性，"
    "例如重抓、绕路、高迭代、用错工具、父子重复劳动、失败重试。不要评判最终结果对错。"
    "如确需展开某步大输出，只能使用 load_tool_output。"
    "输出 JSON：{verdict, findings:[{type, what, evidence, severity, suggestion, worth_changing}]}。"
    "type 只能是 效率 或 健壮性；severity 只能是 high、med 或 low。无问题时 findings 为空。"
)


def get_execution_review_prompt_template() -> str:
    """Return the deterministic reviewer system prompt used for execution reviews."""
    return _REVIEW_PROMPT

# prompt 声明 severity 只能 high/med/low，但 LLM 可能幻觉出 critical 等值；
# _normalize_severity 据此把非法值收敛为 low（026 I6）。
_SEVERITY_VALUES = frozenset({"high", "med", "low"})


def _normalize_severity(value: Any) -> str:
    """归一化 severity 到 high/med/low；非法值（critical/大小写混用/空）收敛为 low。"""
    text = str(value or "").strip().lower()
    return text if text in _SEVERITY_VALUES else "low"


class ExecutionReviewService:
    def review(self, skeleton: dict[str, Any], llm_client) -> dict[str, Any]:
        payload = json.dumps(skeleton, ensure_ascii=False)
        raw = self._complete_json(llm_client, payload)
        findings = self._normalize_findings(raw.get("findings") if isinstance(raw, dict) else [])
        verdict = str(raw.get("verdict") or "") if isinstance(raw, dict) else ""
        return {"verdict": verdict, "findings": findings, "advisory": True}

    def _complete_json(self, llm_client, payload: str) -> dict[str, Any]:
        if hasattr(llm_client, "complete_json"):
            result = llm_client.complete_json(
                system=_REVIEW_PROMPT,
                user=payload,
                tools=REVIEWER_TOOLS,
            )
            return result if isinstance(result, dict) else {}
        if hasattr(llm_client, "chat_with_tools"):
            return self._complete_json_with_readonly_tools(llm_client, payload)
        if hasattr(llm_client, "chat"):
            text = llm_client.chat(f"{_REVIEW_PROMPT}\n\n骨架轨迹：\n{payload}")
            return self._parse_json_object(text)
        logger.warning("Execution review skipped because llm client has no supported method")
        return {"verdict": "", "findings": []}

    def _complete_json_with_readonly_tools(self, llm_client, payload: str) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _REVIEW_PROMPT},
            {"role": "user", "content": f"骨架轨迹：\n{payload}"},
        ]
        tool_by_name = {tool.name: tool for tool in REVIEWER_TOOLS}
        for _ in range(3):
            response = llm_client.chat_with_tools(
                messages,
                [tool.schema for tool in REVIEWER_TOOLS],
            )
            if not getattr(response, "tool_calls", None):
                return self._parse_json_object(getattr(response, "content", "") or "")
            tool_calls = []
            for call in response.tool_calls:
                tool_calls.append({"id": call.id, "name": call.name, "args": call.args})
            messages.append(
                {
                    "role": "assistant",
                    "content": getattr(response, "content", "") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in response.tool_calls:
                tool = tool_by_name.get(call.name)
                if tool is None:
                    result = json.dumps({"outcome": "error", "error": "tool_not_allowed"})
                else:
                    try:
                        result = tool.handler(**(call.args or {}))
                    except Exception as exc:
                        result = json.dumps(
                            {"outcome": "error", "error": type(exc).__name__},
                            ensure_ascii=False,
                        )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "tool_name": call.name,
                        "content": str(result),
                    }
                )
        response = llm_client.chat_with_tools(messages, [tool.schema for tool in REVIEWER_TOOLS])
        return self._parse_json_object(getattr(response, "content", "") or "")

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    return parsed if isinstance(parsed, dict) else {}
                except Exception:
                    return {}
            return {}

    @staticmethod
    def _normalize_findings(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        findings: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            findings.append(
                {
                    "type": str(item.get("type") or ""),
                    "what": str(item.get("what") or ""),
                    "evidence": str(item.get("evidence") or ""),
                    "severity": _normalize_severity(item.get("severity")),
                    "suggestion": str(item.get("suggestion") or ""),
                    "worth_changing": bool(item.get("worth_changing")),
                }
            )
        return findings


class ExecutionReviewQueryService:
    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        from src.data.repos.execution_review_repository import ExecutionReviewRepository

        with ExecutionReviewRepository() as repo:
            rows = repo.list_recent(limit=limit)
            return [self._to_dto(row) for row in rows]

    @staticmethod
    def _to_dto(row) -> dict[str, Any]:
        try:
            findings = json.loads(row.findings_json or "[]")
        except Exception:
            findings = []
        if not isinstance(findings, list):
            findings = []
        return {
            "id": row.id,
            "turnSessionId": row.turn_session_id,
            "verdict": row.verdict or "",
            "findings": findings,
            "advisory": bool(row.advisory),
            "modelUsed": row.model_used or "",
            "createdAt": row.created_at,
            "reviewedAt": row.reviewed_at,
        }
