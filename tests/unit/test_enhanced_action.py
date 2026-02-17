"""
增强数据类单元测试
"""

import pytest
from src.recording.recorder import (
    VisualFeatures,
    SiblingElement,
    SiblingsSnapshot,
    NetworkRequestDetail,
    EnhancedAction,
    Action,
)


class TestVisualFeatures:
    """VisualFeatures 测试"""

    def test_creation(self):
        """测试创建"""
        features = VisualFeatures(
            element_position={"x": 100, "y": 200, "width": 50, "height": 30},
            background_color="#ffffff",
            text_color="#000000",
            font_size=14,
            is_visible=True,
            z_index=1,
        )

        assert features.element_position == {"x": 100, "y": 200, "width": 50, "height": 30}
        assert features.background_color == "#ffffff"
        assert features.font_size == 14
        assert features.is_visible is True

    def test_to_dict(self):
        """测试转换为字典"""
        features = VisualFeatures(
            element_position={"x": 100, "y": 200},
        )

        data = features.to_dict()

        assert data["element_position"] == {"x": 100, "y": 200}
        assert "background_color" in data

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "element_position": {"x": 100, "y": 200},
            "background_color": "#ffffff",
            "font_size": 14,
        }

        features = VisualFeatures.from_dict(data)

        assert features.element_position == {"x": 100, "y": 200}
        assert features.background_color == "#ffffff"
        assert features.font_size == 14


class TestSiblingElement:
    """SiblingElement 测试"""

    def test_creation(self):
        """测试创建"""
        element = SiblingElement(
            index=1,
            tag="li",
            class_list=["item", "active"],
            text_summary="First item",
            href="/item/1",
            has_link=True,
            has_image=False,
        )

        assert element.index == 1
        assert element.tag == "li"
        assert "item" in element.class_list
        assert element.has_link is True

    def test_to_dict(self):
        """测试转换为字典"""
        element = SiblingElement(
            index=1,
            tag="li",
        )

        data = element.to_dict()

        assert data["index"] == 1
        assert data["tag"] == "li"

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "index": 1,
            "tag": "li",
            "class_list": ["item"],
            "text_summary": "Item",
        }

        element = SiblingElement.from_dict(data)

        assert element.index == 1
        assert element.tag == "li"
        assert "item" in element.class_list


class TestSiblingsSnapshot:
    """SiblingsSnapshot 测试"""

    def test_creation(self):
        """测试创建"""
        siblings = [
            SiblingElement(index=1, tag="li", text_summary="Item 1"),
            SiblingElement(index=2, tag="li", text_summary="Item 2"),
        ]

        snapshot = SiblingsSnapshot(
            container_selector="ul.items",
            item_selector="li",
            list_type="list",
            total_count=2,
            siblings=siblings,
        )

        assert snapshot.container_selector == "ul.items"
        assert snapshot.total_count == 2
        assert len(snapshot.siblings) == 2

    def test_to_dict(self):
        """测试转换为字典"""
        siblings = [
            SiblingElement(index=1, tag="li"),
        ]

        snapshot = SiblingsSnapshot(
            total_count=1,
            siblings=siblings,
        )

        data = snapshot.to_dict()

        assert data["total_count"] == 1
        assert len(data["siblings"]) == 1
        assert isinstance(data["siblings"][0], dict)

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "container_selector": "ul.items",
            "total_count": 2,
            "siblings": [
                {"index": 1, "tag": "li"},
                {"index": 2, "tag": "li"},
            ],
        }

        snapshot = SiblingsSnapshot.from_dict(data)

        assert snapshot.container_selector == "ul.items"
        assert snapshot.total_count == 2
        assert len(snapshot.siblings) == 2
        assert all(isinstance(s, SiblingElement) for s in snapshot.siblings)


class TestNetworkRequestDetail:
    """NetworkRequestDetail 测试"""

    def test_creation(self):
        """测试创建"""
        request = NetworkRequestDetail(
            url="https://api.example.com/data",
            method="GET",
            response_status=200,
            response_body='{"key": "value"}',
            response_body_parsed={"key": "value"},
            is_json_response=True,
        )

        assert request.url == "https://api.example.com/data"
        assert request.is_json_response is True
        assert request.response_body_parsed == {"key": "value"}

    def test_to_dict(self):
        """测试转换为字典"""
        request = NetworkRequestDetail(
            url="https://api.example.com/data",
            method="GET",
            response_body_parsed={"key": "value"},
            is_json_response=True,
        )

        data = request.to_dict()

        assert "response_body_parsed" in data
        assert "is_json_response" in data
        assert data["response_body_parsed"] == {"key": "value"}

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "url": "https://api.example.com/data",
            "method": "GET",
            "response_status": 200,
            "response_body": '{"key": "value"}',
            "response_body_parsed": {"key": "value"},
            "is_json_response": True,
        }

        request = NetworkRequestDetail.from_dict(data)

        assert request.url == "https://api.example.com/data"
        assert request.response_body_parsed == {"key": "value"}
        assert request.is_json_response is True


class TestEnhancedAction:
    """EnhancedAction 测试"""

    def test_creation(self):
        """测试创建"""
        action = EnhancedAction(
            action_type="click",
            recording_mode="browser",
            url="https://example.com",
            dom_tree_snapshot={"html": "body"},
        )

        assert action.action_type == "click"
        assert action.recording_mode == "browser"
        assert action.dom_tree_snapshot == {"html": "body"}

    def test_from_action(self):
        """测试从 Action 转换"""
        base_action = Action(
            action_type="click",
            recording_mode="browser",
            url="https://example.com",
        )

        enhanced = EnhancedAction.from_action(base_action)

        assert enhanced.action_type == base_action.action_type
        assert enhanced.url == base_action.url

    def test_to_dict_with_enhanced_fields(self):
        """测试转换包含增强字段"""
        visual_features = VisualFeatures(
            element_position={"x": 100},
        )

        action = EnhancedAction(
            action_type="click",
            visual_features=visual_features,
            dom_tree_snapshot={"html": "body"},
        )

        data = action.to_dict()

        assert "visual_features" in data
        assert "dom_tree_snapshot" in data
        assert data["dom_tree_snapshot"] == {"html": "body"}

    def test_from_dict_with_enhanced_fields(self):
        """测试从字典创建包含增强字段"""
        data = {
            "action_type": "click",
            "recording_mode": "browser",
            "url": "https://example.com",
            "visual_features": {
                "element_position": {"x": 100},
            },
            "dom_tree_snapshot": {"html": "body"},
        }

        action = EnhancedAction.from_dict(data)

        assert action.action_type == "click"
        assert action.visual_features is not None
        assert action.visual_features.element_position == {"x": 100}
        assert action.dom_tree_snapshot == {"html": "body"}

    def test_inheritance(self):
        """测试继承关系"""
        action = EnhancedAction(
            action_type="click",
            url="https://example.com",
            parameters={"x": 100},
        )

        # 应该包含 Action 的所有字段
        assert hasattr(action, "action_type")
        assert hasattr(action, "url")
        assert hasattr(action, "parameters")
        assert hasattr(action, "dom_tree_snapshot")  # 新增字段
        assert hasattr(action, "visual_features")  # 新增字段


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
