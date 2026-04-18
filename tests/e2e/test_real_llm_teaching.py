"""
真实 LLM 完整链路 E2E 测试 — 教学流程 + 试用流程

覆盖两条核心业务链路：
  1. 录制完成 → PM Agent 多轮确认 → 程序员 Agent → 保存工具
  2. 创建待考核工具 → 试用 Agent 多轮沟通 → 三次通过 → 自动发布

运行条件:
  EXEMPLAR_RUN_E2E_GUI=1
  config.json 中有有效的 API Key (ai.api_key)

运行方式:
  EXEMPLAR_RUN_E2E_GUI=1 pytest tests/e2e/test_real_llm_teaching.py -xvs
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QLabel

from src.data.repositories import ToolRepository
from src.ui.page_ids import INTENT_CONFIRMATION, SKILLS, TEACHING
from tests.e2e.robot.wait_helper import WaitHelper

pytestmark = [pytest.mark.e2e, pytest.mark.real_llm]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_real_api_key() -> str:
    config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    key = cfg.get("ai", {}).get("api_key")
    if not key:
        pytest.skip("config.json 中没有 ai.api_key")
    return key


def _inject_real_api_key(isolated_runtime) -> None:
    real_key = _read_real_api_key()
    isolated_runtime.keyring.set_password(
        isolated_runtime.keyring_service_name,
        "anthropic_api_key",
        real_key,
    )


def _loading_label_visible(widget) -> bool:
    """检查加载中标签是否仍然可见"""
    for label in widget.findChildren(QLabel):
        if label.objectName() == "intent_loading_label" and label.isVisible():
            return True
    return False


def _labels_contain(widget, text: str) -> bool:
    return any(text in label.text() for label in widget.findChildren(QLabel))


def _count_assistant_labels(widget) -> int:
    """统计 agent 回复内容标签数量（包括对话气泡和分析摘要）"""
    return sum(
        1 for label in widget.findChildren(QLabel)
        if (
            label.objectName().startswith("intent_message_content_assistant")
            or label.objectName() == "confirmation_message_label"
        )
        and label.isVisible()
        and label.text().strip()
    )


def _send_message(robot, intent_page, message: str) -> None:
    """填写输入框并点击发送"""
    robot.ui.fill(intent_page.message_input, message)
    robot.ui.click_button("发送")


def _agent_worker_finished(main_window, workflow_id: str) -> bool:
    """Agent worker 线程已结束，表示当前回复完全处理完毕"""
    bridge = main_window.agent_ui_bridge
    if bridge is None:
        return True
    thread = bridge._worker_threads.get(workflow_id)
    return thread is None or not thread.isRunning()


# 预设的用户回复 — 尽量完整，减少 LLM 追问轮次
_INTENT_FIRST_REPLY = (
    "我刚才录制了一段在百度搜索的操作。"
    "目标网站是 https://www.baidu.com，打开后定位搜索框，输入用户提供的关键词，"
    "然后点击搜索按钮。每次执行时关键词会变，其他步骤都一样。"
    "请帮我创建这个技能。"
)
_INTENT_FOLLOW_UP = (
    "对，就是百度搜索。目标网址 https://www.baidu.com，"
    "只需要输入关键词并点击搜索就行了，不需要对结果做其他操作。"
    "需求就是这些，请确认并提交吧。"
)
_INTENT_FINAL_CONFIRM = "是的，完全正确，请提交需求。"

# 试用阶段 — 每轮用不同关键词，验证工具通用性
_TRIAL_KEYWORDS = ["Python教程", "机器学习入门", "Claude API"]
_TRIAL_CONFIRM = "执行结果正确，符合预期。"


# ---------------------------------------------------------------------------
# Test 1: 完整教学链路（录制 → PM → 程序员 → 保存）
# ---------------------------------------------------------------------------


def test_real_llm_full_teaching_flow(
    main_window,
    isolated_runtime,
    robot,
    event_log,
    simulate_recording_completion,
):
    """真实 LLM 跑完整教学链路：录制完成 → PM 确认需求 → 程序员生成代码 → tool_saved

    支持两条路径：
    - PM 多轮对话 → submit_requirements → requirement_confirmed → Programmer
    - PM 单轮完成 → report_code_issue → triage_completed → Programmer
    """
    _inject_real_api_key(isolated_runtime)
    workflow_id = "wf-real-llm-teach"

    # 1. 触发录制完成，启动 PM Agent
    robot.ui.click_sidebar_page(TEACHING)
    simulate_recording_completion(workflow_id=workflow_id, action_count=5)

    intent_page = main_window.intent_confirmation_page

    # 2. 等待页面跳转 + Agent 首次回复（PM 或 Programmer）
    assert robot.wait.wait_until(
        lambda: main_window.main_content.get_current_page() == INTENT_CONFIRMATION,
        timeout_ms=10_000,
    ), "录制完成后未跳转到意图确认页"

    assert robot.wait.wait_until(
        lambda: _count_assistant_labels(intent_page) > 0,
        timeout_ms=120_000,
    ), "120s 内 Agent 未产出回复"

    # 3. 多轮对话循环（最多 8 轮，覆盖 PM 和 Programmer 阶段）
    max_rounds = 8
    for round_idx in range(max_rounds):
        # 已触发 tool_saved，教学链路完成
        if len(event_log["tool_saved"]) >= 1:
            break

        WaitHelper.sleep(500)

        # 根据轮次选择不同回复
        if round_idx == 0:
            message = _INTENT_FIRST_REPLY
        elif round_idx == 1:
            message = _INTENT_FOLLOW_UP
        else:
            message = _INTENT_FINAL_CONFIRM

        baseline = _count_assistant_labels(intent_page)
        _send_message(robot, intent_page, message)

        # 等待 Agent 回复或链路推进事件
        assert robot.wait.wait_until(
            lambda: (
                len(event_log["tool_saved"]) >= 1
                or _count_assistant_labels(intent_page) > baseline
            ),
            timeout_ms=120_000,
        ), f"Agent 第 {round_idx + 1} 轮未回复（120s 超时）"

    # 4. 等待 tool_saved（PM + Programmer 全部完成）
    assert robot.wait.wait_until(
        lambda: len(event_log["tool_saved"]) >= 1,
        timeout_ms=180_000,
    ), f"180s 内未触发 tool_saved（事件: requirement_confirmed={len(event_log['requirement_confirmed'])}, triage_completed={len(event_log['triage_completed'])}）"

    # 5. 结构化断言
    assert not event_log["agent_error"], f"Agent 出错: {event_log['agent_error']}"
    assert len(event_log["tool_saved"]) == 1

    tool = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool is not None, f"未找到 workflow_id={workflow_id} 的工具"
    assert tool.status == "pending"
    assert tool.execution_code, "工具缺少可执行代码"
    assert tool.tool_name, "工具缺少名称"


# ---------------------------------------------------------------------------
# Test 2: 完整试用链路（3 轮试用 → 自动发布）
# ---------------------------------------------------------------------------


def test_real_llm_full_trial_flow(
    main_window,
    isolated_runtime,
    robot,
    event_log,
    pending_tool_factory,
):
    """真实 LLM 跑完整试用链路：创建 pending tool → 3 轮试用沟通 → tool_published"""
    _inject_real_api_key(isolated_runtime)

    tool = pending_tool_factory(
        tool_name="测试搜索技能",
        description="在搜索框输入关键词并点击搜索按钮",
        parameters=[
            {
                "name": "keyword",
                "type": "text",
                "description": "搜索关键词",
                "required": True,
            }
        ],
        workflow_id="wf-real-llm-trial",
    )

    # 1. 启用 Agent Bridge，导航到技能页，启动试用
    assert main_window._ensure_agent_bridge(timeout=10.0)

    robot.ui.click_sidebar_page(SKILLS)
    assert robot.wait.wait_until(
        lambda: _labels_contain(main_window.pending_tools_page, tool.tool_name),
        timeout_ms=5_000,
    ), f"技能列表中未找到工具: {tool.tool_name}"

    main_window._on_trial_start_request(tool.tool_id)

    intent_page = main_window.intent_confirmation_page

    # 2. 等待页面跳转 + 试用 Agent 首次回复
    assert robot.wait.wait_until(
        lambda: main_window.main_content.get_current_page() == INTENT_CONFIRMATION,
        timeout_ms=10_000,
    ), "启动试用后未跳转到意图确认页"

    assert robot.wait.wait_until(
        lambda: _count_assistant_labels(intent_page) > 0,
        timeout_ms=120_000,
    ), "120s 内试用 Agent 未产出回复"

    # 3. 执行 3 轮试用
    #    每轮流程：发搜索词 → 等 Agent worker 结束 → 确认结果 → 等 Agent worker 结束
    workflow_id = "wf-real-llm-trial"
    for trial_round in range(3):
        current_successes = len(event_log["trial_success"])
        keyword = _TRIAL_KEYWORDS[trial_round]

        # 3a. 等 Agent worker 结束（上一轮完全处理完毕），再发搜索词
        assert robot.wait.wait_until(
            lambda: _agent_worker_finished(main_window, workflow_id),
            timeout_ms=120_000,
        ), f"试用第 {trial_round + 1} 轮：上一轮 Agent 未完成（120s 超时）"

        _send_message(robot, intent_page, f"请用 keyword='{keyword}' 执行一下，看看结果。")

        # 3b. 等 Agent 完整响应（worker 线程结束 = Agent 不再处理）
        assert robot.wait.wait_until(
            lambda: (
                len(event_log["trial_success"]) > current_successes
                or _agent_worker_finished(main_window, workflow_id)
            ),
            timeout_ms=120_000,
        ), f"试用 Agent 第 {trial_round + 1} 轮：发送搜索词后 Agent 未完成回复（120s 超时）"

        if len(event_log["trial_success"]) > current_successes:
            continue

        # 3c. 等 Agent worker 结束后再发确认
        assert robot.wait.wait_until(
            lambda: _agent_worker_finished(main_window, workflow_id),
            timeout_ms=10_000,
        )
        _send_message(robot, intent_page, _TRIAL_CONFIRM)

        # 3d. 等 Agent 完整响应确认
        assert robot.wait.wait_until(
            lambda: (
                len(event_log["trial_success"]) > current_successes
                or _agent_worker_finished(main_window, workflow_id)
            ),
            timeout_ms=120_000,
        ), f"试用 Agent 第 {trial_round + 1} 轮：确认结果后 Agent 未完成回复（120s 超时）"

        if len(event_log["trial_success"]) > current_successes:
            continue

        # 3e. 兜底多轮对话
        for extra in range(6):
            if len(event_log["trial_success"]) > current_successes:
                break
            assert robot.wait.wait_until(
                lambda: _agent_worker_finished(main_window, workflow_id),
                timeout_ms=10_000,
            )
            _send_message(robot, intent_page, "是的，没问题，请提交试用结果吧。")
            assert robot.wait.wait_until(
                lambda: (
                    len(event_log["trial_success"]) > current_successes
                    or _agent_worker_finished(main_window, workflow_id)
                ),
                timeout_ms=120_000,
            ), f"试用 Agent 第 {trial_round + 1} 轮兜底第 {extra + 1} 次未回复（120s 超时）"

        # 本轮必须有 trial_success
        assert len(event_log["trial_success"]) > current_successes, (
            f"试用第 {trial_round + 1} 轮未成功，"
            f"trial_success 总数: {len(event_log['trial_success'])}"
        )

    # 4. 等待 tool_published（3 次成功后自动发布）
    assert robot.wait.wait_until(
        lambda: len(event_log["tool_published"]) >= 1,
        timeout_ms=30_000,
    ), "3 次试用成功后未触发 tool_published"

    # 5. 结构化断言
    assert not event_log["agent_error"], f"Agent 出错: {event_log['agent_error']}"
    assert len(event_log["trial_success"]) == 3
    assert len(event_log["tool_published"]) == 1

    tool = ToolRepository().get_by_id(tool.tool_id)
    assert tool is not None
    assert tool.status == "published"
    assert tool.trial_success_count == 3
