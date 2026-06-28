from __future__ import annotations

from src.data.unified_config import get_unified_config


def test_toggle_execution_review_setting(desktop_api_client):
    response = desktop_api_client.patch(
        "/api/settings/values",
        json={"values": {"self_improvement.execution_review.enabled": False}},
    )

    assert response.status_code == 200
    assert get_unified_config().get_self_improvement_execution_review_enabled() is False
