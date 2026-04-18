from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QLabel

from src.business.agents.config import AgentType
from src.business.memory.assistant_memory import AssistantMemoryManager
from src.data.models_sqlite import AssistantSummary, Message, PendingAssistantTask, Session
from src.data.repositories import (
    AssistantSummaryRepository,
    MessageRepository,
    PendingTaskRepository,
    SessionRepository,
)
from src.ui.page_ids import CONVERSATIONS
from src.ui.widgets.chat_widget import SessionCard
from tests.e2e.support import dynamic_tool_short_name, text_reply, tool_call_response

pytestmark = pytest.mark.e2e


def _labels_contain(widget, text: str) -> bool:
    return any(label.isVisible() and text in label.text() for label in widget.findChildren(QLabel))


def _find_session_card(chat_widget, session_id: str) -> SessionCard | None:
    for card in chat_widget.findChildren(SessionCard):
        if card.isVisible() and getattr(card, "_session_id", None) == session_id:
            return card
    return None


def _assistant_tool_call_names(session_id: str) -> list[str]:
    names: list[str] = []
    for message in MessageRepository().get_by_session(session_id):
        if message.role != "assistant" or not message.tool_calls:
            continue
        names.extend(call["name"] for call in json.loads(message.tool_calls))
    return names


def _open_new_chat(main_window, robot):
    chat_widget = main_window._get_chat_widget()
    robot.ui.click_sidebar_action("new_chat")
    assert robot.wait.wait_until(
        lambda: chat_widget._welcome_input is not None,
        timeout_ms=5_000,
    )
    welcome_input = chat_widget._welcome_input
    assert welcome_input is not None
    return chat_widget, welcome_input


def _seed_assistant_session(
    *,
    session_id: str,
    user_message: str,
    assistant_message: str,
    status: str = "completed",
) -> str:
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status=status,
        )
    )
    message_repo = MessageRepository()
    message_repo.create(
        Message(
            message_id=f"{session_id}-user",
            session_id=session_id,
            sequence=1,
            role="user",
            content=user_message,
        )
    )
    message_repo.create(
        Message(
            message_id=f"{session_id}-assistant",
            session_id=session_id,
            sequence=2,
            role="assistant",
            content=assistant_message,
        )
    )
    return session_id


def test_simple_chat(main_window, robot, mock_llm):
    chat_widget, welcome_input = _open_new_chat(main_window, robot)
    mock_llm.push(text_reply("你好！我是你的办公助理。"))
    assert main_window._ensure_agent_bridge(timeout=10.0)

    robot.ui.fill(welcome_input, "你好，请帮我整理一下今天的工作")
    robot.ui.press_enter(welcome_input)

    assert robot.wait.wait_until(
        lambda: _labels_contain(chat_widget, "你好！我是你的办公助理。"),
        timeout_ms=15_000,
    )
    assert chat_widget.send_button.text() == "发送"


def test_skill_invocation_via_chat(
    main_window,
    robot,
    mock_llm,
    event_log,
    published_tool_factory,
):
    tool = published_tool_factory(
        tool_id="abcd1234-skill-chat",
        tool_name="搜索技能",
        description="根据关键词返回搜索结果",
        parameters=[
            {
                "name": "keyword",
                "type": "string",
                "description": "要搜索的关键词",
                "required": True,
            }
        ],
        code=(
            "async def execute(keyword: str):\n"
            "    return {\n"
            "        'success': True,\n"
            "        'message': f'已执行搜索：{keyword}',\n"
            "        'data': {'keyword': keyword},\n"
            "    }\n"
        ),
    )
    tool_name = dynamic_tool_short_name(tool.tool_id)
    mock_llm.push(
        tool_call_response("search_tools", {"query": "搜索技能"}, tc_id="tc-search"),
        tool_call_response(
            "get_tool_detail",
            {"tool_name": "技能:搜索技能"},
            tc_id="tc-detail",
        ),
        tool_call_response(
            tool_name,
            {"keyword": "Mexemplar"},
            tc_id="tc-exec",
        ),
        text_reply("已执行搜索技能，关键词 Mexemplar。"),
    )
    assert main_window._ensure_agent_bridge(timeout=10.0)

    chat_widget, welcome_input = _open_new_chat(main_window, robot)
    robot.ui.fill(welcome_input, "帮我执行搜索技能，关键词是 Mexemplar")
    robot.ui.press_enter(welcome_input)

    assert robot.wait.wait_until(
        lambda: _labels_contain(chat_widget, "已执行搜索技能，关键词 Mexemplar。"),
        timeout_ms=20_000,
    )
    assert chat_widget.send_button.text() == "发送"

    session_id = chat_widget._session_id
    assert session_id is not None
    tool_call_names = _assistant_tool_call_names(session_id)
    assert {"search_tools", "get_tool_detail", tool_name}.issubset(tool_call_names)

    tool_results = [
        message.content
        for message in MessageRepository().get_by_session(session_id)
        if message.role == "tool" and message.tool_name == tool_name
    ]
    assert tool_results
    assert "Mexemplar" in tool_results[-1]
    assert not event_log["agent_error"]


def test_session_history(
    main_window,
    robot,
    mock_llm,
    monkeypatch,
    event_log,
):
    monkeypatch.setattr(
        AssistantMemoryManager,
        "trigger_on_new_session",
        lambda self, new_session_id: None,
    )
    previous_session_id = _seed_assistant_session(
        session_id="ast-history-seeded",
        user_message="帮我整理今天的工作清单",
        assistant_message="今天有三个重点任务：写周报、回邮件、准备评审。",
    )
    AssistantSummaryRepository().create(
        AssistantSummary(
            summary_id="ss-history-memory",
            level=1,
            content="历史记忆：今天的工作重点是写周报、回邮件、准备评审。",
            source_ids=previous_session_id,
        )
    )
    mock_llm.push(
        tool_call_response(
            "memory_search",
            {"query": "今天 工作", "limit": 3},
            tc_id="tc-memory-search",
        ),
        text_reply("你之前提到今天要写周报、回邮件并准备评审。"),
    )
    assert main_window._ensure_agent_bridge(timeout=10.0)

    robot.ui.click_sidebar_page(CONVERSATIONS)
    chat_widget = main_window._get_chat_widget()
    assert chat_widget._search_input.placeholderText() == "搜索对话..."
    assert robot.wait.wait_until(
        lambda: _find_session_card(chat_widget, previous_session_id) is not None,
        timeout_ms=5_000,
    )
    assert _labels_contain(chat_widget, "帮我整理今天的工作清单")

    history_card = _find_session_card(chat_widget, previous_session_id)
    assert history_card is not None
    robot.ui.click_widget(history_card)
    assert robot.wait.wait_until(
        lambda: _labels_contain(chat_widget, "今天有三个重点任务：写周报、回邮件、准备评审。"),
        timeout_ms=5_000,
    )

    chat_widget, welcome_input = _open_new_chat(main_window, robot)
    robot.ui.fill(welcome_input, "你还记得我今天要做什么吗？")
    robot.ui.press_enter(welcome_input)

    assert robot.wait.wait_until(
        lambda: _labels_contain(chat_widget, "你之前提到今天要写周报、回邮件并准备评审。"),
        timeout_ms=15_000,
    )

    session_id = chat_widget._session_id
    assert session_id is not None and session_id != previous_session_id
    memory_results = [
        message.content
        for message in MessageRepository().get_by_session(session_id)
        if message.role == "tool" and message.tool_name == "memory_search"
    ]
    assert memory_results
    assert "写周报" in memory_results[-1]
    assert not event_log["agent_error"]


def test_background_task_creation(
    main_window,
    robot,
    mock_llm,
    event_log,
    published_tool_factory,
):
    from src.business.agents.tools.assistant_tools import register_task_worker_notify

    tool = published_tool_factory(
        tool_id="wthr1234-codify",
        tool_name="天气技能",
        description="查询指定城市的天气",
        parameters=[
            {
                "name": "city",
                "type": "string",
                "description": "城市名称",
                "required": True,
            }
        ],
        code=(
            "async def execute(city: str):\n"
            "    return {\n"
            "        'success': True,\n"
            "        'message': f'已查询{city}天气',\n"
            "        'data': {'city': city, 'weather': 'sunny'},\n"
            "    }\n"
        ),
    )
    tool_name = dynamic_tool_short_name(tool.tool_id)
    mock_llm.push(
        tool_call_response("search_tools", {"query": "天气技能"}, tc_id="tc-weather-search"),
        tool_call_response(
            "get_tool_detail",
            {"tool_name": "技能:天气技能"},
            tc_id="tc-weather-detail",
        ),
        tool_call_response(
            tool_name,
            {"city": "上海"},
            tc_id="tc-weather-exec",
        ),
        text_reply("已经查到上海天气。"),
        tool_call_response(
            "codify_as_tool",
            {"task_description": "查询指定城市天气"},
            tc_id="tc-codify",
        ),
        text_reply("已提交工具创建请求，完成后会通知你。"),
    )
    assert main_window._ensure_agent_bridge(timeout=10.0)

    orchestrator = main_window.agent_ui_bridge._orchestrator
    orchestrator.task_worker.is_running = False
    orchestrator.task_worker.notify_task_enqueued()
    register_task_worker_notify(lambda: None)

    chat_widget, welcome_input = _open_new_chat(main_window, robot)
    robot.ui.fill(welcome_input, "帮我查一下上海天气")
    robot.ui.press_enter(welcome_input)
    assert robot.wait.wait_until(
        lambda: _labels_contain(chat_widget, "已经查到上海天气。"),
        timeout_ms=20_000,
    )

    robot.ui.fill(chat_widget.message_input, "把这个操作沉淀为技能")
    robot.ui.click_button("发送")
    assert robot.wait.wait_until(
        lambda: _labels_contain(chat_widget, "已提交工具创建请求，完成后会通知你。"),
        timeout_ms=20_000,
    )

    session_id = chat_widget._session_id
    assert session_id is not None
    task_repo = PendingTaskRepository()
    tasks = task_repo.session.query(PendingAssistantTask).all()
    assert len(tasks) == 1

    task = tasks[0]
    payload = json.loads(task.payload or "{}")
    assert task.task_type == "codify_tool"
    assert payload["task_description"] == "查询指定城市天气"
    assert payload["session_id"] == session_id
    assert tool_name in [item["name"] for item in payload["execution_trace"]]
    assert any(
        item["type"] == "tool_result" and "上海" in item["content"]
        for item in payload["execution_trace"]
    )
    assert not event_log["agent_error"]
