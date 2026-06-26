"""
v2 全链路集成测试

覆盖三条核心路径：
1. Happy Path   — PM → 程序员 → Review 通过 → 工具入库
2. Review 打回  — Review 连续失败 4 次 → 第 4 次强制入库
3. 试用失败分诊 — 试用失败 → PM 分诊 → 程序员修复 → 重新入库

Mock 策略：
- 只 Mock LLM（MockLLMClient），其余全部真实运行（DB、事件、工具调用）
- 数据库使用 in-memory SQLite（通过 conftest.in_memory_db 替换全局 singleton）
"""

import pytest

from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.business.orchestration.agent import AgentOrchestrator
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository
from src.data.repositories import ToolRepository, WorkflowTransitionRepository

from tests.conftest import MockLLMClient


@pytest.fixture(autouse=True)
def isolated_recording_db(tmp_path):
    """Keep recording-mode fixtures out of the process-global DuckDB file."""
    import src.data.duckdb_manager as duckdb_module

    old_instance = duckdb_module._duckdb_instance
    old_desktop_ensured = RecordingRepository._desktop_tables_ensured
    duckdb_module._duckdb_instance = None
    RecordingRepository._desktop_tables_ensured = False
    db = DuckDBManager(str(tmp_path / "v2_full_flow.duckdb"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
        RecordingRepository._desktop_tables_ensured = old_desktop_ensured


# =============================================================================
# 辅助函数：构造常用的 LLMResponse
# =============================================================================

SAMPLE_CODE = (
    "async def execute(**kwargs):\n" "    return {'success': True, 'message': 'ok', 'data': {}}"
)

SAMPLE_CODE_V2 = (
    "async def execute(**kwargs):\n"
    "    # v2 修复版\n"
    "    return {'success': True, 'message': 'fixed', 'data': {}}"
)


def _pm_submit_requirements(recording_id: str, tc_id: str = "tc-pm-1") -> LLMResponse:
    """PM Agent 提交需求的 mock 响应"""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id=tc_id,
                name="submit_requirements",
                args={
                    "goal": "测试目标：自动提交表单",
                    "recording_id": recording_id,
                    "parameters": [],
                },
            )
        ],
    )


def _programmer_submit_code(code: str = SAMPLE_CODE, tc_id: str = "tc-prog-1") -> LLMResponse:
    """程序员 Agent 提交代码的 mock 响应"""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id=tc_id,
                name="submit_code",
                args={
                    "tool_name": "auto_submit_form",
                    "description": "自动提交表单",
                    "code": code,
                    "execution_strategy": "api",
                    "parameters": [],
                },
            )
        ],
    )


def _review_passed() -> str:
    return '{"passed": true, "feedback": "代码符合规范，可以入库"}'


def _review_failed(msg: str = "函数签名错误") -> str:
    return f'{{"passed": false, "feedback": "{msg}"}}'


def _trial_submit_result(success: bool, feedback: str = "") -> LLMResponse:
    """试用 Agent 提交结论的 mock 响应"""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id="tc-trial-1",
                name="submit_trial_result",
                args={"success": success, "feedback": feedback},
            )
        ],
    )


def _trial_wait_for_user(message: str = "请重新试用修复后的工具。") -> LLMResponse:
    """试用 Agent 在修复后自动恢复会话时等待用户继续输入。"""
    return LLMResponse(content=message, tool_calls=[])


def _pm_report_code_issue(
    feedback: str = "代码逻辑有误", tc_id: str = "tc-pm-triage"
) -> LLMResponse:
    """PM Agent 分诊后报告代码问题的 mock 响应"""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id=tc_id,
                name="report_code_issue",
                args={"feedback": feedback},
            )
        ],
    )


def _seed_browser_recording(recording_id: str) -> None:
    RecordingRepository().save_recording_session(
        {"recording_id": recording_id, "start_time": 1, "recording_mode": "browser"}
    )


# =============================================================================
# 路径一：Happy Path
# =============================================================================


def test_happy_path(mock_config, events_collector):
    """
    PM → 程序员 → Review 通过 → 工具入库

    验证：
    - 4 个事件依次触发（requirement_confirmed、code_completed、review_passed、tool_saved）
    - DB 中 Tool 存在，workflow_id 正确，status == "pending"
    - WorkflowTransition 包含对应事件类型
    """
    workflow_id = "wf-happy-001"
    _seed_browser_recording(workflow_id)

    responses = [
        _pm_submit_requirements(workflow_id),  # 1. PM
        _programmer_submit_code(),  # 2. 程序员
        _review_passed(),  # 3. Review
    ]

    mock_llm = MockLLMClient(responses)
    orchestrator = AgentOrchestrator(llm_client=mock_llm, config=mock_config)

    orchestrator.start_analysis(workflow_id, workflow_id)

    # --- 事件验证 ---
    assert "requirement_confirmed" in events_collector, "应触发 requirement_confirmed 事件"
    req = events_collector["requirement_confirmed"][0]
    assert req["requirements_json"]["goal"] == "测试目标：自动提交表单"

    assert "code_completed" in events_collector, "应触发 code_completed 事件"
    assert "review_passed" in events_collector, "应触发 review_passed 事件"
    assert "tool_saved" in events_collector, "应触发 tool_saved 事件"

    assert (
        "agent_error" not in events_collector
    ), f"不应有错误事件: {events_collector.get('agent_error')}"

    tool_id = events_collector["tool_saved"][0]["tool_id"]
    assert tool_id is not None

    # --- DB 验证 ---
    tool = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool is not None
    assert tool.workflow_id == workflow_id
    assert tool.status == "pending"
    assert tool.tool_name == "auto_submit_form"
    assert tool.execution_code == SAMPLE_CODE

    transitions = WorkflowTransitionRepository().get_by_workflow(workflow_id)
    event_types = [t.event_type for t in transitions]
    assert "requirement_confirmed" in event_types
    assert "code_completed" in event_types
    assert "review_passed" in event_types
    assert "tool_saved" in event_types


# =============================================================================
# 路径二：Review 打回 → 第 4 次强制入库
# =============================================================================


def test_review_retry_forced_save(mock_config, events_collector):
    """
    Review 连续失败 4 次 → 第 4 次强制入库（forced_save=True）

    验证：
    - review_failed 共 4 条
    - 前 3 条 forced_save=False，第 4 条 forced_save=True
    - 最终 tool_saved 存在
    - _review_counts 中该 workflow_id 已清除（通过 orchestrator 内部状态验证）
    """
    workflow_id = "wf-retry-002"
    _seed_browser_recording(workflow_id)

    responses = [
        _pm_submit_requirements(workflow_id),  # 1. PM
        _programmer_submit_code(tc_id="tc-prog-1"),  # 2. 程序员（第1次）
        _review_failed("函数签名错误"),  # 3. Review 失败（retry_count=1）
        _programmer_submit_code(tc_id="tc-prog-2"),  # 4. 程序员（第2次）
        _review_failed("缺少返回格式"),  # 5. Review 失败（retry_count=2）
        _programmer_submit_code(tc_id="tc-prog-3"),  # 6. 程序员（第3次）
        _review_failed("必崩逻辑"),  # 7. Review 失败（retry_count=3）
        _programmer_submit_code(tc_id="tc-prog-4"),  # 8. 程序员（第4次）
        _review_failed("仍有问题"),  # 9. Review 失败（retry_count=4，强制入库）
    ]

    mock_llm = MockLLMClient(responses)
    orchestrator = AgentOrchestrator(llm_client=mock_llm, config=mock_config)

    orchestrator.start_analysis(workflow_id, workflow_id)

    # --- 事件验证 ---
    assert "review_failed" in events_collector, "应触发 review_failed 事件"
    failed_events = events_collector["review_failed"]
    assert len(failed_events) == 4, f"应有 4 次 review_failed，实际 {len(failed_events)} 次"

    # 前 3 次：forced_save=False
    for i in range(3):
        assert failed_events[i]["forced_save"] is False, (
            f"第 {i+1} 次 review_failed 的 forced_save 应为 False，"
            f"实际: {failed_events[i]['forced_save']}"
        )
        assert failed_events[i]["retry_count"] == i + 1

    # 第 4 次：forced_save=True
    assert failed_events[3]["forced_save"] is True, "第 4 次 review_failed 的 forced_save 应为 True"
    assert failed_events[3]["retry_count"] == 4

    assert "tool_saved" in events_collector, "强制入库后应触发 tool_saved"
    assert (
        "agent_error" not in events_collector
    ), f"不应有错误事件: {events_collector.get('agent_error')}"

    # --- orchestrator 内部状态：_review_counts 已清除 ---
    assert (
        workflow_id not in orchestrator._review_counts
    ), "_review_counts 中该 workflow_id 应已清除（强制入库后 pop）"

    # --- DB 验证 ---
    tool = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool is not None
    assert tool.status == "pending"


# =============================================================================
# 路径三：试用失败 → PM 分诊 → 程序员修复 → 重新入库
# =============================================================================


def test_trial_fail_triage_fix(mock_config, events_collector):
    """
    前置：正常入库（PM → 程序员 → Review pass）
    然后：试用失败 → PM 分诊（code_issue）→ 程序员修复 → Review pass → 工具更新入库

    验证：
    - trial_failed 存在，triage_completed 存在（triage_result=code_issue）
    - 最终 tool_saved 有 2 条（首次入库 + 修复后更新）
    - DB 中 Tool.execution_code 已更新为 SAMPLE_CODE_V2
    - trial_success_count 清零（_save_tool 更新时重置为 0）
    """
    workflow_id = "wf-trial-003"
    _seed_browser_recording(workflow_id)

    responses = [
        # === 阶段一：首次正常入库 ===
        _pm_submit_requirements(workflow_id, tc_id="tc-pm-init"),  # 1. PM
        _programmer_submit_code(tc_id="tc-prog-init"),  # 2. 程序员
        _review_passed(),  # 3. Review 通过
        # === 阶段二：试用失败 → 分诊 → 修复 ===
        _trial_submit_result(success=False, feedback="输出结果不对"),  # 4. 试用 Agent 失败
        _pm_report_code_issue("输出结果不对，代码逻辑有误"),  # 5. PM 分诊 → code_issue
        _programmer_submit_code(SAMPLE_CODE_V2, tc_id="tc-prog-fix"),  # 6. 程序员修复
        _review_passed(),  # 7. Review 再次通过
        _trial_wait_for_user(),  # 8. 修复后恢复 Trial，会等待用户继续试用
    ]

    mock_llm = MockLLMClient(responses)
    orchestrator = AgentOrchestrator(llm_client=mock_llm, config=mock_config)

    # --- 阶段一：首次正常入库 ---
    orchestrator.start_analysis(workflow_id, workflow_id)

    assert "tool_saved" in events_collector
    first_tool_id = events_collector["tool_saved"][0]["tool_id"]

    # 验证工具已入库
    tool_after_first = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool_after_first is not None
    assert tool_after_first.execution_code == SAMPLE_CODE

    # --- 阶段二：试用失败 → 分诊 → 修复 ---
    # 取第一次 run_agent 生成的 trial session_id 作为试用会话（实际由 orchestrator 管理）
    # 直接调用 start_trial，让 trial agent 运行并提交失败结论
    orchestrator.start_trial(
        tool_id=first_tool_id,
        user_input="请帮我试用这个工具",
        workflow_id=workflow_id,
    )

    # --- 事件验证 ---
    assert "trial_failed" in events_collector, "应触发 trial_failed 事件"
    trial_failed_ev = events_collector["trial_failed"][0]
    assert trial_failed_ev["tool_id"] == first_tool_id
    assert trial_failed_ev["user_feedback"] == "输出结果不对"

    assert "triage_completed" in events_collector, "应触发 triage_completed 事件"
    triage_ev = events_collector["triage_completed"][0]
    assert triage_ev["triage_result"] == "code_issue"

    assert (
        "agent_error" not in events_collector
    ), f"不应有错误事件: {events_collector.get('agent_error')}"

    # tool_saved 共两条：首次入库 + 修复后更新
    assert (
        len(events_collector["tool_saved"]) == 2
    ), f"应有 2 次 tool_saved，实际 {len(events_collector['tool_saved'])} 次"

    # --- DB 验证：工具代码已更新，trial_success_count 清零 ---
    tool_after_fix = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool_after_fix is not None
    assert tool_after_fix.execution_code == SAMPLE_CODE_V2, "修复后工具代码应更新为 SAMPLE_CODE_V2"
    assert (
        tool_after_fix.trial_success_count == 0
    ), "_save_tool 更新已有工具时应将 trial_success_count 清零"
