import pytest

from src.business.services.chat_service import ChatService, ChatHistoryPage, DisplayChatMessage
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
        seed_message(session_id, sequence=3, role="assistant", content="", tool_calls='[{"id":"t1"}]')
        seed_message(session_id, sequence=4, role="summary", content="sum")
        seed_message(session_id, sequence=5, role="assistant", content="reply", message_type="compressed")
        seed_message(session_id, sequence=6, role="assistant", content="normal reply")
        result = ChatService().get_display_messages(session_id, limit=10)
        roles = [m.role for m in result.messages]
        assert "tool" not in roles
        assert "summary" not in roles
        assert len(result.messages) == 2
