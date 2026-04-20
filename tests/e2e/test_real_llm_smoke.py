"""
真实 LLM 冒烟测试 — 验证链路通，不检查具体回复文本

运行条件:
  EXEMPLAR_RUN_E2E_GUI=1

仅验证:
  - LLM 客户端能连上 API 并拿到回复
  - Agent 编排流程不报错
  - 事件正常触发
"""


import json
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QLabel

from src.ui.page_ids import INTENT_CONFIRMATION, TEACHING

pytestmark = [pytest.mark.e2e, pytest.mark.real_llm]


def _read_real_api_key() -> str:
    """从项目根目录 config.json 读取真实 API Key"""
    config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    key = cfg.get("ai", {}).get("api_key")
    if not key:
        pytest.skip("config.json 中没有 ai.api_key")
    return key


def _any_visible_text(widget) -> bool:
    """控件中是否存在可见的非空文本标签"""
    return any(
        label.isVisible() and label.text().strip()
        for label in widget.findChildren(QLabel)
    )


def _inject_real_api_key(isolated_runtime) -> None:
    """把 config.json 中的真实 API Key 注入 InMemoryKeyring"""
    real_key = _read_real_api_key()
    isolated_runtime.keyring.set_password(
        isolated_runtime.keyring_service_name,
        "anthropic_api_key",
        real_key,
    )


# ---------------------------------------------------------------------------
# Test 1: Assistant 简单对话
# ---------------------------------------------------------------------------


def test_real_llm_assistant_chat(main_window, isolated_runtime, robot, event_log):
    """用真实 LLM 发一条消息，验证能收到回复"""
    _inject_real_api_key(isolated_runtime)

    chat_widget = main_window._get_chat_widget()
    robot.ui.click_sidebar_action("new_chat")
    assert robot.wait.wait_until(
        lambda: chat_widget._welcome_input is not None,
        timeout_ms=5_000,
    )

    assert main_window._ensure_agent_bridge(timeout=30.0)

    robot.ui.fill(chat_widget._welcome_input, "你好，请用一句话介绍你自己")
    robot.ui.press_enter(chat_widget._welcome_input)

    assert robot.wait.wait_until(
        lambda: _any_visible_text(chat_widget),
        timeout_ms=60_000,
    ), "60s 内未收到 LLM 回复"

    assert not event_log["agent_error"], f"Agent 出错: {event_log['agent_error']}"


# ---------------------------------------------------------------------------
# Test 2: 教学流程冒烟（PM Agent 启动 → 用户确认意图 → 全流程）
# ---------------------------------------------------------------------------


def test_real_llm_teaching_smoke(
    main_window,
    isolated_runtime,
    robot,
    event_log,
    simulate_recording_completion,
):
    """触发录制完成 → PM Agent 启动并回复 → 验证整条编排链路通

    注意: simulate_recording_completion 不写 DuckDB 录制数据，PM Agent
    会发现没有数据并如实告知用户。这恰好验证了 PM Agent 编排链路完整：
    事件触发 → AgentOrchestrator → PM AgentLoop → LLM 调用 → UI 回显。
    """
    _inject_real_api_key(isolated_runtime)

    robot.ui.click_sidebar_page(TEACHING)
    simulate_recording_completion(action_count=5)

    # 验证跳转到意图确认页
    assert robot.wait.wait_until(
        lambda: main_window.main_content.get_current_page() == INTENT_CONFIRMATION,
        timeout_ms=10_000,
    ), "录制完成后未跳转到意图确认页"

    # 等待 PM Agent 产出回复（LLM 需要多次调用）
    intent_page = main_window.intent_confirmation_page
    assert robot.wait.wait_until(
        lambda: _any_visible_text(intent_page),
        timeout_ms=120_000,
    ), "120s 内 PM Agent 未产出回复"

    # 验证没有 agent_error
    assert not event_log["agent_error"], f"Agent 出错: {event_log['agent_error']}"
