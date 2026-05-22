"""
retrieve_archive 助理工具测试 (T051)

覆盖：
- retrieve_archive 工具 schema 定义
- retrieve_archive 工具 handler 调用 RetrievalService
- 空查询返回友好提示
- 检索结果格式化为可读文本
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


class TestRetrieveArchiveToolSchema:
    """验证 retrieve_archive 工具的 schema 定义。"""

    def test_retrieve_archive_schema_exists(self):
        """retrieve_archive schema 常量应存在。"""
        from src.business.agents.tools.assistant_tools import RETRIEVE_ARCHIVE_SCHEMA

        assert RETRIEVE_ARCHIVE_SCHEMA is not None
        schema = RETRIEVE_ARCHIVE_SCHEMA
        func = schema.get("function", schema)
        assert func["name"] == "retrieve_archive"

    def test_retrieve_archive_schema_requires_query(self):
        """retrieve_archive schema 应要求 query 参数。"""
        from src.business.agents.tools.assistant_tools import RETRIEVE_ARCHIVE_SCHEMA

        schema = RETRIEVE_ARCHIVE_SCHEMA
        func = schema.get("function", schema)
        assert "query" in func["parameters"]["required"]

    def test_retrieve_archive_tool_definition_exists(self):
        """RETRIEVE_ARCHIVE ToolDefinition 应存在。"""
        from src.business.agents.tools.assistant_tools import RETRIEVE_ARCHIVE

        assert RETRIEVE_ARCHIVE is not None
        assert RETRIEVE_ARCHIVE.name == "retrieve_archive"
        assert RETRIEVE_ARCHIVE.handler is not None


class TestRetrieveArchiveHandler:
    """验证 retrieve_archive handler 行为。"""

    def test_handler_calls_retrieval_service(self):
        """handler 应调用 RetrievalService.retrieve_archive。"""
        from src.business.agents.tools.assistant_tools import RETRIEVE_ARCHIVE

        with patch("src.business.agents.tools.assistant_tools.RetrievalService") as MockService:
            mock_service_instance = MagicMock()
            mock_service_instance.retrieve_archive.return_value = [
                {
                    "entry_id": "archive-1",
                    "content": "用户之前讨论过预算审核",
                    "zone": "archive",
                    "status": "active",
                    "relevance_score": 0.85,
                    "composite_score": 2.1,
                    "invalidation_factor": 1.0,
                },
            ]
            MockService.return_value = mock_service_instance

            result = RETRIEVE_ARCHIVE.handler(query="预算")
            result_data = json.loads(result)

            assert result_data["success"] is True
            assert len(result_data["results"]) == 1
            assert "预算" in result_data["results"][0]["content"]
            assert result_data["results"][0]["invalidation_factor"] == 1.0
            mock_service_instance.retrieve_archive.assert_called_once_with("预算")

    def test_handler_empty_query_returns_message(self):
        """空查询应返回友好提示而非调用服务。"""
        from src.business.agents.tools.assistant_tools import RETRIEVE_ARCHIVE

        with patch("src.business.agents.tools.assistant_tools.RetrievalService"):
            result = RETRIEVE_ARCHIVE.handler(query="")
            result_data = json.loads(result)

            assert result_data["success"] is False


class TestFailureRetrievalAndInvalidationTools:
    """US4: 失败区检索与记忆失效工具。"""

    def test_retrieve_failure_zone_calls_service(self):
        from src.business.agents.tools.assistant_tools import RETRIEVE_FAILURE_ZONE

        with patch("src.business.agents.tools.assistant_tools.RetrievalService") as MockService:
            service = MagicMock()
            service.retrieve_failure_zone.return_value = [
                {
                    "entry_id": "failure-1",
                    "content": "过去尝试直接删除配置失败",
                    "reason": "需要先备份",
                    "composite_score": 0.8,
                    "invalidation_factor": 0.5,
                }
            ]
            MockService.return_value = service

            result = json.loads(RETRIEVE_FAILURE_ZONE.handler(context="删除配置"))

            assert result["success"] is True
            assert result["entries"][0]["entry_id"] == "failure-1"
            assert result["entries"][0]["invalidation_factor"] == 0.5
            service.retrieve_failure_zone.assert_called_once_with("删除配置")

    def test_invalidate_memory_entry_uses_current_context_window(self):
        from src.business.agents.tools.assistant_tools import create_invalidate_memory_entry_handler

        with (
            patch("src.business.brain.context_builder.BrainContextBuilder") as MockBuilder,
            patch("src.business.agents.tools.assistant_tools.RetrievalService") as MockService,
        ):
            MockBuilder.return_value.build_context.return_value.injected_entry_ids = ["entry-1"]
            service = MagicMock()
            service.invalidate_memory_entry.return_value = {
                "success": True,
                "entry_id": "entry-1",
                "message": "Entry invalidated",
            }
            MockService.return_value = service

            handler = create_invalidate_memory_entry_handler("session-1")
            result = json.loads(handler(entry_id="entry-1", reason="用户纠正了这条记忆"))

            assert result["success"] is True
            service.invalidate_memory_entry.assert_called_once_with(
                "entry-1",
                "用户纠正了这条记忆",
                current_context_entry_ids=["entry-1"],
            )

    def test_proactive_invalidation_result_requires_disclosure(self):
        from src.business.agents.tools.assistant_tools import create_invalidate_memory_entry_handler

        with (
            patch("src.business.brain.context_builder.BrainContextBuilder") as MockBuilder,
            patch("src.business.agents.tools.assistant_tools.RetrievalService") as MockService,
        ):
            MockBuilder.return_value.build_context.return_value.injected_entry_ids = ["entry-1"]
            service = MagicMock()
            service.invalidate_memory_entry.return_value = {
                "success": True,
                "entry_id": "entry-1",
                "message": "Entry invalidated",
            }
            MockService.return_value = service

            handler = create_invalidate_memory_entry_handler("session-1")
            result = json.loads(
                handler(
                    entry_id="entry-1",
                    reason="当前对话显示这条记忆已不成立",
                    invalidation_type="proactive",
                )
            )

            assert result["requires_user_disclosure"] is True
            assert "reply_to_user" in result["disclosure_instruction"]

    def test_invalidate_memory_entry_allows_explicitly_retrieved_entries(self):
        from src.business.agents.tools.assistant_tools import (
            create_invalidate_memory_entry_handler,
            create_retrieve_archive_handler,
        )

        session_id = "session-retrieved-entry"
        with patch("src.business.agents.tools.assistant_tools.RetrievalService") as MockService:
            service = MagicMock()
            service.retrieve_archive.return_value = [
                {
                    "entry_id": "archive-1",
                    "content": "用户之前讨论过预算审核",
                    "zone": "archive",
                    "status": "active",
                }
            ]
            MockService.return_value = service
            retrieve = create_retrieve_archive_handler(session_id)
            json.loads(retrieve(query="预算"))

        with (
            patch("src.business.brain.context_builder.BrainContextBuilder") as MockBuilder,
            patch("src.business.agents.tools.assistant_tools.RetrievalService") as MockService,
        ):
            MockBuilder.return_value.build_context.return_value.injected_entry_ids = []
            service = MagicMock()
            service.invalidate_memory_entry.return_value = {
                "success": True,
                "entry_id": "archive-1",
                "message": "Entry invalidated",
            }
            MockService.return_value = service

            handler = create_invalidate_memory_entry_handler(session_id)
            result = json.loads(handler(entry_id="archive-1", reason="旧信息过时"))

            assert result["success"] is True
            allowed_ids = service.invalidate_memory_entry.call_args.kwargs[
                "current_context_entry_ids"
            ]
            assert "archive-1" in allowed_ids

    def test_handler_no_results_returns_message(self):
        """无匹配结果时返回提示。"""
        from src.business.agents.tools.assistant_tools import RETRIEVE_ARCHIVE

        with patch("src.business.agents.tools.assistant_tools.RetrievalService") as MockService:
            mock_service_instance = MagicMock()
            mock_service_instance.retrieve_archive.return_value = []
            MockService.return_value = mock_service_instance

            result = RETRIEVE_ARCHIVE.handler(query="不存在的话题")
            result_data = json.loads(result)

            assert result_data["success"] is True
            assert result_data["results"] == []
            assert result_data.get("message") is not None

    def test_handler_service_error_returns_error(self):
        """服务异常时应返回错误信息。"""
        from src.business.agents.tools.assistant_tools import RETRIEVE_ARCHIVE

        with patch("src.business.agents.tools.assistant_tools.RetrievalService") as MockService:
            MockService.side_effect = RuntimeError("DB error")

            result = RETRIEVE_ARCHIVE.handler(query="test")
            result_data = json.loads(result)

            assert result_data["success"] is False
