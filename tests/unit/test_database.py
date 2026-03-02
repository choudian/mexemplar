"""
数据库模块单元测试
"""

import pytest
import tempfile
import os
from pathlib import Path

from src.data.repositories import ToolRepository, TaskExecutionRepository, ConversationRepository
from src.data.models_sqlite import Tool as ToolModel, TaskExecution as TaskExecutionModel, Conversation as ConversationModel
from src.data.sqlalchemy_manager import SQLAlchemyManager


@pytest.fixture
def temp_db():
    """创建临时数据库"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    manager = SQLAlchemyManager(db_path)
    manager.initialize()

    yield manager

    # 清理
    manager.close()
    if os.path.exists(db_path):
        os.remove(db_path)


def test_tool_repository(temp_db):
    """测试工具仓库"""
    import uuid
    session = temp_db.get_session()
    repo = ToolRepository(session)

    # 创建工具（确保必需字段有值，包括 tool_id）
    tool = ToolModel(
        tool_id=str(uuid.uuid4()),
        tool_name="Test Tool",
        description="This is a test tool",
        parameters=[{"name": "keyword", "type": "string"}],
        steps=[{"action": "click", "target": "button"}],
        execution_code="def test(): pass",
        code_language="python",
        code_version="1.0",
        execution_strategy="browser",
        source="test",
        trial_count=0,
    )

    created_tool = repo.create(tool)
    assert created_tool.tool_id == tool.tool_id

    # 获取工具
    retrieved_tool = repo.get_by_id(tool.tool_id)
    assert retrieved_tool is not None
    assert retrieved_tool.tool_name == "Test Tool"
    assert retrieved_tool.execution_code == "def test(): pass"
    assert retrieved_tool.execution_strategy == "browser"

    # 更新工具
    retrieved_tool.tool_name = "Updated Tool"
    updated_tool = repo.update(retrieved_tool)
    assert updated_tool.tool_name == "Updated Tool"

    # 删除工具
    deleted = repo.delete(tool.tool_id)
    assert deleted is True

    # 验证已删除
    retrieved_tool = repo.get_by_id(tool.tool_id)
    assert retrieved_tool is None

    session.close()


def test_task_execution_repository(temp_db):
    """测试任务执行仓库"""
    import uuid
    session = temp_db.get_session()
    tool_repo = ToolRepository(session)
    execution_repo = TaskExecutionRepository(session)

    # 先创建一个工具
    tool = ToolModel(
        tool_id=str(uuid.uuid4()),
        tool_name="Test Tool",
        parameters=[],
        steps=[],
        execution_code="def test(): pass",
        code_language="python",
    )
    tool_repo.create(tool)

    # 创建执行记录（提供 execution_id）
    execution = TaskExecutionModel(
        execution_id=str(uuid.uuid4()),
        tool_id=tool.tool_id,
        status="success",
        parameters={"keyword": "test"},
        result={"price": "$100"},
    )

    created_execution = execution_repo.create(execution)
    assert created_execution.execution_id == execution.execution_id

    # 获取执行记录
    retrieved_execution = execution_repo.get_by_id(execution.execution_id)
    assert retrieved_execution is not None
    assert retrieved_execution.status == "success"

    session.close()


def test_conversation_repository(temp_db):
    """测试对话仓库"""
    import uuid
    session = temp_db.get_session()
    repo = ConversationRepository(session)

    # 创建对话（提供 conversation_id）
    conversation = ConversationModel(
        conversation_id=str(uuid.uuid4()),
        user_message="Help me check price",
        assistant_response="OK, searching now",
        parameters_extracted={"keyword": "keyboard"},
    )

    created_conv = repo.create(conversation)
    assert created_conv.conversation_id == conversation.conversation_id

    # 获取对话记录
    retrieved_conv = repo.get_by_id(conversation.conversation_id)
    assert retrieved_conv is not None
    assert retrieved_conv.user_message == "Help me check price"

    session.close()
