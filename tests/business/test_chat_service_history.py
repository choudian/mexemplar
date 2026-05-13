import pytest

from src.business.agents.config import AgentType
from src.business.services.chat_service import ChatService, ChatHistoryPage, DisplayChatMessage
from src.data.models_sqlite import Session
from src.data.repositories import SessionRepository
from tests.data.chat_history_test_helpers import (
    create_assistant_session,
    seed_display_messages,
    seed_message,
)


@pytest.fixture()
def session_id():
    return create_assistant_session()


class TestGetDisplayMessagesDTOs:
    def test_returns_chat_history_page(self, session_id):
        seed_display_messages(session_id, count=5)
        result = ChatService().get_display_messages(session_id, limit=10)
        assert isinstance(result, ChatHistoryPage)
        assert isinstance(result.messages, list)
        assert isinstance(result.has_more_before, bool)

    def test_messages_are_display_dtos_without_internal_fields(self, session_id):
        seed_display_messages(session_id, count=3)
        result = ChatService().get_display_messages(session_id, limit=10)
        assert len(result.messages) == 3
        for msg in result.messages:
            assert isinstance(msg, DisplayChatMessage)
            assert hasattr(msg, "sequence")
            assert hasattr(msg, "role")
            assert hasattr(msg, "content")
            assert not hasattr(msg, "is_archived")
            assert not hasattr(msg, "message_type")
            assert not hasattr(msg, "compressed_range")

    def test_dto_fields_values(self, session_id):
        seed_display_messages(session_id, count=2)
        result = ChatService().get_display_messages(session_id, limit=10)
        msg = result.messages[0]
        assert msg.role in ("user", "assistant")
        assert isinstance(msg.sequence, int)
        assert isinstance(msg.content, str)


class TestGetDisplayMessagesPagination:
    def test_default_limit_is_latest_ten(self, session_id):
        seed_display_messages(session_id, count=20)
        result = ChatService().get_display_messages(session_id, limit=10)
        assert len(result.messages) == 10
        assert result.messages[0].sequence == 11

    def test_before_sequence_returns_older_page(self, session_id):
        seed_display_messages(session_id, count=20)
        result = ChatService().get_display_messages(session_id, limit=10, before_sequence=11)
        assert len(result.messages) == 10
        assert result.messages[0].sequence == 1

    def test_has_more_before_true(self, session_id):
        seed_display_messages(session_id, count=20)
        result = ChatService().get_display_messages(session_id, limit=10)
        assert result.has_more_before is True

    def test_has_more_before_false(self, session_id):
        seed_display_messages(session_id, count=5)
        result = ChatService().get_display_messages(session_id, limit=10)
        assert result.has_more_before is False

    def test_next_before_sequence(self, session_id):
        seed_display_messages(session_id, count=20)
        result = ChatService().get_display_messages(session_id, limit=10)
        assert result.next_before_sequence == 11

    def test_filters_internal_messages(self, session_id):
        seed_message(session_id, sequence=1, role="user", content="hello")
        seed_message(session_id, sequence=2, role="tool", content="result")
        seed_message(
            session_id, sequence=3, role="assistant", content="", tool_calls='[{"id":"t1"}]'
        )
        seed_message(session_id, sequence=4, role="summary", content="sum")
        seed_message(
            session_id, sequence=5, role="assistant", content="reply", message_type="compressed"
        )
        seed_message(session_id, sequence=6, role="assistant", content="normal reply")
        result = ChatService().get_display_messages(session_id, limit=10)
        roles = [m.role for m in result.messages]
        assert "tool" not in roles
        assert "summary" not in roles
        assert len(result.messages) == 2

    def test_incremental_display_messages_reuse_display_filter(self, session_id):
        seed_message(session_id, sequence=1, role="user", content="hello")
        seed_message(session_id, sequence=2, role="tool", content="hidden")
        seed_message(session_id, sequence=3, role="assistant", content="old")
        seed_message(
            session_id,
            sequence=4,
            role="assistant",
            content="compressed",
            message_type="compressed",
        )
        seed_message(session_id, sequence=5, role="assistant", content="new")

        result = ChatService().get_display_messages_after(session_id, after_sequence=3)

        assert [(m.sequence, m.content) for m in result] == [(5, "new")]


class TestSessionListAndRename:
    def test_session_list_includes_completed_and_failed_but_excludes_archived(self):
        completed = create_assistant_session("ast_completed")
        failed = create_assistant_session("ast_failed")
        archived = create_assistant_session("ast_archived")
        repo = SessionRepository()
        repo.update_status(completed, "completed")
        repo.update_status(failed, "failed")
        repo.update_status(archived, "archived")

        sessions = ChatService().get_sessions_with_preview()
        listed_ids = {item["session_id"] for item in sessions}

        assert completed in listed_ids
        assert failed in listed_ids
        assert archived not in listed_ids

    def test_rename_session_rejects_non_assistant_without_mutating_title(self):
        session_id = "pm_session_for_rename_guard"
        SessionRepository().create(
            Session(
                session_id=session_id,
                workflow_id="wf_pm",
                agent_type=AgentType.PM,
                status="active",
                title="Original PM title",
            )
        )

        with pytest.raises(KeyError):
            ChatService().rename_session(session_id, "Should not write")

        assert SessionRepository().get_by_id(session_id).title == "Original PM title"
