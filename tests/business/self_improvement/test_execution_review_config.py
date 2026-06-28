from src.data.unified_config import get_unified_config


def test_execution_review_defaults():
    cfg = get_unified_config()

    assert cfg.get_self_improvement_execution_review_enabled() is True
    assert cfg.get_self_improvement_execution_review_max_per_session() == 3
    assert cfg.get_self_improvement_execution_review_model() == {}
