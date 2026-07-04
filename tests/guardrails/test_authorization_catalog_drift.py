"""
Authorization catalog drift regression tests (P0).

Verifies that DynamicToolManager correctly reflects updated authorization
sets when the session's allowed tools change between agent turns, and that
the prompt catalog and runtime discovery stay consistent.
"""

import pytest

from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager


# ---------------------------------------------------------------------------
# DynamicToolManager.update_authorization
# ---------------------------------------------------------------------------


class TestUpdateAuthorization:
    """Tests for DynamicToolManager.update_authorization drift detection."""

    def test_no_change_returns_false(self):
        mgr = DynamicToolManager(allowed_tool_ids={"a", "b"})
        assert mgr.update_authorization(allowed_tool_ids={"a", "b"}) is False

    def test_tool_ids_change_returns_true(self):
        mgr = DynamicToolManager(allowed_tool_ids={"a", "b"})
        assert mgr.update_authorization(allowed_tool_ids={"a", "b", "c"}) is True

    def test_composition_ids_change_returns_true(self):
        mgr = DynamicToolManager(
            allowed_tool_ids=None,
            allowed_composition_ids={"comp_1"},
        )
        assert mgr.update_authorization(
            allowed_tool_ids=None,
            allowed_composition_ids={"comp_1", "comp_2"},
        ) is True

    def test_tool_ids_removed_returns_true(self):
        mgr = DynamicToolManager(allowed_tool_ids={"a", "b"})
        assert mgr.update_authorization(allowed_tool_ids={"a"}) is True

    def test_none_vs_set_returns_true(self):
        mgr = DynamicToolManager(allowed_tool_ids=None)
        assert mgr.update_authorization(allowed_tool_ids={"a"}) is True

    def test_set_vs_none_returns_true(self):
        mgr = DynamicToolManager(allowed_tool_ids={"a"})
        assert mgr.update_authorization(allowed_tool_ids=None) is True

    def test_update_mutates_internal_state(self):
        mgr = DynamicToolManager(allowed_tool_ids={"a"})
        mgr.update_authorization(allowed_tool_ids={"a", "b"})
        assert mgr.allowed_tool_ids == {"a", "b"}

    def test_composition_ids_updated_in_internal_state(self):
        mgr = DynamicToolManager(allowed_composition_ids={"c1"})
        mgr.update_authorization(allowed_composition_ids={"c1", "c2"})
        assert mgr.allowed_composition_ids == {"c1", "c2"}


# ---------------------------------------------------------------------------
# Authorization drift in cached manager (orchestrator-level contract)
# ---------------------------------------------------------------------------


class TestAuthorizationDriftInCache:
    """Tests for the get_or_create_dynamic_manager authorization drift fix.

    These test the contract that the orchestrator's cache respects
    authorization changes on cache hit, rather than silently discarding
    new allowed_ids.
    """

    def _make_orchestrator_cache(self):
        """Create a minimal object that implements the cache interface."""
        from collections import OrderedDict
        import threading

        class _FakeOrchestratorCache:
            def __init__(self):
                self._dynamic_managers: OrderedDict[str, DynamicToolManager] = OrderedDict()
                self._dynamic_managers_lock = threading.Lock()
                self._MAX_DYNAMIC_MANAGERS = 20

            def get_or_create_dynamic_manager(
                self,
                session_id: str,
                allowed_ids: set[str] | None,
                allowed_composition_ids: set[str] | None = None,
            ) -> DynamicToolManager:
                with self._dynamic_managers_lock:
                    if session_id in self._dynamic_managers:
                        self._dynamic_managers.move_to_end(session_id)
                        manager = self._dynamic_managers[session_id]
                        if manager.update_authorization(allowed_ids, allowed_composition_ids):
                            manager.get_activated_tools()
                    else:
                        self._dynamic_managers[session_id] = DynamicToolManager(
                            allowed_ids,
                            allowed_composition_ids=allowed_composition_ids,
                        )
                        while len(self._dynamic_managers) > self._MAX_DYNAMIC_MANAGERS:
                            self._dynamic_managers.popitem(last=False)
                    return self._dynamic_managers[session_id]

        return _FakeOrchestratorCache()

    def test_cache_hit_updates_tool_ids(self):
        cache = self._make_orchestrator_cache()
        # First call: only tool A authorized
        mgr1 = cache.get_or_create_dynamic_manager("sess1", {"tool_a"})
        assert mgr1.allowed_tool_ids == {"tool_a"}

        # Second call: tool B also authorized — cache hit should update
        mgr2 = cache.get_or_create_dynamic_manager("sess1", {"tool_a", "tool_b"})
        assert mgr2 is mgr1  # same object
        assert mgr2.allowed_tool_ids == {"tool_a", "tool_b"}

    def test_cache_hit_updates_composition_ids(self):
        cache = self._make_orchestrator_cache()
        mgr1 = cache.get_or_create_dynamic_manager("sess1", None)
        assert mgr1.allowed_composition_ids is None

        mgr2 = cache.get_or_create_dynamic_manager(
            "sess1", None, allowed_composition_ids={"comp_a"}
        )
        assert mgr2 is mgr1
        assert mgr2.allowed_composition_ids == {"comp_a"}

    def test_cache_miss_creates_new_manager(self):
        cache = self._make_orchestrator_cache()
        mgr = cache.get_or_create_dynamic_manager("sess1", {"tool_a"})
        assert mgr.allowed_tool_ids == {"tool_a"}

        mgr2 = cache.get_or_create_dynamic_manager("sess2", {"tool_b"})
        assert mgr2 is not mgr
        assert mgr2.allowed_tool_ids == {"tool_b"}

    def test_authorization_revocation_reflects_in_allowed_set(self):
        cache = self._make_orchestrator_cache()
        mgr1 = cache.get_or_create_dynamic_manager("sess1", {"tool_a", "tool_b"})
        assert mgr1.allowed_tool_ids == {"tool_a", "tool_b"}

        # Revoke tool_b
        mgr2 = cache.get_or_create_dynamic_manager("sess1", {"tool_a"})
        assert mgr2.allowed_tool_ids == {"tool_a"}

    def test_identical_authorization_is_noop(self):
        cache = self._make_orchestrator_cache()
        mgr1 = cache.get_or_create_dynamic_manager("sess1", {"tool_a"})
        # Identical call — should not change anything
        mgr2 = cache.get_or_create_dynamic_manager("sess1", {"tool_a"})
        assert mgr2 is mgr1
        assert mgr2.allowed_tool_ids == {"tool_a"}


# ---------------------------------------------------------------------------
# _is_allowed_tool / _is_allowed_composition respect updated auth
# ---------------------------------------------------------------------------


class TestFilteringAfterAuthorizationUpdate:
    """Verify that filtering methods use the latest authorization state."""

    def _make_published_tool(self, tool_id: str, tool_name: str = "test"):
        """Create a minimal tool-like object for _is_allowed_tool checks."""

        class _FakeTool:
            pass

        tool = _FakeTool()
        tool.tool_id = tool_id
        tool.tool_name = tool_name
        tool.status = "published"
        return tool

    def _make_published_composition(
        self,
        composition_id: str,
        member_tool_ids: set[str] | None = None,
    ):
        """Create a minimal composition-like object for _is_allowed_composition."""

        class _FakeMember:
            pass

        class _FakeComposition:
            pass

        comp = _FakeComposition()
        comp.composition_id = composition_id
        comp.status = "published"
        comp.assistant_enabled = True
        comp.needs_review = False
        members = []
        for tid in member_tool_ids or set():
            m = _FakeMember()
            m.tool_id = tid
            members.append(m)
        comp.members = members
        return comp

    def test_newly_authorized_tool_passes_filter(self):
        mgr = DynamicToolManager(allowed_tool_ids={"tool_a"})
        tool_b = self._make_published_tool("tool_b")
        assert mgr._is_allowed_tool(tool_b) is False

        mgr.update_authorization(allowed_tool_ids={"tool_a", "tool_b"})
        assert mgr._is_allowed_tool(tool_b) is True

    def test_revoked_tool_fails_filter(self):
        mgr = DynamicToolManager(allowed_tool_ids={"tool_a", "tool_b"})
        tool_b = self._make_published_tool("tool_b")
        assert mgr._is_allowed_tool(tool_b) is True

        mgr.update_authorization(allowed_tool_ids={"tool_a"})
        assert mgr._is_allowed_tool(tool_b) is False

    def test_newly_authorized_composition_passes_filter(self):
        mgr = DynamicToolManager(
            allowed_tool_ids={"tool_a"},
            allowed_composition_ids={"comp_a"},
        )
        comp_b = self._make_published_composition("comp_b", {"tool_a"})
        assert mgr._is_allowed_composition(comp_b) is False

        mgr.update_authorization(
            allowed_tool_ids={"tool_a"},
            allowed_composition_ids={"comp_a", "comp_b"},
        )
        assert mgr._is_allowed_composition(comp_b) is True

    def test_composition_leaked_by_member_subset_without_explicit_deny(self):
        """When allowed_composition_ids is None, a composition whose member tools
        are all authorized is allowed — this is the current design (composition
        auth is derived from member tool auth when no explicit composition allowlist)."""
        mgr = DynamicToolManager(allowed_tool_ids={"tool_a", "tool_b"})
        comp = self._make_published_composition("comp_x", {"tool_a", "tool_b"})
        # allowed_composition_ids is None => all published compositions pass
        # the composition_id check, then member tool check applies
        assert mgr._is_allowed_composition(comp) is True

    def test_composition_blocked_by_member_not_in_tool_allowlist(self):
        """A composition with an unauthorized member tool should be blocked
        even when allowed_composition_ids is None."""
        mgr = DynamicToolManager(allowed_tool_ids={"tool_a"})
        comp = self._make_published_composition("comp_x", {"tool_a", "tool_b"})
        assert mgr._is_allowed_composition(comp) is False


# ---------------------------------------------------------------------------
# Session.get_composition_id_set
# ---------------------------------------------------------------------------


class TestSessionGetCompositionIdSet:
    """Verify Session.get_composition_id_set extracts composition_id correctly."""

    def _make_session(self, tool_ids_json: str | None):
        """Minimal mock-like Session with just tool_ids set."""
        from unittest.mock import MagicMock

        sess = MagicMock()
        sess.tool_ids = tool_ids_json

        # Use the real method implementation
        from src.data.models_sqlite import Session

        sess.get_composition_id_set = Session.get_composition_id_set.__get__(sess, Session)
        return sess

    def test_dict_with_composition_id(self):
        """Trial session dict format returns composition_id set."""
        import json

        sess = self._make_session(
            json.dumps({"composition_id": "comp_abc", "member_tool_ids": ["t1", "t2"]})
        )
        result = sess.get_composition_id_set()
        assert result == {"comp_abc"}

    def test_dict_without_composition_id(self):
        """Dict without composition_id returns None (full access)."""
        import json

        sess = self._make_session(json.dumps({"member_tool_ids": ["t1"]}))
        result = sess.get_composition_id_set()
        assert result is None

    def test_list_format_returns_none(self):
        """List format (non-trial session) returns None."""
        import json

        sess = self._make_session(json.dumps(["t1", "t2"]))
        result = sess.get_composition_id_set()
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty tool_ids returns None."""
        sess = self._make_session("")
        result = sess.get_composition_id_set()
        assert result is None

    def test_none_returns_none(self):
        """None tool_ids returns None."""
        sess = self._make_session(None)
        result = sess.get_composition_id_set()
        assert result is None
