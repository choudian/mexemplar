"""Guard: todo 来源定时任务恒 one_shot，recurring 被拒（033 CC-002 / FR-016）。"""

from __future__ import annotations

import pytest

from src.business.scheduling.scheduler_service import SchedulerService


def test_todo_source_recurring_rejected():
    """source_type='todo' + recurring 必须被 create_from_draft 拒绝。"""
    service = SchedulerService()
    with pytest.raises(ValueError, match="one_shot"):
        service.create_from_draft(
            {
                "source_type": "todo",
                "source_ref": "utodo_x",
                "title": "待办任务",
                "schedule_kind": "recurring",
                "schedule_payload": {"interval_seconds": 60},
                "instruction": "x",
            }
        )


def test_todo_source_one_shot_accepted():
    """source_type='todo' + one_shot 允许。"""
    service = SchedulerService()
    task = service.create_from_draft(
        {
            "source_type": "todo",
            "source_ref": "utodo_y",
            "title": "待办一次性",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "do it",
        }
    )
    assert task["scheduleKind"] == "one_shot"
    assert task["sourceType"] == "todo"


def test_direct_source_recurring_accepted():
    """direct 来源允许 recurring（CC-002 只约束 todo 来源）。"""
    service = SchedulerService()
    task = service.create_from_draft(
        {
            "source_type": "direct",
            "source_ref": "poll",
            "title": "直接周期",
            "schedule_kind": "recurring",
            "schedule_payload": {"interval_seconds": 60},
            "instruction": "poll",
        }
    )
    assert task["scheduleKind"] == "recurring"
