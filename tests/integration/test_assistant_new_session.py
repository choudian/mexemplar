"""
助理 Agent 新建会话集成测试

覆盖链路：UI 新建会话 → 发送消息 → Orchestrator 调度 → AgentLoop 执行 → 数据持久化

Mock 策略：
- 只 Mock LLM（MockLLMClient），其余全部真实运行（DB、事件、工具调用）
- 数据库使用 in-memory SQLite（通过 conftest.in_memory_db 替换全局 singleton）
"""

import json
import pytest

from src.business.agents.config import AgentType
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.business.orchestration.agent import AgentOrchestrator
from src.data.models_sqlite import Session
from src.data.repositories import SessionRepository, MessageRepository

from tests.conftest import MockLLMClient


# =============================================================================
# 辅助函数
# =============================================================================


def _assistant_text_reply(content: str, tc_id: str = "tc-ast-1") -> LLMResponse:
    """模拟 assistant 直接文字回复（text_as_user_input=True → NEEDS_USER_INPUT）"""
    return LLMResponse(content=content, tool_calls=[])


def _assistant_talk_to_user(message: str, tc_id: str = "tc-ast-1") -> LLMResponse:
    """模拟 assistant 调用 talk_to_user 工具"""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id=tc_id,
                name="talk_to_user",
                args={"message": message},
            )
        ],
    )


def _create_assistant_session() -> str:
    """在数据库中创建一个 assistant 会话，模拟 ChatWidget._create_session()"""
    import uuid

    session_id = f"ast_{uuid.uuid4().hex[:12]}"
    repo = SessionRepository()
    repo.create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            tool_ids=None,
        )
    )
    return session_id


# =============================================================================
# 测试用例
# =============================================================================


class TestAssistantNewSession:
    """助理 Agent 新建会话集成测试"""

    # -------------------------------------------------------------------------
    # 1. 数据层：创建会话 + 持久化验证
    # -------------------------------------------------------------------------

    def test_create_session_persists_to_db(self, in_memory_db):
        """新建会话应正确写入数据库"""
        session_id = _create_assistant_session()

        repo = SessionRepository()
        session = repo.get_by_id(session_id)
        assert session is not None
        assert session.agent_type == AgentType.ASSISTANT
        assert session.status == "active"
        assert session.workflow_id is None

    def test_session_appears_in_agent_type_list(self, in_memory_db):
        """新建的 assistant 会话应出现在按 agent_type 查询的结果中"""
        session_id = _create_assistant_session()

        repo = SessionRepository()
        sessions = repo.get_by_agent_type(AgentType.ASSISTANT)
        session_ids = [s.session_id for s in sessions]
        assert session_id in session_ids

    # -------------------------------------------------------------------------
    # 2. 业务编排层：Orchestrator 正确调度 assistant Agent
    # -------------------------------------------------------------------------

    def test_orchestrator_runs_assistant_agent(self, in_memory_db, mock_config, events_collector):
        """
        Orchestrator.run_agent('assistant', ...) 应：
        1. 正确创建 AgentLoop
        2. 保存 system prompt（首条消息）
        3. 保存用户消息
        4. 调用 LLM 并保存 assistant 回复
        5. 对于 text_as_user_input=True 的 assistant，直接文字回复触发 NEEDS_USER_INPUT
        6. 发出 agent_needs_user_input 事件
        """
        session_id = _create_assistant_session()

        # LLM 返回一条直接文字回复
        mock_llm = MockLLMClient([
            _assistant_text_reply("你好！我是你的办公助理，有什么可以帮你的？"),
        ])
        orchestrator = AgentOrchestrator(mock_llm, mock_config)
        orchestrator.run_agent(
            agent_type=AgentType.ASSISTANT,
            user_input="你好",
            session_id=session_id,
        )

        # 验证事件：应发出 agent_needs_user_input（因为 text_as_user_input=True）
        assert "agent_needs_user_input" in events_collector
        event_data = events_collector["agent_needs_user_input"][0]
        assert event_data["session_id"] == session_id
        assert event_data["agent_type"] == AgentType.ASSISTANT
        assert "办公助理" in event_data["question"]

    def test_orchestrator_saves_messages(self, in_memory_db, mock_config):
        """Orchestrator 运行后，数据库中应有 system + user + assistant 三条消息"""
        session_id = _create_assistant_session()

        mock_llm = MockLLMClient([
            _assistant_text_reply("你好！有什么可以帮你的？"),
        ])
        orchestrator = AgentOrchestrator(mock_llm, mock_config)
        orchestrator.run_agent(
            agent_type=AgentType.ASSISTANT,
            user_input="你好",
            session_id=session_id,
        )

        # 验证消息持久化
        msg_repo = MessageRepository()
        messages = msg_repo.get_all(session_id)
        assert len(messages) >= 3  # system + user + assistant

        roles = [m.role for m in messages]
        assert roles[0] == "system"
        assert "user" in roles
        assert "assistant" in roles

        # 验证 user 消息内容
        user_msgs = [m for m in messages if m.role == "user"]
        assert any("你好" in (m.content or "") for m in user_msgs)

        # 验证 assistant 回复内容
        assistant_msgs = [m for m in messages if m.role == "assistant"]
        assert any("帮你" in (m.content or "") for m in assistant_msgs)

    # -------------------------------------------------------------------------
    # 3. Agent 执行层：AgentLoop 正确处理 assistant 的 talk_to_user
    # -------------------------------------------------------------------------

    def test_talk_to_user_triggers_needs_input(self, in_memory_db, mock_config, events_collector):
        """assistant 直接文字回复（text_as_user_input=True）应触发 NEEDS_USER_INPUT"""
        session_id = _create_assistant_session()

        mock_llm = MockLLMClient([
            _assistant_text_reply("请问你需要什么帮助？"),
        ])
        orchestrator = AgentOrchestrator(mock_llm, mock_config)
        orchestrator.run_agent(
            agent_type=AgentType.ASSISTANT,
            user_input="帮我查一下",
            session_id=session_id,
        )

        # 验证事件
        assert "agent_needs_user_input" in events_collector
        event_data = events_collector["agent_needs_user_input"][0]
        assert event_data["session_id"] == session_id
        assert "帮助" in event_data["question"]

    # -------------------------------------------------------------------------
    # 4. 多轮对话：用户回复后继续对话
    # -------------------------------------------------------------------------

    def test_multi_turn_conversation(self, in_memory_db, mock_config, events_collector):
        """
        模拟两轮对话：
        第 1 轮：用户发送 "你好" → assistant 回复问候
        第 2 轮：用户回复 "帮我看看天气" → assistant 再回复
        """
        session_id = _create_assistant_session()

        # 第 1 轮
        mock_llm_1 = MockLLMClient([
            _assistant_text_reply("你好！我是你的办公助理。"),
        ])
        orchestrator = AgentOrchestrator(mock_llm_1, mock_config)
        orchestrator.run_agent(
            agent_type=AgentType.ASSISTANT,
            user_input="你好",
            session_id=session_id,
        )

        # 第 2 轮：重建 orchestrator（新的 LLM 响应序列）
        mock_llm_2 = MockLLMClient([
            _assistant_text_reply("好的，让我来查一下天气。"),
        ])
        orchestrator_2 = AgentOrchestrator(mock_llm_2, mock_config)
        orchestrator_2.run_agent(
            agent_type=AgentType.ASSISTANT,
            user_input="帮我看看天气",
            session_id=session_id,
        )

        # 验证消息数量：system(1) + user(1) + assistant(1) + user(2) + assistant(2) = 5
        msg_repo = MessageRepository()
        messages = msg_repo.get_all(session_id)
        assert len(messages) >= 5

        # 验证两轮 user 消息都在
        user_contents = [m.content for m in messages if m.role == "user"]
        assert any("你好" in c for c in user_contents)
        assert any("天气" in c for c in user_contents)

    # -------------------------------------------------------------------------
    # 5. 错误处理：LLM 调用失败
    # -------------------------------------------------------------------------

    def test_llm_failure_emits_error_event(self, in_memory_db, mock_config, events_collector):
        """LLM 调用失败应发出 agent_error 事件"""
        session_id = _create_assistant_session()

        # MockLLMClient 序列为空，next() 会抛 StopIteration
        # 但 AgentLoop 内部 catch 后会返回 None → ERROR
        mock_llm = MockLLMClient([])

        # chat_with_tools 抛异常模拟 LLM 失败
        def fail_chat(*args, **kwargs):
            raise RuntimeError("LLM service unavailable")

        mock_llm.chat_with_tools = fail_chat

        orchestrator = AgentOrchestrator(mock_llm, mock_config)
        orchestrator.run_agent(
            agent_type=AgentType.ASSISTANT,
            user_input="你好",
            session_id=session_id,
        )

        # 验证错误事件
        assert "agent_error" in events_collector
        error_data = events_collector["agent_error"][0]
        assert error_data["session_id"] == session_id
        assert error_data["agent_type"] == AgentType.ASSISTANT

    # -------------------------------------------------------------------------
    # 6. UI 接线层：ChatWidget 信号发射验证
    # -------------------------------------------------------------------------

    def test_chat_widget_emits_send_signal(self, in_memory_db):
        """
        ChatWidget.on_send_message() 应发射 send_message_requested 信号，
        携带正确的 session_id、agent_type、user_input。

        注意：此测试需要 PyQt6 QApplication 实例。如果环境无法创建则跳过。
        """
        try:
            from PyQt6.QtWidgets import QApplication
            import sys

            app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError):
            pytest.skip("PyQt6 不可用或无法创建 QApplication")

        from src.ui.widgets.chat_widget import ChatWidget

        widget = ChatWidget()

        # 捕获信号
        received = []
        widget.send_message_requested.connect(
            lambda sid, atype, msg: received.append((sid, atype, msg))
        )

        # 模拟输入文本并发送
        widget.message_input.setPlainText("测试消息")
        widget.on_send_message()

        assert len(received) == 1
        session_id, agent_type, user_input = received[0]
        assert session_id.startswith("ast_")
        assert agent_type == AgentType.ASSISTANT
        assert user_input == "测试消息"

        widget.close()

    # -------------------------------------------------------------------------
    # 7. 带工具选择的会话创建
    # -------------------------------------------------------------------------

    def test_create_session_with_tool_ids(self, in_memory_db):
        """创建会话时指定 tool_ids，应正确持久化"""
        import uuid

        session_id = f"ast_{uuid.uuid4().hex[:12]}"
        tool_ids = ["tool_1", "tool_2"]
        repo = SessionRepository()
        repo.create(
            Session(
                session_id=session_id,
                workflow_id=None,
                agent_type=AgentType.ASSISTANT,
                status="active",
                tool_ids=json.dumps(tool_ids),
            )
        )

        session = repo.get_by_id(session_id)
        assert session is not None
        assert session.get_tool_id_set() == {"tool_1", "tool_2"}
