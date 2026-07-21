import pytest

from src.data.repos.message_repository import MessageRepository
from tests.data.chat_history_test_helpers import (
    create_assistant_session,
    seed_message,
    seed_display_messages,
)


@pytest.fixture()
def session_id():
    return create_assistant_session()


class TestGetDisplayPageLatest:
    def test_returns_latest_ten_in_ascending_sequence(self, session_id):
        seed_display_messages(session_id, count=20)
        repo = MessageRepository()
        page = repo.get_display_page(session_id, limit=10)
        assert len(page) == 10
        assert page[0].sequence == 11
        assert page[-1].sequence == 20

    def test_includes_archived_display_messages(self, session_id):
        seed_display_messages(session_id, count=5, archived_until=3)
        repo = MessageRepository()
        page = repo.get_display_page(session_id, limit=10)
        sequences = [m.sequence for m in page]
        assert 1 in sequences
        assert 2 in sequences
        assert 3 in sequences


class TestGetDisplayPageBeforeSequence:
    def test_returns_older_page(self, session_id):
        seed_display_messages(session_id, count=20)
        repo = MessageRepository()
        page = repo.get_display_page(session_id, limit=10, before_sequence=11)
        assert len(page) == 10
        assert page[0].sequence == 1
        assert page[-1].sequence == 10

    def test_has_more_before_true(self, session_id):
        seed_display_messages(session_id, count=20)
        repo = MessageRepository()
        has_more = repo.has_more_before(session_id, before_sequence=11)
        assert has_more is True

    def test_has_more_before_false(self, session_id):
        seed_display_messages(session_id, count=5)
        repo = MessageRepository()
        has_more = repo.has_more_before(session_id, before_sequence=1)
        assert has_more is False


class TestGetDisplayPageFilters:
    def test_excludes_tool_messages(self, session_id):
        seed_message(session_id, sequence=1, role="user", content="hello")
        seed_message(session_id, sequence=2, role="tool", content="tool result")
        seed_message(session_id, sequence=3, role="assistant", content="reply")
        repo = MessageRepository()
        page = repo.get_display_page(session_id, limit=10)
        roles = [m.role for m in page]
        assert "tool" not in roles

    def test_excludes_summary_messages(self, session_id):
        seed_message(session_id, sequence=1, role="user", content="hello")
        seed_message(session_id, sequence=2, role="summary", content="summary")
        repo = MessageRepository()
        page = repo.get_display_page(session_id, limit=10)
        roles = [m.role for m in page]
        assert "summary" not in roles

    def test_excludes_compressed_messages(self, session_id):
        seed_message(session_id, sequence=1, role="user", content="hello")
        seed_message(
            session_id, sequence=2, role="assistant", content="old", message_type="compressed"
        )
        seed_message(session_id, sequence=3, role="assistant", content="reply")
        repo = MessageRepository()
        page = repo.get_display_page(session_id, limit=10)
        contents = [m.content for m in page]
        assert "old" not in contents

    def test_excludes_empty_content(self, session_id):
        seed_message(session_id, sequence=1, role="user", content="hello")
        seed_message(session_id, sequence=2, role="assistant", content="")
        seed_message(session_id, sequence=3, role="assistant", content=None)
        repo = MessageRepository()
        page = repo.get_display_page(session_id, limit=10)
        assert len(page) == 1
        assert page[0].content == "hello"

    def test_excludes_tool_call_only_assistant(self, session_id):
        seed_message(session_id, sequence=1, role="user", content="hello")
        seed_message(
            session_id, sequence=2, role="assistant", content="", tool_calls='[{"id":"t1"}]'
        )
        repo = MessageRepository()
        page = repo.get_display_page(session_id, limit=10)
        assert len(page) == 1

    def test_get_display_after_reuses_display_filter(self, session_id):
        seed_message(session_id, sequence=1, role="user", content="hello")
        seed_message(session_id, sequence=2, role="tool", content="hidden")
        seed_message(
            session_id, sequence=3, role="assistant", content="old", message_type="compressed"
        )
        seed_message(session_id, sequence=4, role="assistant", content="reply")
        repo = MessageRepository()

        rows = repo.get_display_after(session_id, after_sequence=1)

        assert [(row.sequence, row.content) for row in rows] == [(4, "reply")]


class TestGetDisplayPageValidation:
    def test_rejects_non_positive_limit(self, session_id):
        repo = MessageRepository()
        with pytest.raises(ValueError):
            repo.get_display_page(session_id, limit=0)
        with pytest.raises(ValueError):
            repo.get_display_page(session_id, limit=-1)


def test_latest_assistant_text_can_be_limited_to_a_run_message_window(session_id):
    seed_message(session_id, sequence=1, role="assistant", content="old run")
    seed_message(session_id, sequence=2, role="user", content="new trigger")
    seed_message(session_id, sequence=3, role="assistant", content="new run")
    repo = MessageRepository()

    assert repo.get_latest_assistant_text(session_id, after_sequence=1) == "new run"
    assert repo.get_latest_assistant_text(session_id, after_sequence=3) == ""


def test_tool_message_query_uses_run_window_and_tool_allowlist(session_id):
    seed_message(
        session_id,
        sequence=1,
        role="tool",
        content='{"success": true}',
        tool_name="delegate_to_subagent",
    )
    seed_message(
        session_id,
        sequence=3,
        role="tool",
        content='{"success": true}',
        tool_name="delegate_to_specialist",
    )
    seed_message(
        session_id,
        sequence=4,
        role="tool",
        content='{"success": true}',
        tool_name="unrelated_tool",
    )
    repo = MessageRepository()

    rows = repo.list_tool_messages_after(
        session_id,
        after_sequence=1,
        tool_names={"delegate_to_subagent", "delegate_to_specialist"},
    )

    assert [(row.sequence, row.tool_name) for row in rows] == [(3, "delegate_to_specialist")]
