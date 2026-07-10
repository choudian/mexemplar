"""ProposalService 讨论会话行为测试（028 T009/T016/T018）。"""

from __future__ import annotations

from unittest.mock import patch

from src.business.self_improvement.proposal_service import ProposalService
from src.data.repos.improvement_proposal_repository import ImprovementProposalRepository
from src.data.repositories import MessageRepository, SessionRepository

_FINDING = [
    {
        "type": "效率",
        "what": "重复抓取同一 URL",
        "evidence": "两次读取同一页面",
        "severity": "med",
        "suggestion": "增加请求级缓存",
        "worth_changing": True,
    },
]


def _make_proposal(svc: ProposalService, review_id: str = "rev_disc") -> str:
    svc.generate_from_review(review_id, _FINDING)
    proposals = svc.list_proposals()
    assert proposals, "fixture proposal missing"
    return proposals[0]["id"]


def _session_count() -> int:
    from src.business.agents.config import AgentType

    return len(SessionRepository().get_by_agent_type(AgentType.ASSISTANT))


class TestDiscussionCreate:
    def test_first_call_creates_session_with_opening_message(self, in_memory_db):
        svc = ProposalService()
        proposal_id = _make_proposal(svc)

        result = svc.get_or_create_discussion_session(proposal_id)

        assert result is not None
        assert result["created"] is True
        session_id = result["sessionId"]

        session = SessionRepository().get_by_id(session_id)
        assert session is not None
        assert session.title.startswith("讨论：重复抓取同一 URL"[:10])

        messages = MessageRepository().get_all(session_id)
        assert len(messages) == 1
        opening = messages[0]
        assert opening.role == "assistant"
        assert "问题：重复抓取同一 URL" in opening.content
        assert "证据：两次读取同一页面" in opening.content
        assert "建议：增加请求级缓存" in opening.content
        assert "严重度：中" in opening.content

    def test_opening_includes_user_supplement(self, in_memory_db):
        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        svc.approve(proposal_id, supplement="优先覆盖缓存层")

        result = svc.get_or_create_discussion_session(proposal_id)

        messages = MessageRepository().get_all(result["sessionId"])
        assert "用户补充说明：优先覆盖缓存层" in messages[0].content

    def test_no_model_call_on_open(self, in_memory_db):
        """零模型调用：打开讨论不得触碰 AgentLoop/LLM（FR-426）。"""
        svc = ProposalService()
        proposal_id = _make_proposal(svc)

        with patch(
            "src.business.agents.agent_loop.AgentLoop.run",
            side_effect=AssertionError("discussion open must not run AgentLoop"),
        ):
            result = svc.get_or_create_discussion_session(proposal_id)
        assert result["created"] is True

    def test_second_call_returns_same_session(self, in_memory_db):
        svc = ProposalService()
        proposal_id = _make_proposal(svc)

        first = svc.get_or_create_discussion_session(proposal_id)
        count_after_first = _session_count()
        second = svc.get_or_create_discussion_session(proposal_id)

        assert second["sessionId"] == first["sessionId"]
        assert second["created"] is False
        assert _session_count() == count_after_first  # 会话数不再增长

    def test_unknown_proposal_returns_none(self, in_memory_db):
        assert ProposalService().get_or_create_discussion_session("prop_missing") is None

    def test_binding_visible_in_dto(self, in_memory_db):
        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        result = svc.get_or_create_discussion_session(proposal_id)

        dto = svc.get_proposal(proposal_id)
        assert dto["discussionSessionId"] == result["sessionId"]


class TestDiscussionPersistenceAndSelfHeal:
    def test_binding_survives_new_repository_instance(self, in_memory_db):
        """跨进程持久语义：新 Repository 实例读取仍返回同一绑定。"""
        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        first = svc.get_or_create_discussion_session(proposal_id)

        with ImprovementProposalRepository() as fresh_repo:
            row = fresh_repo.get_by_id(proposal_id)
            assert row.discussion_session_id == first["sessionId"]

        again = ProposalService().get_or_create_discussion_session(proposal_id)
        assert again["sessionId"] == first["sessionId"]
        assert again["created"] is False

    def test_archived_session_triggers_self_heal(self, in_memory_db):
        """绑定会话被删除（归档）后：新建会话并换绑（FR-423）。"""
        from src.business.services.chat_service import ChatService

        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        first = svc.get_or_create_discussion_session(proposal_id)

        assert ChatService().archive_session(first["sessionId"]) is True

        healed = svc.get_or_create_discussion_session(proposal_id)
        assert healed["created"] is True
        assert healed["sessionId"] != first["sessionId"]

        with ImprovementProposalRepository() as repo:
            row = repo.get_by_id(proposal_id)
            assert row.discussion_session_id == healed["sessionId"]

        # 新会话同样带开场消息
        messages = MessageRepository().get_all(healed["sessionId"])
        assert len(messages) == 1
        assert "问题：重复抓取同一 URL" in messages[0].content

    def test_missing_session_row_triggers_self_heal(self, in_memory_db):
        """绑定指向不存在的会话行（异常脏数据）同样自愈。"""
        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        with ImprovementProposalRepository() as repo:
            repo.rebind_discussion_session(proposal_id, "ast_ghost_missing")

        healed = svc.get_or_create_discussion_session(proposal_id)
        assert healed["created"] is True
        assert healed["sessionId"] != "ast_ghost_missing"


class TestDiscussionTerminalStates:
    def test_done_proposal_opening_includes_outcome(self, in_memory_db):
        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        svc.approve(proposal_id)
        with ImprovementProposalRepository() as repo:
            repo.mark_in_progress(proposal_id, graph_id="g1", worktree_path="w", branch_name="b28")
            repo.mark_done(proposal_id, tests_passed=True, summary="已加缓存，12 个测试通过")

        result = svc.get_or_create_discussion_session(proposal_id)

        opening = MessageRepository().get_all(result["sessionId"])[0].content
        assert "当前状态：已完成" in opening
        assert "实施结果：已加缓存，12 个测试通过" in opening
        assert "测试结论：通过" in opening

    def test_failed_proposal_opening_includes_error(self, in_memory_db):
        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        svc.approve(proposal_id)
        with ImprovementProposalRepository() as repo:
            repo.mark_in_progress(proposal_id, graph_id="g2", worktree_path="w", branch_name="b28")
            repo.mark_failed(proposal_id, error="执行体越界被拒")

        result = svc.get_or_create_discussion_session(proposal_id)

        opening = MessageRepository().get_all(result["sessionId"])[0].content
        assert "当前状态：实施失败" in opening
        assert "失败原因：执行体越界被拒" in opening

    def test_rejected_proposal_can_discuss(self, in_memory_db):
        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        svc.reject(proposal_id)

        result = svc.get_or_create_discussion_session(proposal_id)
        assert result["created"] is True
        opening = MessageRepository().get_all(result["sessionId"])[0].content
        assert "当前状态：已拒绝" in opening


class TestDiscussionZeroSideEffect:
    def test_open_discussion_changes_no_proposal_state(self, in_memory_db):
        """FR-425：讨论入口唯一允许的提案变更是绑定字段本身。"""
        svc = ProposalService()
        proposal_id = _make_proposal(svc)
        before = svc.get_proposal(proposal_id)

        svc.get_or_create_discussion_session(proposal_id)

        after = svc.get_proposal(proposal_id)
        assert after["status"] == before["status"] == "pending_review"
        assert after["graphId"] is None
        assert after["worktreeAvailable"] is False
        assert after["branchName"] is None

    def test_open_discussion_never_touches_bridge(self, in_memory_db):
        """讨论路径不得进入 proposal_bridge 实施桥（不建 worktree/task graph）。"""
        svc = ProposalService()
        proposal_id = _make_proposal(svc)

        with (
            patch(
                "src.business.self_improvement.proposal_bridge.trigger_implementation_async",
                side_effect=AssertionError("discussion must not trigger implementation"),
            ),
            patch(
                "src.business.self_improvement.proposal_bridge._build_implementation_graph",
                side_effect=AssertionError("discussion must not build task graph"),
            ),
        ):
            result = svc.get_or_create_discussion_session(proposal_id)
        assert result is not None


def test_discussion_session_is_ordinary_assistant_session(in_memory_db):
    """FR-424：讨论会话就是普通助理会话——agent_type/状态/可归档语义一致。"""
    from src.business.agents.config import AgentType
    from src.business.services.chat_service import ChatService

    svc = ProposalService()
    proposal_id = _make_proposal(svc)
    result = svc.get_or_create_discussion_session(proposal_id)

    session = SessionRepository().get_by_id(result["sessionId"])
    assert session.agent_type == AgentType.ASSISTANT
    assert session.status == "active"
    # 出现在普通会话预览列表里
    previews = ChatService().get_sessions_with_preview()
    assert any(p["session_id"] == result["sessionId"] for p in previews)
