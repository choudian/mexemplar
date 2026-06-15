"""澄清 API 与事件契约测试（019）。

覆盖：GET pending 快照（含/不含、不泄漏答案）、decision 归属 404、幂等、422 校验、
UI 事件注册/allowlist/enum、嵌套禁用值拒绝、resolved 不含答案。
"""

import threading
import time

import pytest

import src.business.agents.tools.clarification_manager as cm
from src.desktop_api.clarifications import _requested_payload, install_clarification_signal
from src.desktop_api.ui_events import UI_EVENT_REGISTRY, UiEventValidationError, validate_ui_event_payload


@pytest.fixture(autouse=True)
def reset_clarification():
    cm.reset_clarification_state_for_tests()
    install_clarification_signal()
    yield
    cm.reset_clarification_state_for_tests()


def _seed_pending(session_id="sess-api", request_id="clr_api1", multi=False):
    questions = cm.validate_and_normalize_questions(
        [
            {
                "question": "选择执行方式？",
                "header": "执行方式",
                "multiSelect": multi,
                "options": [{"label": "按顺序"}, {"label": "并行"}],
            }
        ]
    )
    pending = cm.PendingClarification(
        request_id=request_id,
        session_id=session_id,
        questions=questions,
        created_at=time.monotonic(),
        event=threading.Event(),
    )
    with cm._clarification_lock:
        cm._pending_clarifications[request_id] = pending
    return pending


# ===== GET pending 快照 =====


def test_pending_snapshot_empty(desktop_api_client):
    resp = desktop_api_client.get("/api/assistant/sessions/none/clarifications/pending")
    assert resp.status_code == 200
    assert resp.json()["clarification"] is None


def test_pending_snapshot_has_questions_no_answers(desktop_api_client):
    _seed_pending(session_id="sess-api")
    resp = desktop_api_client.get("/api/assistant/sessions/sess-api/clarifications/pending")
    assert resp.status_code == 200
    body = resp.json()["clarification"]
    assert body["requestId"] == "clr_api1"
    assert body["status"] == "pending"
    assert body["questions"][0]["questionId"] == "q1"
    assert body["questions"][0]["options"][0]["optionId"] == "q1o1"
    # 快照不含任何答案字段
    assert "answers" not in body
    assert "selectedOptionIds" not in str(body)


# ===== decision API =====


def test_decision_submit_answered(desktop_api_client):
    _seed_pending(session_id="sess-api")
    resp = desktop_api_client.post(
        "/api/assistant/sessions/sess-api/clarifications/clr_api1/decision",
        json={"decision": "submit", "answers": [{"questionId": "q1", "selectedOptionIds": ["q1o1"], "otherText": None}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "answered" and body["accepted"] is True


def test_decision_cancel(desktop_api_client):
    _seed_pending(session_id="sess-api")
    resp = desktop_api_client.post(
        "/api/assistant/sessions/sess-api/clarifications/clr_api1/decision",
        json={"decision": "cancel", "answers": []},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_decision_ownership_mismatch_404(desktop_api_client):
    _seed_pending(session_id="sess-api")
    resp = desktop_api_client.post(
        "/api/assistant/sessions/WRONG/clarifications/clr_api1/decision",
        json={"decision": "cancel", "answers": []},
    )
    assert resp.status_code == 404


def test_decision_idempotent_repeat(desktop_api_client):
    _seed_pending(session_id="sess-api")
    first = desktop_api_client.post(
        "/api/assistant/sessions/sess-api/clarifications/clr_api1/decision",
        json={"decision": "submit", "answers": [{"questionId": "q1", "selectedOptionIds": ["q1o1"], "otherText": None}]},
    )
    assert first.json()["accepted"] is True
    second = desktop_api_client.post(
        "/api/assistant/sessions/sess-api/clarifications/clr_api1/decision",
        json={"decision": "submit", "answers": [{"questionId": "q1", "selectedOptionIds": ["q1o2"], "otherText": None}]},
    )
    assert second.status_code == 200
    assert second.json()["accepted"] is False


def test_decision_validation_422(desktop_api_client):
    _seed_pending(session_id="sess-api")
    # 单选题提交两个选项 -> 422，不结算
    resp = desktop_api_client.post(
        "/api/assistant/sessions/sess-api/clarifications/clr_api1/decision",
        json={"decision": "submit", "answers": [{"questionId": "q1", "selectedOptionIds": ["q1o1", "q1o2"], "otherText": None}]},
    )
    assert resp.status_code == 422
    # 仍 pending（未结算）
    assert cm.get_pending_for_session("sess-api") is not None


# ===== UI 事件契约（T019）=====


def test_both_events_registered():
    assert "assistant.clarification_requested" in UI_EVENT_REGISTRY
    assert "assistant.clarification_resolved" in UI_EVENT_REGISTRY


def test_requested_payload_valid():
    pending = _seed_pending(session_id="sess-api")
    payload = _requested_payload(pending)
    validate_ui_event_payload("assistant.clarification_requested", payload)
    assert payload["status"] == "pending"
    # 不含答案投影
    assert "answers" not in payload


def test_resolved_rejects_answers_key():
    with pytest.raises(UiEventValidationError):
        validate_ui_event_payload(
            "assistant.clarification_resolved",
            {"requestId": "r", "sessionId": "s", "status": "answered", "answers": []},
        )


def test_resolved_status_enum_enforced():
    with pytest.raises(UiEventValidationError):
        validate_ui_event_payload(
            "assistant.clarification_resolved",
            {"requestId": "r", "sessionId": "s", "status": "bogus"},
        )


def test_requested_nested_forbidden_value_rejected():
    bad = {
        "requestId": "r",
        "sessionId": "s",
        "status": "pending",
        "questions": [
            {
                "questionId": "q1",
                "question": "api_key=sk-secret-1234567890",
                "header": "h",
                "multiSelect": False,
                "options": [{"optionId": "q1o1", "label": "A"}],
            }
        ],
    }
    with pytest.raises(UiEventValidationError):
        validate_ui_event_payload("assistant.clarification_requested", bad)
