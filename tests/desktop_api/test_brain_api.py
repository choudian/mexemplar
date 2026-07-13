"""
P1 大脑 API 端点测试 (T028)

覆盖：
- GET /api/brain/zones - 返回分区汇总
- GET /api/brain/zones/{zone}/entries - 返回分页条目
- GET /api/brain/segments - 返回 segment 列表
- POST /api/brain/segments/{id}/retry - 重试失败 segment
"""

import pytest
from uuid import uuid4
from unittest.mock import patch, MagicMock

from src.data.models_sqlite import BrainSegment, BrainMemoryEntry, Tool
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


# ═══════════════════════════════════════════════
# GET /api/brain/zones
# ═══════════════════════════════════════════════


class TestGetZones:
    def test_returns_zone_summaries(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/zones")

        assert response.status_code == 200
        data = response.json()
        assert "zones" in data
        assert isinstance(data["zones"], list)

    def test_zone_summaries_include_all_six_zones(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/zones")

        assert response.status_code == 200
        data = response.json()
        zone_names = {z["zone"] for z in data["zones"]}

        expected_zones = {"hot", "persistent", "archive", "subconscious", "failure", "prediction"}
        assert expected_zones.issubset(zone_names)

    def test_zone_summaries_have_correct_fields(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/zones")

        assert response.status_code == 200
        data = response.json()
        for zone in data["zones"]:
            assert "zone" in zone
            assert "label" in zone
            assert "entry_count" in zone


# ═══════════════════════════════════════════════
# GET /api/brain/zones/{zone}/entries
# ═══════════════════════════════════════════════


class TestGetZoneEntries:
    def test_returns_entries_for_hot_zone(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/zones/hot/entries")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_returns_entries_with_pagination(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/zones/hot/entries?limit=10&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert "limit" in data
        assert "offset" in data
        assert data["limit"] == 10
        assert data["offset"] == 0

    def test_invalid_zone_returns_error(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/zones/invalid_zone/entries")

        assert response.status_code in (400, 404, 422)

    def test_entry_response_has_required_fields(self, desktop_api_client, in_memory_db):
        """验证返回的 entry 对象包含所有必需字段。"""
        # 先创建一个 entry
        with in_memory_db.get_session() as session:
            entry = BrainMemoryEntry(
                entry_id=uuid4().hex[:50],
                zone="hot",
                content="Test content",
                status="active",
                origin="distillation",
                reason="test",
                relevance_score=0.9,
            )
            session.add(entry)
            session.commit()

        response = desktop_api_client.get("/api/brain/zones/hot/entries")

        assert response.status_code == 200
        data = response.json()
        if data["items"]:
            item = data["items"][0]
            required_fields = {
                "entry_id",
                "zone",
                "content",
                "status",
                "origin",
                "reason",
                "loaded_count",
                "referenced_count",
            }
            assert required_fields.issubset(set(item.keys()))


# ═══════════════════════════════════════════════
# GET /api/brain/segments
# ═══════════════════════════════════════════════


class TestGetSegments:
    def test_returns_segments_list(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/segments")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_returns_segments_with_pagination(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/segments?limit=10&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert "limit" in data
        assert "offset" in data

    def test_filter_by_status(self, desktop_api_client):
        response = desktop_api_client.get("/api/brain/segments?status=failed")

        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["status"] == "failed"

    def test_segment_response_has_required_fields(self, desktop_api_client, in_memory_db):
        """验证返回的 segment 对象包含所有必需字段。"""
        with in_memory_db.get_session() as session:
            segment = BrainSegment(
                segment_id=uuid4().hex[:50],
                session_id=uuid4().hex[:50],
                status="pending",
                boundary_reason="idle",
            )
            session.add(segment)
            session.commit()

        response = desktop_api_client.get("/api/brain/segments")

        assert response.status_code == 200
        data = response.json()
        if data["items"]:
            item = data["items"][0]
            required_fields = {
                "segment_id",
                "session_id",
                "status",
                "retry_count",
                "boundary_reason",
                "sealed_at",
            }
            assert required_fields.issubset(set(item.keys()))


# ═══════════════════════════════════════════════
# POST /api/brain/segments/{segment_id}/retry
# ═══════════════════════════════════════════════


class TestRetrySegment:
    def test_retry_failed_segment(self, desktop_api_client, in_memory_db):
        """重试失败的 segment 应将其状态从 failed 改为 pending。"""
        segment_id = uuid4().hex[:50]

        with in_memory_db.get_session() as session:
            segment = BrainSegment(
                segment_id=segment_id,
                session_id=uuid4().hex[:50],
                status="failed",
                boundary_reason="idle",
                retry_count=2,
            )
            session.add(segment)
            session.commit()

        response = desktop_api_client.post(f"/api/brain/segments/{segment_id}/retry")

        assert response.status_code == 200
        data = response.json()
        assert data["segment_id"] == segment_id
        assert data["status"] == "pending"

    def test_retry_nonexistent_segment_returns_404(self, desktop_api_client):
        """重试不存在的 segment 应返回 404。"""
        response = desktop_api_client.post("/api/brain/segments/nonexistent/retry")

        assert response.status_code == 404

    def test_retry_non_failed_segment_returns_error(self, desktop_api_client, in_memory_db):
        """重试非 failed 状态的 segment 应返回错误。"""
        segment_id = uuid4().hex[:50]

        with in_memory_db.get_session() as session:
            segment = BrainSegment(
                segment_id=segment_id,
                session_id=uuid4().hex[:50],
                status="pending",
                boundary_reason="idle",
            )
            session.add(segment)
            session.commit()

        response = desktop_api_client.post(f"/api/brain/segments/{segment_id}/retry")

        # 非 failed 状态的 segment 不应允许重试
        assert response.status_code in (400, 409, 422)


# ═══════════════════════════════════════════════
# 认证验证
# ═══════════════════════════════════════════════


class TestBrainApiAuth:
    def test_brain_endpoints_require_auth(self, desktop_api_token):
        """大脑 API 端点应要求 X-Mexemplar-Session 认证。"""
        from fastapi.testclient import TestClient
        from src.desktop_api.app import create_app

        app = create_app(desktop_api_token)

        # 无 token 的请求应被拒绝
        client_no_auth = TestClient(app)
        response = client_no_auth.get("/api/brain/zones")
        assert response.status_code == 401


# ═══════════════════════════════════════════════
# T065: Specialist REST contract tests
# ═══════════════════════════════════════════════


class TestCreateSpecialist:
    def test_create_specialist_success(self, desktop_api_client):
        """POST /api/brain/specialists 创建专员"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.create_specialist.return_value = {
                "specialist_id": "sp-001",
                "name": "天气专家",
                "description": "天气查询专员",
                "role_definition": "你负责查询天气",
                "tool_whitelist": ["get_weather"],
                "composition_ids": ["comp_builtin_external_coding"],
                "origin": "user_management_ui",
                "reason": "通过管理界面创建",
                "current_version": 1,
                "is_active": True,
            }

            response = desktop_api_client.post(
                "/api/brain/specialists",
                json={
                    "name": "天气专家",
                    "description": "天气查询专员",
                    "role_definition": "你负责查询天气",
                    "tool_whitelist": ["get_weather"],
                    "composition_ids": ["comp_builtin_external_coding"],
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "天气专家"
            mock_service.create_specialist.assert_called_once_with(
                name="天气专家",
                description="天气查询专员",
                role_definition="你负责查询天气",
                tool_whitelist=["get_weather"],
                composition_ids=["comp_builtin_external_coding"],
                caller_type="user_management_ui",
            )

    def test_create_specialist_missing_fields(self, desktop_api_client):
        """缺少必需字段应返回 422"""
        response = desktop_api_client.post(
            "/api/brain/specialists",
            json={"name": ""},
        )

        assert response.status_code == 422

    def test_create_specialist_duplicate_name(self, desktop_api_client):
        """重复名称应返回 409"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.create_specialist.side_effect = ValueError("专员名称已存在")

            response = desktop_api_client.post(
                "/api/brain/specialists",
                json={
                    "name": "重复名称",
                    "description": "描述",
                    "role_definition": "角色",
                    "tool_whitelist": [],
                },
            )

            assert response.status_code == 409
            assert response.json()["detail"] == {"error": "conflict"}
            assert "专员名称已存在" not in response.text

    def test_create_rejects_invalid_composition_assignment(self, desktop_api_client):
        from src.business.brain.specialist_service import CompositionValidationError

        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            MockService.return_value.create_specialist.side_effect = CompositionValidationError(
                "技能组合不存在或未发布/不可用: comp_missing"
            )

            response = desktop_api_client.post(
                "/api/brain/specialists",
                json={
                    "name": "代码专员",
                    "description": "执行编码任务",
                    "role_definition": "只使用授权组合",
                    "composition_ids": ["comp_missing"],
                },
            )

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "invalid_compositions"


class TestListSpecialists:
    def test_list_specialists(self, desktop_api_client):
        """GET /api/brain/specialists 返回专员列表"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.list_specialists.return_value = (
                [{"specialist_id": "sp-001", "name": "专家1"}],
                1,
            )

            response = desktop_api_client.get("/api/brain/specialists")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data

    def test_list_specialists_with_pagination(self, desktop_api_client):
        """GET /api/brain/specialists 支持分页"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.list_specialists.return_value = ([], 0)

            response = desktop_api_client.get("/api/brain/specialists?limit=10&offset=0")

            assert response.status_code == 200


class TestGetSpecialist:
    def test_get_specialist_by_id(self, desktop_api_client):
        """GET /api/brain/specialists/{id} 返回专员详情"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.get_specialist.return_value = {
                "specialist_id": "sp-001",
                "name": "天气专家",
            }

            response = desktop_api_client.get("/api/brain/specialists/sp-001")

            assert response.status_code == 200
            data = response.json()
            assert data["specialist_id"] == "sp-001"

    def test_get_specialist_not_found(self, desktop_api_client):
        """GET /api/brain/specialists/{id} 不存在返回 404"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.get_specialist.return_value = None

            response = desktop_api_client.get("/api/brain/specialists/nonexistent")

            assert response.status_code == 404


class TestUpdateSpecialist:
    def test_update_specialist(self, desktop_api_client):
        """PUT /api/brain/specialists/{id} 更新专员"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.update_specialist.return_value = {
                "specialist_id": "sp-001",
                "name": "更新后的名称",
                "current_version": 2,
            }

            response = desktop_api_client.put(
                "/api/brain/specialists/sp-001",
                json={"name": "更新后的名称"},
            )

            assert response.status_code == 200
            mock_service.update_specialist.assert_called_once_with(
                specialist_id="sp-001",
                name="更新后的名称",
                description=None,
                role_definition=None,
                tool_whitelist=None,
                composition_ids=None,
                caller_type="user_management_ui",
                change_reason=None,
            )

    def test_update_specialist_not_found(self, desktop_api_client):
        """PUT 不存在的专员返回 404"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.update_specialist.side_effect = KeyError("specialist_not_found")

            response = desktop_api_client.put(
                "/api/brain/specialists/nonexistent",
                json={"name": "新名称"},
            )

            assert response.status_code == 404

    def test_update_specialist_validates_request_body(self, desktop_api_client):
        response = desktop_api_client.put(
            "/api/brain/specialists/sp-001",
            json={"name": "  ", "tool_whitelist": "not-a-list"},
        )

        assert response.status_code == 422

    def test_update_specialist_conflict_does_not_leak_business_message(self, desktop_api_client):
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.update_specialist.side_effect = ValueError("专员名称已存在: 内部名称")

            response = desktop_api_client.put(
                "/api/brain/specialists/sp-001",
                json={"name": "重复名称"},
            )

        assert response.status_code == 409
        assert response.json()["detail"] == {"error": "conflict"}
        assert "内部名称" not in response.text


class TestDeleteSpecialist:
    def test_delete_specialist(self, desktop_api_client):
        """DELETE /api/brain/specialists/{id} 删除专员"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.delete_specialist.return_value = True

            response = desktop_api_client.delete("/api/brain/specialists/sp-001")

            assert response.status_code == 204

    def test_delete_specialist_not_found(self, desktop_api_client):
        """DELETE 不存在的专员返回 404"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.delete_specialist.return_value = False

            response = desktop_api_client.delete("/api/brain/specialists/nonexistent")

            assert response.status_code == 404


class TestSpecialistVersions:
    def test_get_specialist_versions(self, desktop_api_client):
        """GET /api/brain/specialists/{id}/versions 返回版本历史"""
        with patch("src.desktop_api.routers.brain.SpecialistService") as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.get_specialist.return_value = {"specialist_id": "sp-001"}
            mock_service.get_version_history.return_value = [
                {"version": 2, "name": "v2"},
                {"version": 1, "name": "v1"},
            ]

            response = desktop_api_client.get("/api/brain/specialists/sp-001/versions")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert len(data["items"]) == 2


class TestEntryManagement:
    def test_edit_entry_returns_new_entry_and_evolution_chain(
        self, desktop_api_client, in_memory_db
    ):
        entry_id = uuid4().hex[:50]
        with in_memory_db.get_session() as session:
            session.add(
                BrainMemoryEntry(
                    entry_id=entry_id,
                    zone="persistent",
                    content="旧内容",
                    status="active",
                    origin="distillation",
                    reason="test",
                    relevance_score=1.0,
                )
            )
            session.commit()

        response = desktop_api_client.put(
            f"/api/brain/entries/{entry_id}",
            json={"content": "新内容", "scope": "工作偏好"},
        )

        assert response.status_code == 200
        updated = response.json()
        assert updated["content"] == "新内容"
        assert updated["scope"] == "工作偏好"

        chain = desktop_api_client.get(f"/api/brain/entries/{updated['entry_id']}/evolution")
        assert chain.status_code == 200
        assert [item["content"] for item in chain.json()["chain"]] == ["旧内容", "新内容"]

    def test_delete_entry_soft_deletes_without_physical_removal(
        self, desktop_api_client, in_memory_db
    ):
        entry_id = uuid4().hex[:50]
        with in_memory_db.get_session() as session:
            session.add(
                BrainMemoryEntry(
                    entry_id=entry_id,
                    zone="hot",
                    content="可删除内容",
                    status="active",
                    origin="distillation",
                    reason="test",
                    relevance_score=1.0,
                )
            )
            session.commit()

        response = desktop_api_client.delete(f"/api/brain/entries/{entry_id}")

        assert response.status_code == 204
        with in_memory_db.get_session() as session:
            entry = session.get(BrainMemoryEntry, entry_id)
            assert entry is not None
            assert entry.status == "soft-deleted"


class TestSkillPoolEndpoints:
    def test_get_skill_pool_returns_published_tool_names(self, desktop_api_client, in_memory_db):
        with in_memory_db.get_session() as session:
            session.add(
                Tool(
                    tool_id="tool-report",
                    tool_name="报表分析",
                    description="分析报表",
                    status="published",
                )
            )
            session.commit()

        response = desktop_api_client.get("/api/brain/skill-pool")

        assert response.status_code == 200
        data = response.json()
        assert data["skills"][0]["tool_id"] == "web_search"
        assert data["skills"][0]["is_builtin"] is True
        assert [skill for skill in data["skills"] if not skill.get("is_builtin")] == [
            {
                "tool_id": "tool-report",
                "name": "报表分析",
                "description": "分析报表",
                "is_builtin": False,
            }
        ]

    def test_force_remove_skill_prunes_specialist_whitelist(self, desktop_api_client, in_memory_db):
        from src.business.brain.specialist_service import SpecialistService

        with in_memory_db.get_session() as session:
            session.add(
                Tool(
                    tool_id="tool-report",
                    tool_name="报表分析",
                    description="分析报表",
                    status="published",
                )
            )
            session.commit()

        created = desktop_api_client.post(
            "/api/brain/specialists",
            json={
                "name": "报表专员",
                "description": "处理周期报表",
                "role_definition": "你负责处理报表。",
                "tool_whitelist": ["tool-report"],
            },
        )
        assert created.status_code == 200
        specialist = created.json()

        conflict = desktop_api_client.delete("/api/brain/skill-pool/tool-report")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["error"] == "skill_in_use"

        forced = desktop_api_client.delete("/api/brain/skill-pool/tool-report?force=true")
        assert forced.status_code == 204
        assert (
            SpecialistService().get_specialist(specialist["specialist_id"])["tool_whitelist"] == []
        )
        remaining = desktop_api_client.get("/api/brain/skill-pool").json()["skills"]
        assert remaining
        assert all(skill["is_builtin"] for skill in remaining)
