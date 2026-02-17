"""
Intent Repository 单元测试
"""

import pytest
from datetime import datetime
from src.data.database import DatabaseManager
from src.business.intent.intent_models import Intent, IntentStatus
from src.business.intent.intent_repository import IntentRepository


@pytest.fixture
def db_manager(tmp_path):
    """创建临时数据库"""
    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager(str(db_path))
    db_manager.initialize()

    # 运行迁移
    from src.data.migrations import migrate_to_v2

    migrate_to_v2(db_manager)

    yield db_manager

    db_manager.close()


@pytest.fixture
def intent_repository(db_manager):
    """创建 IntentRepository"""
    return IntentRepository(db_manager)


@pytest.fixture
def sample_intent():
    """创建示例意图"""
    return Intent(
        recording_id="rec-001",
        core_operations=["打开登录页面", "输入用户名", "输入密码", "点击登录"],
        target="某网站",
        business_scenario="用户登录",
        expected_results=["登录成功", "跳转到首页"],
        analysis_confidence=0.9,
        llm_model_used="claude-3-5-sonnet-20241022",
    )


class TestIntentRepository:
    """IntentRepository 测试"""

    def test_create_intent(self, intent_repository, sample_intent):
        """测试创建意图"""
        created = intent_repository.create(sample_intent)

        assert created.intent_id == sample_intent.intent_id
        assert created.recording_id == "rec-001"
        assert created.status == IntentStatus.ANALYZING

    def test_get_by_id(self, intent_repository, sample_intent):
        """测试根据ID获取意图"""
        intent_repository.create(sample_intent)

        retrieved = intent_repository.get_by_id(sample_intent.intent_id)

        assert retrieved is not None
        assert retrieved.intent_id == sample_intent.intent_id
        assert retrieved.recording_id == "rec-001"
        assert len(retrieved.core_operations) == 4

    def test_get_by_recording_id(self, intent_repository, sample_intent):
        """测试根据录制ID获取意图"""
        intent_repository.create(sample_intent)

        retrieved = intent_repository.get_by_recording_id("rec-001")

        assert retrieved is not None
        assert retrieved.intent_id == sample_intent.intent_id

    def test_get_by_status(self, intent_repository, sample_intent):
        """测试根据状态获取意图列表"""
        intent_repository.create(sample_intent)

        intents = intent_repository.get_by_status(IntentStatus.ANALYZING)

        assert len(intents) >= 1
        assert any(i.intent_id == sample_intent.intent_id for i in intents)

    def test_update_intent(self, intent_repository, sample_intent):
        """测试更新意图"""
        intent_repository.create(sample_intent)

        sample_intent.confirm(
            confirmed_operations=["打开登录页面", "点击登录"],
            user_message="简化流程",
        )

        updated = intent_repository.update(sample_intent)

        assert updated.status == IntentStatus.CONFIRMED
        assert updated.user_message == "简化流程"
        assert len(updated.confirmed_operations) == 2

    def test_delete_intent(self, intent_repository, sample_intent):
        """测试删除意图"""
        intent_repository.create(sample_intent)

        deleted = intent_repository.delete(sample_intent.intent_id)

        assert deleted is True

        retrieved = intent_repository.get_by_id(sample_intent.intent_id)
        assert retrieved is None

    def test_get_all(self, intent_repository, sample_intent):
        """测试获取所有意图"""
        intent_repository.create(sample_intent)

        # 创建第二个意图
        intent2 = Intent(recording_id="rec-002", core_operations=["搜索商品"])
        intent_repository.create(intent2)

        all_intents = intent_repository.get_all(limit=10)

        assert len(all_intents) >= 2
