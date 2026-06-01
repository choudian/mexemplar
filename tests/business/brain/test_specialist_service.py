"""
T063: SpecialistService CRUD, whitelist, and versioning tests

Tests for:
- CRUD operations (create, read, update, delete)
- Whitelist subset validation
- Version history tracking
- Name uniqueness enforcement
- Origin tracking
"""

import pytest
from unittest.mock import patch, MagicMock

from src.data.models_sqlite import BrainSpecialist, BrainSpecialistVersion
from src.utils.events import clear_all, connect


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


def _make_specialist_orm(
    specialist_id="sp-001",
    name="天气专家",
    description="天气查询专员",
    role_definition="你负责查询天气",
    tool_whitelist='["get_weather"]',
    origin="user_conversation",
    reason="用户创建",
    current_version=1,
    is_active=1,
):
    """创建一个 mock BrainSpecialist ORM 对象"""
    s = MagicMock(spec=BrainSpecialist)
    s.specialist_id = specialist_id
    s.name = name
    s.description = description
    s.role_definition = role_definition
    s.tool_whitelist = tool_whitelist
    s.origin = origin
    s.reason = reason
    s.current_version = current_version
    s.is_active = is_active
    s.created_at = "2026-01-01T00:00:00"
    s.updated_at = "2026-01-01T00:00:00"
    return s


def _make_version_orm(
    version_id="v-001",
    specialist_id="sp-001",
    version=1,
    name="天气专家",
    change_reason="初始创建",
):
    """创建一个 mock BrainSpecialistVersion ORM 对象"""
    v = MagicMock(spec=BrainSpecialistVersion)
    v.version_id = version_id
    v.specialist_id = specialist_id
    v.version = version
    v.name = name
    v.description = "天气查询专员"
    v.role_definition = "你负责查询天气"
    v.tool_whitelist = '["get_weather"]'
    v.changed_by = "user_conversation"
    v.change_reason = change_reason
    v.changed_at = "2026-01-01T00:00:00"
    return v


# ═══════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════


class TestSpecialistServiceCreate:
    def test_create_specialist_success(self):
        """成功创建专员"""
        from src.business.brain.specialist_service import SpecialistService

        with (
            patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo,
            patch("src.business.brain.specialist_service.ToolRepository") as MockToolRepo,
        ):
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist_by_name.return_value = None
            mock_repo.create_specialist.return_value = "sp-001"
            mock_repo.get_specialist.return_value = _make_specialist_orm()

            mock_tool_repo = MagicMock()
            MockToolRepo.return_value = mock_tool_repo
            mock_tool_repo.get_all_published.return_value = [MagicMock(tool_name="get_weather")]

            service = SpecialistService(repo=mock_repo)
            result = service.create_specialist(
                name="天气专家",
                description="天气查询专员",
                role_definition="你负责查询天气",
                tool_whitelist=["get_weather"],
            )

            assert result["name"] == "天气专家"
            assert result["specialist_id"] == "sp-001"
            mock_repo.create_specialist.assert_called_once()

    def test_create_rejects_duplicate_name(self):
        """重复名称应抛出 ValueError"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist_by_name.return_value = _make_specialist_orm()

            service = SpecialistService(repo=mock_repo)
            with pytest.raises(ValueError, match="已存在"):
                service.create_specialist(
                    name="天气专家",
                    description="天气查询专员",
                    role_definition="你负责查询天气",
                    tool_whitelist=["get_weather"],
                )

    def test_create_with_user_conversation_origin(self):
        """通过对话创建时 origin 为 user_conversation"""
        from src.business.brain.specialist_service import SpecialistService

        with (
            patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo,
            patch("src.business.brain.specialist_service.ToolRepository") as MockToolRepo,
        ):
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist_by_name.return_value = None
            mock_repo.create_specialist.return_value = "sp-001"
            mock_repo.get_specialist.return_value = _make_specialist_orm()

            mock_tool_repo = MagicMock()
            MockToolRepo.return_value = mock_tool_repo
            mock_tool_repo.get_all_published.return_value = []

            service = SpecialistService(repo=mock_repo)
            service.create_specialist(
                name="天气专家",
                description="天气查询专员",
                role_definition="你负责查询天气",
                tool_whitelist=[],
                origin="user_conversation",
            )

            call_kwargs = mock_repo.create_specialist.call_args[1]
            assert call_kwargs["origin"] == "user_conversation"

    def test_create_fails_closed_when_default_equipment_fails(self):
        """默认装备方法论失败时不应静默创建无装备专员。"""
        from src.business.brain.specialist_service import SpecialistService

        with (
            patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo,
            patch("src.business.brain.specialist_service.ToolRepository") as MockToolRepo,
            patch(
                "src.business.brain.skill_equipment_service.SkillEquipmentService"
            ) as MockEquipmentService,
        ):
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist_by_name.return_value = None
            mock_repo.create_specialist.return_value = "sp-001"
            mock_repo.get_specialist.return_value = _make_specialist_orm()
            MockToolRepo.return_value.get_all_published.return_value = []
            MockEquipmentService.return_value.default_equip_all.side_effect = RuntimeError(
                "equipment failed"
            )

            service = SpecialistService(repo=mock_repo)
            with pytest.raises(RuntimeError, match="equipment failed"):
                service.create_specialist(
                    name="装备失败专员",
                    description="测试",
                    role_definition="测试",
                    tool_whitelist=[],
                )

            mock_repo.session.rollback.assert_called_once()
            mock_repo.session.commit.assert_not_called()


class TestSpecialistServiceRead:
    def test_get_specialist_by_id(self):
        """按 ID 查询专员"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist.return_value = _make_specialist_orm()

            service = SpecialistService(repo=mock_repo)
            result = service.get_specialist("sp-001")

            assert result is not None
            assert result["specialist_id"] == "sp-001"
            assert result["name"] == "天气专家"

    def test_get_specialist_not_found(self):
        """查询不存在的专员返回 None"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist.return_value = None

            service = SpecialistService(repo=mock_repo)
            result = service.get_specialist("nonexistent")

            assert result is None

    def test_get_specialist_by_name(self):
        """按名称查询专员"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist_by_name.return_value = _make_specialist_orm()

            service = SpecialistService(repo=mock_repo)
            result = service.get_specialist_by_name("天气专家")

            assert result is not None
            assert result["name"] == "天气专家"

    def test_list_specialists(self):
        """列出专员"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.list_specialists.return_value = ([_make_specialist_orm()], 1)

            service = SpecialistService(repo=mock_repo)
            results, total = service.list_specialists()

            assert total == 1
            assert len(results) == 1


class TestSpecialistServiceUpdate:
    def test_update_specialist(self):
        """更新专员信息"""
        from src.business.brain.specialist_service import SpecialistService

        existing = _make_specialist_orm()
        updated = _make_specialist_orm(description="更新后的描述", current_version=2)

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist.side_effect = [existing, updated]
            mock_repo.update_specialist.return_value = True
            received = []
            connect(
                "brain_specialist_changed",
                lambda sender, **kwargs: received.append(kwargs),
                weak=False,
            )

            service = SpecialistService(repo=mock_repo)
            result = service.update_specialist(
                specialist_id="sp-001",
                description="更新后的描述",
            )

            assert result["description"] == "更新后的描述"
            mock_repo.update_specialist.assert_called_once()
            assert received[-1]["operation"] == "update"

    def test_update_rejects_nonexistent(self):
        """更新不存在的专员应抛出稳定的 not-found 异常。"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist.return_value = None

            service = SpecialistService(repo=mock_repo)
            with pytest.raises(KeyError, match="specialist_not_found"):
                service.update_specialist(
                    specialist_id="nonexistent",
                    description="新描述",
                )


class TestSpecialistServiceDelete:
    def test_delete_specialist(self):
        """删除专员走软删除，保留版本历史"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist.return_value = _make_specialist_orm()
            mock_repo.deactivate_specialist.return_value = True
            received = []
            connect(
                "brain_specialist_changed",
                lambda sender, **kwargs: received.append(kwargs),
                weak=False,
            )

            service = SpecialistService(repo=mock_repo)
            result = service.delete_specialist("sp-001")

            assert result is True
            mock_repo.deactivate_specialist.assert_called_once_with("sp-001")
            assert received[-1]["operation"] == "deactivate"


# ═══════════════════════════════════════════════
# Whitelist validation
# ═══════════════════════════════════════════════


class TestWhitelistValidation:
    def test_accepts_valid_whitelist(self):
        """白名单中的工具在技能池中时应通过验证"""
        from src.business.brain.specialist_service import SpecialistService

        with (
            patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo,
            patch("src.business.brain.specialist_service.ToolRepository") as MockToolRepo,
        ):
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist_by_name.return_value = None
            mock_repo.create_specialist.return_value = "sp-001"
            mock_repo.get_specialist.return_value = _make_specialist_orm(
                tool_whitelist='["get_weather", "search_web"]'
            )

            mock_tool_repo = MagicMock()
            MockToolRepo.return_value = mock_tool_repo
            mock_tool_repo.get_all_published.return_value = [
                MagicMock(tool_name="get_weather"),
                MagicMock(tool_name="search_web"),
            ]

            service = SpecialistService(repo=mock_repo)
            result = service.create_specialist(
                name="天气专家",
                description="天气查询专员",
                role_definition="你负责查询天气",
                tool_whitelist=["get_weather", "search_web"],
            )
            assert result is not None

    def test_rejects_invalid_whitelist(self):
        """白名单中的工具不在技能池中时应抛出 ValueError"""
        from src.business.brain.specialist_service import SpecialistService

        with (
            patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo,
            patch("src.business.brain.specialist_service.ToolRepository") as MockToolRepo,
        ):
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist_by_name.return_value = None

            mock_tool_repo = MagicMock()
            MockToolRepo.return_value = mock_tool_repo
            mock_tool_repo.get_all_published.return_value = []

            service = SpecialistService(repo=mock_repo)
            with pytest.raises(ValueError, match="不存在的工具"):
                service.create_specialist(
                    name="天气专家",
                    description="天气查询专员",
                    role_definition="你负责查询天气",
                    tool_whitelist=["nonexistent_tool"],
                )

    def test_empty_whitelist_is_valid(self):
        """空白名单应通过验证"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_specialist_by_name.return_value = None
            mock_repo.create_specialist.return_value = "sp-001"
            mock_repo.get_specialist.return_value = _make_specialist_orm(tool_whitelist="[]")

            service = SpecialistService(repo=mock_repo)
            result = service.create_specialist(
                name="天气专家",
                description="天气查询专员",
                role_definition="你负责查询天气",
                tool_whitelist=[],
            )
            assert result is not None


# ═══════════════════════════════════════════════
# Version history
# ═══════════════════════════════════════════════


class TestVersionHistory:
    def test_get_version_history(self):
        """获取版本历史"""
        from src.business.brain.specialist_service import SpecialistService

        v1 = _make_version_orm(version=1, change_reason="初始创建")
        v2 = _make_version_orm(version_id="v-002", version=2, change_reason="更新描述")

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_version_history.return_value = [v2, v1]

            service = SpecialistService(repo=mock_repo)
            versions = service.get_version_history("sp-001")

            assert len(versions) == 2
            assert versions[0]["version"] == 2
            assert versions[1]["version"] == 1

    def test_version_history_contains_required_fields(self):
        """版本历史记录包含必需字段"""
        from src.business.brain.specialist_service import SpecialistService

        with patch("src.business.brain.specialist_service.SpecialistRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_version_history.return_value = [_make_version_orm()]

            service = SpecialistService(repo=mock_repo)
            versions = service.get_version_history("sp-001")

            assert len(versions) == 1
            v = versions[0]
            assert "version_id" in v
            assert "specialist_id" in v
            assert "version" in v
            assert "name" in v
            assert "changed_by" in v
            assert "tool_whitelist" in v
