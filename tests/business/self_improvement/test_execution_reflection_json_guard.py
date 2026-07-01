"""execution_reflection_service json 守卫测试（026 C5）。

avoidance rule 的 content 可能是合法 JSON 但非对象（list/str/int），json.loads 成功
后直接 .get() 会 AttributeError 崩溃。需 isinstance(dict) 守卫（486528f 同型坑）。
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.business.brain.models import EntryType
from src.business.self_improvement import execution_reflection_service as ers_module
from src.business.self_improvement.execution_reflection_service import (
    ExecutionReflectionService,
)


def test_get_avoidance_rules_skips_non_dict_json_content(monkeypatch) -> None:
    monkeypatch.setattr(
        ers_module,
        "get_unified_config",
        lambda: MagicMock(get_self_improvement_avoidance_top_n=lambda: 10),
    )

    entries = [
        SimpleNamespace(
            entry_id="e_non_dict",
            entry_type=EntryType.AVOIDANCE_RULE,
            content="[1, 2, 3]",  # 合法 JSON 但是 list → .get() 会崩
            relevance_score=0.5,
        ),
        SimpleNamespace(
            entry_id="e_valid",
            entry_type=EntryType.AVOIDANCE_RULE,
            content=json.dumps({"pattern": "deploy", "avoidance": "run tests first"}),
            relevance_score=0.5,
        ),
    ]
    brain_repo = MagicMock()
    brain_repo.get_entries_by_zone.return_value = entries

    service = ExecutionReflectionService(
        si_repo=MagicMock(),
        audit_service=MagicMock(),
        safety_governor=MagicMock(),
        brain_repo=brain_repo,
    )

    rules = service.get_avoidance_rules_for_context("deploy step")

    # 非 dict 那条被跳过（不崩溃）；valid 那条匹配 context 返回
    assert all(r["entry_id"] != "e_non_dict" for r in rules)
    assert any(r["entry_id"] == "e_valid" for r in rules)


def test_avoidance_rule_db_persistence_failure_logged_as_error(caplog) -> None:
    """brain_repo.create_entry 抛 DB 异常时必须 log ERROR，不得被过宽 except 吞成
    JSON/LLM warning（026 errors 审查 I2）。

    修复前 ``_generate_avoidance_rule`` 的 ``except (json.JSONDecodeError, Exception)``
    包了 ``create_entry`` + ``log_action``：DB 持久化失败被伪装成良性 "Avoidance
    rule generation failed" warning，掩盖真实故障。avoidance rule 是 best-effort
    附加（reflection 已存储），DB 失败不应冒泡，但必须以 ERROR 记录、且消息区分于
    JSON 解析失败。
    """
    brain_repo = MagicMock()
    brain_repo.create_entry.side_effect = RuntimeError("db constraint violation")

    service = ExecutionReflectionService(
        si_repo=MagicMock(),
        audit_service=MagicMock(),
        safety_governor=MagicMock(),
        brain_repo=brain_repo,
    )

    class _LLM:
        def call(self, *, messages, max_tokens, temperature):
            return '{"pattern": "p", "avoidance": "a", "evidence_count": 1}'

    with caplog.at_level("DEBUG", logger=ers_module.logger.name):
        # best-effort: DB 失败不应冒泡出 _generate_avoidance_rule
        service._generate_avoidance_rule(
            session_id="s1",
            task_description="t",
            reflection_text="r",
            llm_client=_LLM(),
        )

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert error_records, "DB 写入失败必须 log ERROR，不得降级为 warning"
    # 消息必须区分持久化失败（不是泛泛的 "generation failed" 误分类为 LLM/JSON）
    msgs = [r.getMessage().lower() for r in error_records]
    assert any("persist" in m or "store" in m or "brain" in m for m in msgs), msgs
