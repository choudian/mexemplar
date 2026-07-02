import pytest

from src.business.memory.context_manager import ContextManager


@pytest.mark.parametrize(
    "reference_id,expected",
    [
        ("tsk_123", "任务 ID"),
        ("tg_123", "任务图 ID"),
        ("adj_123", 'load_task_result(adjudication_id="adj_123")'),
    ],
)
def test_load_reference_rejects_task_collaboration_ids(
    mock_config,
    reference_id: str,
    expected: str,
) -> None:
    ctx = ContextManager("ast_parent", mock_config)

    with pytest.raises(ValueError) as exc_info:
        ctx.load_reference(reference_id)

    message = str(exc_info.value)
    assert expected in message
    assert "message/summary reference" in message
