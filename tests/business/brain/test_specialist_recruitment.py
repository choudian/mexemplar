"""Automatic specialist recruitment tests."""

import json
from uuid import uuid4

import pytest

from src.data.models_sqlite import BrainRecruitmentSignal, Tool
from src.utils.events import clear_all, connect


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


def test_records_sustained_delegation_signal(in_memory_db):
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    signal_id = repo.record_recruitment_signal(
        task_pattern="整理每周销售报表",
        session_id="sess-1",
        delegation_summary="生成销售透视摘要",
    )
    repo.record_recruitment_signal(
        task_pattern="整理每周销售报表",
        session_id="sess-2",
        delegation_summary="补齐渠道对比",
    )

    with in_memory_db.get_session() as session:
        signal = session.get(BrainRecruitmentSignal, signal_id)
        assert signal is not None
        assert signal.delegation_count == 2
        assert json.loads(signal.example_session_ids) == ["sess-1", "sess-2"]
        assert json.loads(signal.example_delegation_summaries) == [
            "生成销售透视摘要",
            "补齐渠道对比",
        ]


def test_scan_and_recruit_creates_specialist_from_threshold_signal(in_memory_db):
    from src.business.brain.specialist_service import SpecialistService

    signal_id = uuid4().hex[:50]
    with in_memory_db.get_session() as session:
        session.add(
            BrainRecruitmentSignal(
                signal_id=signal_id,
                task_pattern="数据清洗与报表整理",
                delegation_count=5,
                example_session_ids=json.dumps(["sess-1"], ensure_ascii=False),
                example_delegation_summaries=json.dumps(
                    ["清理重复行并输出报表", "补齐缺失字段"],
                    ensure_ascii=False,
                ),
            )
        )
        session.commit()

    created = SpecialistService().scan_and_recruit()

    assert len(created) == 1
    specialist = created[0]
    assert specialist["origin"] == "auto_recruitment"
    assert specialist["reason"].startswith("检测到持续委托模式")
    assert "清理重复行并输出报表" in specialist["role_definition"]

    with in_memory_db.get_session() as session:
        signal = session.get(BrainRecruitmentSignal, signal_id)
        assert signal.specialist_id == specialist["specialist_id"]


def test_worker_emits_recruited_event_after_auto_recruitment():
    from src.business.brain.background_worker import BrainBackgroundWorker

    received = []
    connect("brain_specialist_recruited", lambda sender, **kwargs: received.append(kwargs), weak=False)

    class StubService:
        def scan_and_recruit(self):
            return [
                {
                    "specialist_id": "spec-1",
                    "name": "报表专员",
                    "reason": "检测到持续报表委托",
                }
            ]

    worker = BrainBackgroundWorker()
    worker._run_recruitment_scan = BrainBackgroundWorker._run_recruitment_scan.__get__(worker)

    import src.business.brain.specialist_service as specialist_module

    original = specialist_module.SpecialistService
    specialist_module.SpecialistService = StubService
    try:
        worker._run_recruitment_scan()
    finally:
        specialist_module.SpecialistService = original

    assert received == [
        {
            "event_name": "brain_specialist_recruited",
            "specialist_id": "spec-1",
            "name": "报表专员",
            "reason": "检测到持续报表委托",
        }
    ]


def test_force_remove_skill_prunes_specialist_whitelists(in_memory_db):
    from src.business.brain.specialist_service import SpecialistService

    with in_memory_db.get_session() as session:
        session.add(
            Tool(
                tool_id="tool-report",
                tool_name="报表分析",
                description="分析报表",
                status="published",
            )
        )
        session.commit()

    service = SpecialistService()
    specialist = service.create_specialist(
        name="报表专员",
        description="处理周期报表",
        role_definition="你负责处理报表。",
        tool_whitelist=["tool-report"],
    )

    assert service.check_skill_in_use("tool-report")[0]["specialist_id"] == specialist["specialist_id"]

    result = service.force_remove_skill_from_pool("tool-report")

    assert result["removed"] is True
    assert result["pruned_specialists"][0]["specialist_id"] == specialist["specialist_id"]
    assert SpecialistService().get_specialist(specialist["specialist_id"])["tool_whitelist"] == []
    assert SpecialistService().list_skill_pool() == []


def test_remove_unreferenced_skill_excludes_it_from_skill_pool(in_memory_db):
    from src.business.brain.specialist_service import SpecialistService
    from src.data.repos.brain_repository import BrainRepository

    with in_memory_db.get_session() as session:
        session.add(
            Tool(
                tool_id="tool-report",
                tool_name="报表分析",
                description="分析报表",
                status="published",
            )
        )
        session.commit()

    service = SpecialistService()
    assert [skill["tool_id"] for skill in service.list_skill_pool()] == ["tool-report"]

    result = service.remove_skill_from_pool("tool-report")

    assert result == {"removed": True, "pruned_specialists": []}
    assert SpecialistService().list_skill_pool() == []
    assert "tool-report" in BrainRepository().get_removed_skill_pool_identifiers()
    with pytest.raises(ValueError):
        SpecialistService().create_specialist(
            name="报表专员",
            description="处理报表",
            role_definition="你负责处理报表。",
            tool_whitelist=["tool-report"],
        )
