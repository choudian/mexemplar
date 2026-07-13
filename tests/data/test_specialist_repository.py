"""
T064: SpecialistRepository persistence tests

Tests for:
- Create specialist + initial version record
- Read specialist by ID and by name
- Update specialist creates new version
- Delete specialist and its versions
- List specialists with active_only filter
- Version history retrieval
"""

import json
import pytest

from src.data.repos.specialist_repository import SpecialistRepository
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


def _create_specialist_via_repo(
    repo: SpecialistRepository,
    name="测试专员",
    description="测试描述",
    role_definition="测试角色",
    tool_whitelist=None,
    origin="user_conversation",
    reason="测试",
) -> str:
    """Helper: 通过 repo 创建专员并返回 specialist_id"""
    if tool_whitelist is None:
        tool_whitelist = ["tool_a"]
    return repo.create_specialist(
        name=name,
        description=description,
        role_definition=role_definition,
        tool_whitelist=tool_whitelist,
        origin=origin,
        reason=reason,
    )


# ═══════════════════════════════════════════════
# Create
# ═══════════════════════════════════════════════


class TestCreateSpecialist:
    def test_create_returns_specialist_id(self, in_memory_db):
        """create_specialist 返回 specialist_id"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo)

        assert sid is not None
        assert len(sid) == 50

    def test_create_persists_specialist(self, in_memory_db):
        """创建后可以查到专员"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo, name="持久化测试")

        specialist = repo.get_specialist(sid)
        assert specialist is not None
        assert specialist.name == "持久化测试"

    def test_create_stores_whitelist_as_json(self, in_memory_db):
        """白名单以 JSON 字符串存储"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo, tool_whitelist=["tool_a", "tool_b"])

        specialist = repo.get_specialist(sid)
        whitelist = json.loads(specialist.tool_whitelist)
        assert whitelist == ["tool_a", "tool_b"]

    def test_create_versions_skill_composition_assignments(self, in_memory_db):
        repo = SpecialistRepository()

        specialist_id = repo.create_specialist(
            name="外部编码专员",
            description="处理正式编码任务",
            role_definition="使用已装备的技能组合完成编码",
            tool_whitelist=[],
            composition_ids=["comp_builtin_external_coding"],
            origin="user_management_ui",
            reason="测试技能组合装备",
        )

        specialist = repo.get_specialist(specialist_id)
        versions = repo.get_version_history(specialist_id)
        assert json.loads(specialist.composition_ids) == ["comp_builtin_external_coding"]
        assert json.loads(versions[0].composition_ids) == ["comp_builtin_external_coding"]

    def test_create_initial_version(self, in_memory_db):
        """创建专员时自动创建 version 1"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo)

        versions = repo.get_version_history(sid)
        assert len(versions) == 1
        assert versions[0].version == 1

    def test_create_sets_origin_and_reason(self, in_memory_db):
        """创建时设置 origin 和 reason"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(
            repo,
            origin="user_conversation",
            reason="测试原因",
        )

        specialist = repo.get_specialist(sid)
        assert specialist.origin == "user_conversation"
        assert specialist.reason == "测试原因"


# ═══════════════════════════════════════════════
# Read
# ═══════════════════════════════════════════════


class TestReadSpecialist:
    def test_get_by_id(self, in_memory_db):
        """按 ID 查询专员"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo, name="ID测试")

        found = repo.get_specialist(sid)
        assert found is not None
        assert found.name == "ID测试"

    def test_get_by_name(self, in_memory_db):
        """按名称查询专员"""
        repo = SpecialistRepository()
        _create_specialist_via_repo(repo, name="名称测试")

        found = repo.get_specialist_by_name("名称测试")
        assert found is not None
        assert found.name == "名称测试"

    def test_get_nonexistent_returns_none(self, in_memory_db):
        """查询不存在的专员返回 None"""
        repo = SpecialistRepository()

        assert repo.get_specialist("nonexistent") is None
        assert repo.get_specialist_by_name("nonexistent") is None


# ═══════════════════════════════════════════════
# Update
# ═══════════════════════════════════════════════


class TestUpdateSpecialist:
    def test_update_creates_new_version(self, in_memory_db):
        """更新专员创建新版本"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo)

        repo.update_specialist(
            sid,
            description="更新后的描述",
            changed_by="user",
            change_reason="测试更新",
        )

        specialist = repo.get_specialist(sid)
        assert specialist.current_version == 2
        assert specialist.description == "更新后的描述"

        versions = repo.get_version_history(sid)
        assert len(versions) == 2

    def test_update_preserves_unmodified_fields(self, in_memory_db):
        """更新时未修改的字段保持不变"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(
            repo,
            name="保留测试",
            role_definition="原始角色",
        )

        repo.update_specialist(
            sid,
            description="新描述",
            changed_by="user",
        )

        specialist = repo.get_specialist(sid)
        assert specialist.name == "保留测试"
        assert specialist.role_definition == "原始角色"
        assert specialist.description == "新描述"

    def test_update_versions_skill_composition_assignments(self, in_memory_db):
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo)

        repo.update_specialist(
            sid,
            composition_ids=["comp_builtin_external_coding"],
            changed_by="user",
        )

        specialist = repo.get_specialist(sid)
        versions = repo.get_version_history(sid)
        assert json.loads(specialist.composition_ids) == ["comp_builtin_external_coding"]
        assert json.loads(versions[0].composition_ids) == ["comp_builtin_external_coding"]

    def test_update_nonexistent_returns_false(self, in_memory_db):
        """更新不存在的专员返回 False"""
        repo = SpecialistRepository()

        result = repo.update_specialist(
            "nonexistent",
            description="不存在",
            changed_by="user",
        )
        assert result is False


# ═══════════════════════════════════════════════
# Delete
# ═══════════════════════════════════════════════


class TestDeleteSpecialist:
    def test_delete_deactivates_specialist(self, in_memory_db):
        """删除专员走软删除，保留专员行。"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo)

        result = repo.delete_specialist(sid)
        assert result is True
        specialist = repo.get_specialist(sid)
        assert specialist is not None
        assert specialist.is_active is False

    def test_delete_preserves_versions(self, in_memory_db):
        """删除专员保留版本历史。"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo)
        repo.update_specialist(sid, description="v2", changed_by="user")

        versions_before = repo.get_version_history(sid)
        assert len(versions_before) == 2

        repo.delete_specialist(sid)
        versions_after = repo.get_version_history(sid)
        assert len(versions_after) == 2

    def test_delete_nonexistent_returns_false(self, in_memory_db):
        """删除不存在的专员返回 False"""
        repo = SpecialistRepository()
        result = repo.delete_specialist("nonexistent")
        assert result is False


# ═══════════════════════════════════════════════
# List
# ═══════════════════════════════════════════════


class TestListSpecialists:
    def test_list_all(self, in_memory_db):
        """列出所有专员"""
        repo = SpecialistRepository()
        _create_specialist_via_repo(repo, name="专员A")
        _create_specialist_via_repo(repo, name="专员B")

        specialists, total = repo.list_specialists(active_only=False)
        assert total >= 2

    def test_list_active_only(self, in_memory_db):
        """只列出活跃专员"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo, name="活跃专员")
        repo.deactivate_specialist(sid)
        _create_specialist_via_repo(repo, name="另一个专员")

        specialists, total = repo.list_specialists(active_only=True)
        names = [s.name for s in specialists]
        assert "活跃专员" not in names
        assert "另一个专员" in names

    def test_list_with_pagination(self, in_memory_db):
        """分页列出专员"""
        repo = SpecialistRepository()
        for i in range(5):
            _create_specialist_via_repo(repo, name=f"专员_{i}")

        specialists, total = repo.list_specialists(limit=2, offset=0)
        assert len(specialists) == 2
        assert total >= 5


# ═══════════════════════════════════════════════
# Deactivate
# ═══════════════════════════════════════════════


class TestDeactivateSpecialist:
    def test_deactivate_sets_is_active_false(self, in_memory_db):
        """停用专员设置 is_active=False。"""
        repo = SpecialistRepository()
        sid = _create_specialist_via_repo(repo, name="待停用")

        result = repo.deactivate_specialist(sid)
        assert result is True

        specialist = repo.get_specialist(sid)
        assert specialist.is_active is False

    def test_deactivate_nonexistent_returns_false(self, in_memory_db):
        """停用不存在的专员返回 False"""
        repo = SpecialistRepository()
        result = repo.deactivate_specialist("nonexistent")
        assert result is False
