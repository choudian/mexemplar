"""
US4: Feedback signal persistence and prompt injection tests.
"""

from src.utils.events import clear_all


def teardown_function():
    clear_all()


def test_feedback_signal_persisted_by_repository():
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    signal_id = repo.create_feedback_signal(
        zone="failure",
        operation="delete",
        target_id="entry-1",
        context_summary="用户删除了错误的失败记忆",
    )

    signals = repo.get_recent_feedback_signals(zone="failure")
    assert signals[0].signal_id == signal_id
    assert signals[0].operation == "delete"


def test_distillation_prompt_injects_recent_feedback_signals():
    from src.business.brain.distillation_service import DistillationService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    repo.create_feedback_signal(
        zone="hot",
        operation="edit",
        target_id="entry-1",
        context_summary="用户把预算记忆改得更具体",
    )

    prompt = DistillationService(repo=repo)._build_distillation_prompt(phase="p4")

    assert "近期用户反馈信号" in prompt
    assert "预算记忆" in prompt


def test_distillation_prompt_no_feedback_is_silent_noop():
    from src.business.brain.distillation_service import DistillationService
    from src.data.repos.brain_repository import BrainRepository

    prompt = DistillationService(repo=BrainRepository())._build_distillation_prompt(phase="p4")

    assert "近期用户反馈信号" not in prompt
    # 结构性锚点:确认 prompt 正常构建(含 zone 结构),不耦合具体 advisory 文案
    assert "hot_zone" in prompt


def test_management_delete_entry_records_feedback_signal():
    from src.business.brain.management_service import BrainManagementService
    from src.business.brain.models import Zone
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    entry_id = repo.create_entry(
        zone=Zone.FAILURE.value,
        content="错误的失败记忆",
        origin="distillation",
        reason="测试",
    )

    BrainManagementService(repo=repo).soft_delete_entry(entry_id)

    signals = repo.get_recent_feedback_signals(zone=Zone.FAILURE.value)
    assert signals[0].operation == "delete"
    assert signals[0].target_id == entry_id


def test_specialist_edit_and_delete_record_feedback_signals():
    from src.business.brain.specialist_service import SpecialistService
    from src.data.repos.brain_repository import BrainRepository
    from src.data.repos.specialist_repository import SpecialistRepository

    service = SpecialistService(repo=SpecialistRepository())
    specialist = service.create_specialist(
        name="预算专员",
        description="处理预算问题",
        role_definition="负责预算分析",
        tool_whitelist=[],
        origin="auto_recruitment",
        reason="检测到持续预算委托",
    )

    service.update_specialist(
        specialist["specialist_id"],
        description="处理预算审核问题",
    )
    service.delete_specialist(specialist["specialist_id"])

    signals = BrainRepository().get_recent_feedback_signals(zone="specialist", limit=5)
    operations = [signal.operation for signal in signals]
    assert "edit" in operations
    assert "delete" in operations
