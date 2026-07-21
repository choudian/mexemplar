"""T023: ``/api/scheduled-tasks`` 契约测试（033 US1）。

覆盖 CRUD + runs 列表 + takeover + confirmation decision；camelCase DTO；
``LookupError→404`` / ``ValueError→422`` 映射；token 不进响应正文。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.business.services.chat_service import ChatService
from src.business.scheduling.scheduling_confirmation_manager import (
    reset_state_for_tests as reset_confirmation_state,
)
from src.data.models_sqlite import Message
from src.data.repos.message_repository import MessageRepository
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.data.repos.session_repository import SessionRepository


@pytest.fixture(autouse=True)
def _reset_confirmation():
    reset_confirmation_state()
    yield
    reset_confirmation_state()


def _make_task(**overrides) -> str:
    """直接经 repo 建一条任务（绕过确认卡），返回 task id。"""
    defaults = dict(
        source_type="direct",
        source_ref="查竞品价格",
        title="查竞品",
        schedule_kind="one_shot",
        schedule_payload={"run_at": "2099-07-19T10:00:00", "tz": "Asia/Shanghai"},
        next_fire_at=datetime(2099, 7, 19, 2, 0, 0),
    )
    defaults.update(overrides)
    with ScheduledTaskRepository() as r:
        row = r.create(**defaults)
        return row.scheduled_task_id


# ---------------------------------------------------------------------------
# 列表 / 详情
# ---------------------------------------------------------------------------


def test_list_tasks_returns_camelcase_dto(desktop_api_client: TestClient):
    task_id = _make_task(title="列表测试")
    resp = desktop_api_client.get("/api/scheduled-tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data
    item = next(i for i in data["items"] if i["scheduledTaskId"] == task_id)
    # camelCase 字段
    assert item["scheduledTaskId"] == task_id
    assert item["scheduleKind"] == "one_shot"
    assert item["sourceType"] == "direct"
    assert item["status"] == "active"
    assert item["unattendedAutoApprove"] is False
    assert "scheduleDescription" in item and item["scheduleDescription"]
    assert "lastRunOutcome" in item
    # token 不进响应正文
    assert "test-session-token" not in resp.text


def test_scheduled_api_marks_utc_instants_with_an_explicit_offset(
    desktop_api_client: TestClient,
):
    """UTC naive 存储值必须带时区出 API，避免浏览器把 07:00 当成本地 07:00。"""
    task_id = _make_task(
        title="时区契约",
        next_fire_at=datetime(2099, 7, 21, 7, 0, 0),
    )
    with ScheduledTaskRunRepository() as run_repo:
        run = run_repo.create(
            scheduled_task_id=task_id,
            session_id="ast_timezone_contract",
            started_at=datetime(2099, 7, 20, 7, 0, 0),
        )
        run_repo.cas_transition(
            run.run_id,
            from_status="running",
            to_status="succeeded",
            summary="done",
        )

    task_response = desktop_api_client.get(f"/api/scheduled-tasks/{task_id}")
    runs_response = desktop_api_client.get(f"/api/scheduled-tasks/{task_id}/runs")

    assert task_response.status_code == 200
    assert runs_response.status_code == 200
    task = task_response.json()
    run_item = runs_response.json()["items"][0]
    for value in (
        task["nextFireAt"],
        task["lastRunAt"],
        task["createdAt"],
        task["updatedAt"],
        run_item["startedAt"],
        run_item["finishedAt"],
    ):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert parsed.utcoffset() == timedelta(0), value


def test_list_tasks_status_filter(desktop_api_client: TestClient):
    active_id = _make_task(title="活跃")
    paused_id = _make_task(title="暂停")
    with ScheduledTaskRepository() as r:
        r.cas_status(paused_id, from_status="active", to_status="paused")
    resp = desktop_api_client.get("/api/scheduled-tasks?status=active")
    assert resp.status_code == 200
    ids = [i["scheduledTaskId"] for i in resp.json()["items"]]
    assert active_id in ids
    assert paused_id not in ids


def test_get_task_detail(desktop_api_client: TestClient):
    task_id = _make_task(title="详情测试")
    resp = desktop_api_client.get(f"/api/scheduled-tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["scheduledTaskId"] == task_id


def test_get_task_not_found_returns_404(desktop_api_client: TestClient):
    resp = desktop_api_client.get("/api/scheduled-tasks/sch_missing")
    assert resp.status_code == 404
    # token 不进响应正文（404 守卫）
    assert "test-session-token" not in resp.text


# ---------------------------------------------------------------------------
# PATCH（status + unattendedAutoApprove）
# ---------------------------------------------------------------------------


def test_patch_pause_and_resume(desktop_api_client: TestClient):
    task_id = _make_task(title="暂停启用")
    # pause
    resp = desktop_api_client.patch(f"/api/scheduled-tasks/{task_id}", json={"status": "paused"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"
    # resume
    resp = desktop_api_client.patch(f"/api/scheduled-tasks/{task_id}", json={"status": "active"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_patch_unattended_auto_approve_toggle(desktop_api_client: TestClient):
    task_id = _make_task(title="免确认开关")
    resp = desktop_api_client.patch(
        f"/api/scheduled-tasks/{task_id}", json={"unattendedAutoApprove": True}
    )
    assert resp.status_code == 200
    assert resp.json()["unattendedAutoApprove"] is True
    # 关掉
    resp = desktop_api_client.patch(
        f"/api/scheduled-tasks/{task_id}", json={"unattendedAutoApprove": False}
    )
    assert resp.json()["unattendedAutoApprove"] is False


def test_patch_not_found_returns_404(desktop_api_client: TestClient):
    resp = desktop_api_client.patch("/api/scheduled-tasks/sch_missing", json={"status": "paused"})
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "forbidden_field",
    [
        {"title": "绕过确认修改"},
        {"scheduleKind": "recurring"},
        {"sourceType": "todo"},
    ],
)
def test_patch_rejects_unknown_or_core_fields_without_mutation(
    desktop_api_client: TestClient,
    forbidden_field: dict,
):
    task_id = _make_task(title="保持原样")

    resp = desktop_api_client.patch(
        f"/api/scheduled-tasks/{task_id}",
        json=forbidden_field,
    )

    assert resp.status_code == 422
    detail = desktop_api_client.get(f"/api/scheduled-tasks/{task_id}").json()
    assert detail["title"] == "保持原样"
    assert detail["scheduleKind"] == "one_shot"
    assert detail["sourceType"] == "direct"


# ---------------------------------------------------------------------------
# fire-now / delete
# ---------------------------------------------------------------------------


def test_fire_now_with_mock_launcher(desktop_api_client: TestClient, monkeypatch):
    """fire-now 调用 launcher.launch；这里 mock 掉 SessionLauncher 避免起真会话。"""
    task_id = _make_task(title="立即跑", source_ref="立即跑指令")

    captured: dict = {}

    class _FakeLauncher:
        def launch(self, *, scheduled_task_id, instruction, started_at=None):
            captured["task_id"] = scheduled_task_id
            captured["instruction"] = instruction
            # 建一条 run 模拟 launcher 行为
            with ScheduledTaskRunRepository() as rr:
                run = rr.create(
                    scheduled_task_id=scheduled_task_id,
                    session_id="ast_mock_fire",
                    started_at=started_at,
                )
                return run.run_id

    from src.business.scheduling import scheduler_service as svc_mod

    # patch SchedulerService 的默认 launcher（desktop_api 已注入，但 service 自己 new 时未注入）
    # 这里通过 monkeypatch _require_launcher 让它返回 fake
    original_require = svc_mod.SchedulerService._require_launcher

    def _fake_require(self):
        return _FakeLauncher()

    monkeypatch.setattr(svc_mod.SchedulerService, "_require_launcher", _fake_require)
    # 也要 patch 已注入到 app lifespan service 的 launcher
    try:
        resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/fire-now")
    finally:
        monkeypatch.setattr(svc_mod.SchedulerService, "_require_launcher", original_require)
    assert resp.status_code == 202
    assert resp.json()["status"] == "running"
    assert resp.json()["sessionId"].startswith("ast_")
    assert captured["task_id"] == task_id
    assert "立即" in captured["instruction"]


def test_fire_now_not_found_returns_404(desktop_api_client: TestClient):
    resp = desktop_api_client.post("/api/scheduled-tasks/sch_missing/fire-now")
    assert resp.status_code == 404


def test_fire_now_returns_503_when_runtime_launcher_is_unavailable(
    desktop_api_client: TestClient,
    monkeypatch,
):
    task_id = _make_task(title="runtime 未就绪")
    from src.business.scheduling import scheduler_service as service_module

    monkeypatch.setattr(service_module, "_get_default_scheduler_launcher", lambda: None)

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/fire-now")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "scheduler_runtime_unavailable"


def test_fire_now_returns_409_when_an_active_run_already_exists(
    desktop_api_client: TestClient,
):
    task_id = _make_task(title="已有运行")
    with ScheduledTaskRunRepository() as rr:
        rr.create(scheduled_task_id=task_id, session_id="ast_active_fire_now")

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/fire-now")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "scheduled_task_run_already_active"


def test_fire_now_returns_503_when_dispatch_fails(
    desktop_api_client: TestClient,
    monkeypatch,
):
    task_id = _make_task(title="投递失败")

    class _FailedLauncher:
        def launch(self, *, scheduled_task_id, instruction, started_at=None):
            with ScheduledTaskRunRepository() as rr:
                run = rr.create(
                    scheduled_task_id=scheduled_task_id,
                    session_id="ast_failed_fire_now",
                    started_at=started_at,
                )
                rr.cas_transition(
                    run.run_id,
                    from_status="running",
                    to_status="failed",
                    failure_reason="scheduled session could not be started",
                )
            return run.run_id

    from src.business.scheduling import scheduler_service as service_module

    monkeypatch.setattr(
        service_module.SchedulerService,
        "_require_launcher",
        lambda self: _FailedLauncher(),
    )

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/fire-now")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "scheduled_task_start_failed"


def test_fire_now_returns_503_without_run_when_atomic_session_creation_fails(
    desktop_api_client: TestClient,
    monkeypatch,
):
    task_id = _make_task(title="会话落库失败")
    from src.business.scheduling import scheduler_service as service_module
    from src.business.scheduling.session_launcher import ScheduledSessionCreationFailed

    class _FailedAtomicLauncher:
        def launch(self, **_kwargs):
            raise ScheduledSessionCreationFailed("database unavailable")

    monkeypatch.setattr(
        service_module.SchedulerService,
        "_require_launcher",
        lambda self: _FailedAtomicLauncher(),
    )

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/fire-now")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "scheduled_task_start_failed"
    with ScheduledTaskRunRepository() as rr:
        runs, total = rr.list_by_task(task_id)
    assert runs == []
    assert total == 0


def test_reset_session_clears_current_binding(
    desktop_api_client: TestClient,
    monkeypatch,
):
    task_id = _make_task(title="重开一轮")
    with ScheduledTaskRepository() as repo:
        repo.cas_bind_session(
            task_id,
            "ast_reset_api",
            expected_session_id=None,
        )

    class _QuiescentLauncher:
        @staticmethod
        def can_reset_session(_session_id: str) -> bool:
            return True

    from src.business.scheduling import scheduler_service as service_module

    monkeypatch.setattr(
        service_module.SchedulerService,
        "_require_launcher",
        lambda self: _QuiescentLauncher(),
    )

    response = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/reset-session")

    assert response.status_code == 200
    assert response.json()["scheduledTaskId"] == task_id
    with ScheduledTaskRepository() as repo:
        assert repo.get(task_id).session_id is None


def test_reset_session_returns_409_while_session_is_busy(
    desktop_api_client: TestClient,
    monkeypatch,
):
    task_id = _make_task(title="忙碌时不重开")
    with ScheduledTaskRepository() as repo:
        repo.cas_bind_session(
            task_id,
            "ast_reset_api_busy",
            expected_session_id=None,
        )

    class _BusyLauncher:
        @staticmethod
        def can_reset_session(_session_id: str) -> bool:
            return False

    from src.business.scheduling import scheduler_service as service_module

    monkeypatch.setattr(
        service_module.SchedulerService,
        "_require_launcher",
        lambda self: _BusyLauncher(),
    )

    response = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/reset-session")

    assert response.status_code == 409
    assert response.json()["detail"] == "scheduled_task_session_busy"
    with ScheduledTaskRepository() as repo:
        assert repo.get(task_id).session_id == "ast_reset_api_busy"


def test_delete_soft_deletes_task(desktop_api_client: TestClient):
    task_id = _make_task(title="待删除")
    resp = desktop_api_client.delete(f"/api/scheduled-tasks/{task_id}")
    assert resp.status_code == 204
    # 再次 GET 应 404（软删后业务层视为不存在）
    resp = desktop_api_client.get(f"/api/scheduled-tasks/{task_id}")
    assert resp.status_code == 404


def test_delete_not_found_returns_404(desktop_api_client: TestClient):
    resp = desktop_api_client.delete("/api/scheduled-tasks/sch_missing")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 历史 runs + takeover
# ---------------------------------------------------------------------------


def test_list_runs_camelcase(desktop_api_client: TestClient):
    task_id = _make_task(title="历史 runs")
    with ScheduledTaskRunRepository() as rr:
        rr.create(
            scheduled_task_id=task_id,
            session_id="ast_run1",
            started_at=__import__("src.utils.timezone", fromlist=["utc_now_naive"]).utc_now_naive(),
        )
    resp = desktop_api_client.get(f"/api/scheduled-tasks/{task_id}/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["scheduledTaskId"] == task_id
    assert item["sessionId"] == "ast_run1"
    assert item["status"] == "running"


def test_list_runs_task_not_found_returns_404(desktop_api_client: TestClient):
    resp = desktop_api_client.get("/api/scheduled-tasks/sch_missing/runs")
    assert resp.status_code == 404


def test_list_runs_projects_skipped_without_fake_session_id(
    desktop_api_client: TestClient,
):
    task_id = _make_task(title="reentry 跳过")
    with ScheduledTaskRunRepository() as rr:
        rr.create_skipped(
            scheduled_task_id=task_id,
        )

    resp = desktop_api_client.get(f"/api/scheduled-tasks/{task_id}/runs")

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["status"] == "skipped"
    assert item["sessionId"] is None
    assert item["startedAt"] is not None


def test_takeover_waiting_user_run_returns_session_id(desktop_api_client: TestClient):
    task_id = _make_task(title="接管测试")
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id=task_id, session_id="ast_takeover_me")
        rr.cas_transition(run.run_id, from_status="running", to_status="waiting_user")
        run_id = run.run_id
    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/runs/{run_id}/takeover")
    assert resp.status_code == 200
    assert resp.json()["sessionId"] == "ast_takeover_me"
    # run 回 running
    with ScheduledTaskRunRepository() as rr:
        assert rr.get(run_id).status == "running"


def test_takeover_repairs_legacy_failed_run_with_missing_session(
    desktop_api_client: TestClient,
):
    task_id = _make_task(
        title="恢复失败会话",
        instruction="重新整理这份周报并说明失败原因",
    )
    session_id = "ast_missing_failed_takeover"
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id=task_id, session_id=session_id)
        rr.cas_transition(run.run_id, from_status="running", to_status="failed")
        run_id = run.run_id
    assert SessionRepository().get_by_id(session_id) is None

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/runs/{run_id}/takeover")

    assert resp.status_code == 200
    assert resp.json() == {
        "sessionId": session_id,
        "recoveryDraft": "重新整理这份周报并说明失败原因",
    }
    repaired = SessionRepository().get_by_id(session_id)
    assert repaired is not None
    assert repaired.source == "scheduled"
    assert repaired.scheduled_task_id == task_id
    assert repaired.is_scheduled == 1
    with ScheduledTaskRunRepository() as rr:
        assert rr.get(run_id).status == "failed"


def test_takeover_recovers_draft_for_existing_empty_scheduled_session(
    desktop_api_client: TestClient,
):
    task_id = _make_task(
        title="恢复空会话",
        instruction="继续整理尚未发出的会议纪要",
    )
    session_id = "ast_existing_empty_takeover"
    ChatService().create_scheduled_session(
        task_id,
        title="恢复空会话",
        session_id=session_id,
    )
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id=task_id, session_id=session_id)
        rr.cas_transition(run.run_id, from_status="running", to_status="failed")
        run_id = run.run_id

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/runs/{run_id}/takeover")

    assert resp.status_code == 200
    assert resp.json() == {
        "sessionId": session_id,
        "recoveryDraft": "继续整理尚未发出的会议纪要",
    }


def test_takeover_does_not_offer_recovery_draft_when_session_has_user_message(
    desktop_api_client: TestClient,
):
    task_id = _make_task(
        title="保留已有对话",
        instruction="不应覆盖已有消息",
    )
    session_id = "ast_existing_message_takeover"
    ChatService().create_scheduled_session(
        task_id,
        title="保留已有对话",
        session_id=session_id,
    )
    MessageRepository().create(
        Message(
            message_id="msg_existing_takeover_user",
            session_id=session_id,
            sequence=1,
            role="user",
            content="我已经补充了接管上下文",
        )
    )
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id=task_id, session_id=session_id)
        rr.cas_transition(run.run_id, from_status="running", to_status="failed")
        run_id = run.run_id

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/runs/{run_id}/takeover")

    assert resp.status_code == 200
    assert resp.json() == {
        "sessionId": session_id,
        "recoveryDraft": None,
    }


def test_takeover_not_found_returns_404(desktop_api_client: TestClient):
    task_id = _make_task(title="接管 not found")
    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/runs/schr_missing/takeover")
    assert resp.status_code == 404


def test_takeover_wrong_task_does_not_mutate_run(desktop_api_client: TestClient):
    owner_task_id = _make_task(title="真正所属任务")
    wrong_task_id = _make_task(title="错误 path 任务")
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(
            scheduled_task_id=owner_task_id,
            session_id="ast_takeover_owner",
        )
        rr.cas_transition(run.run_id, from_status="running", to_status="waiting_user")
        run_id = run.run_id

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{wrong_task_id}/runs/{run_id}/takeover")

    assert resp.status_code == 404
    with ScheduledTaskRunRepository() as rr:
        assert rr.get(run_id).status == "waiting_user"


@pytest.mark.parametrize("status", ["running", "succeeded", "skipped"])
def test_takeover_rejects_statuses_without_takeover_semantics(
    desktop_api_client: TestClient,
    status: str,
):
    task_id = _make_task(title=f"不可接管 {status}")
    with ScheduledTaskRunRepository() as rr:
        if status == "skipped":
            run = rr.create_skipped(scheduled_task_id=task_id)
        else:
            run = rr.create(
                scheduled_task_id=task_id,
                session_id=f"ast_{status}",
            )
            if status == "succeeded":
                run = rr.cas_transition(
                    run.run_id,
                    from_status="running",
                    to_status="succeeded",
                )

    resp = desktop_api_client.post(f"/api/scheduled-tasks/{task_id}/runs/{run.run_id}/takeover")

    assert resp.status_code == 422
    with ScheduledTaskRunRepository() as rr:
        assert rr.get(run.run_id).status == status


# ---------------------------------------------------------------------------
# 确认卡决策 + pending
# ---------------------------------------------------------------------------


def test_confirmation_confirm_creates_task(desktop_api_client: TestClient):
    from src.business.scheduling.scheduling_confirmation_manager import create

    draft = {
        "source_type": "direct",
        "schedule_kind": "one_shot",
        "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
        "instruction": "查竞品价格",
        "title": "确认卡确认",
        "source_ref": "查竞品价格",
    }
    request_id = create(draft, "ast_session_x")
    resp = desktop_api_client.post(
        f"/api/scheduled-tasks/confirmations/{request_id}/decision",
        json={"decision": "confirm", "unattendedAutoApprove": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scheduledTaskId"].startswith("sch_")
    assert data["title"] == "确认卡确认"
    assert data["status"] == "active"


def test_interval_tool_contract_reaches_pending_then_confirmed_task(
    desktop_api_client: TestClient,
):
    """工具契约的 kind=interval 必须贯通 handler→pending→decision→task。"""
    from src.business.agents.tools.assistant_tools import (
        create_create_scheduled_task_handler,
    )
    from src.business.scheduling.scheduling_confirmation_manager import (
        get_scheduling_confirmation_manager,
    )

    handler = create_create_scheduled_task_handler("ast_interval_contract")
    result = json.loads(
        handler(
            source_type="direct",
            schedule_kind="recurring",
            schedule_payload={"kind": "interval", "interval_seconds": 60},
            instruction="每分钟检查一次构建状态",
            title="构建状态检查",
        )
    )

    assert result["success"] is True
    request_id = result["requestId"]
    pending = get_scheduling_confirmation_manager().list_pending("ast_interval_contract")
    assert [item["requestId"] for item in pending] == [request_id]

    resp = desktop_api_client.post(
        f"/api/scheduled-tasks/confirmations/{request_id}/decision",
        json={"decision": "confirm"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["scheduleKind"] == "recurring"
    assert data["nextFireAt"] is not None
    with ScheduledTaskRepository() as repo:
        row = repo.get(data["scheduledTaskId"])
        assert json.loads(row.schedule_payload) == {
            "kind": "interval",
            "interval_seconds": 60,
        }


@pytest.mark.parametrize(
    "schedule_payload",
    [
        {"kind": "interval", "interval_seconds": 1.5},
        {"kind": "interval", "interval_seconds": "1.5"},
        {"kind": "interval", "interval_seconds": 10**100},
        {"kind": "weekly", "weekdays": 1, "time_of_day": "09:00"},
        {"kind": "weekly", "weekdays": ["Monday"], "time_of_day": "09:00"},
    ],
)
def test_confirmation_rejects_invalid_schedule_boundaries_without_insert(
    desktop_api_client: TestClient,
    schedule_payload: dict,
):
    from src.business.scheduling.scheduling_confirmation_manager import create

    with ScheduledTaskRepository() as repo:
        _, before = repo.list_tasks()
    request_id = create(
        {
            "source_type": "direct",
            "schedule_kind": "recurring",
            "schedule_payload": schedule_payload,
            "instruction": "不应落库",
            "title": "非法 payload",
            "source_ref": "不应落库",
        },
        "ast_invalid_payload",
    )

    resp = desktop_api_client.post(
        f"/api/scheduled-tasks/confirmations/{request_id}/decision",
        json={"decision": "confirm"},
    )

    assert resp.status_code == 422
    with ScheduledTaskRepository() as repo:
        _, after = repo.list_tasks()
    assert after == before


def test_invalid_schedule_payload_does_not_create_confirmation_card():
    from src.business.agents.tools.assistant_tools import (
        create_create_scheduled_task_handler,
    )

    class _Manager:
        create_calls = 0

        def create(self, *_args, **_kwargs):
            self.create_calls += 1
            return "scf_should_not_exist"

    manager = _Manager()
    handler = create_create_scheduled_task_handler(
        "ast_invalid_handler",
        confirmation_manager_factory=lambda: manager,
    )

    result = json.loads(
        handler(
            source_type="direct",
            schedule_kind="recurring",
            schedule_payload={"kind": "weekly", "weekdays": "1", "time_of_day": "09:00"},
            instruction="不应生成卡",
        )
    )

    assert result["success"] is False
    assert manager.create_calls == 0


def test_confirmation_accepts_real_frontend_edited_draft(desktop_api_client: TestClient):
    """前端只回传 camelCase 可见字段；内部 schedule/source 必须合并自 pending。"""
    from src.business.scheduling.scheduling_confirmation_manager import create
    from src.data.repos.scheduled_task_repository import ScheduledTaskRepository

    request_id = create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "原始指令",
            "title": "原始标题",
            "source_ref": "原始指令",
            "scheduleDescription": "一次性 7月19日 18:00",
        },
        "ast_frontend_edit",
    )

    resp = desktop_api_client.post(
        f"/api/scheduled-tasks/confirmations/{request_id}/decision",
        json={
            "decision": "confirm",
            "editedDraft": {
                "title": "用户确认标题",
                "instruction": "用户确认后的完整指令",
                "scheduleDescription": "一次性 7月19日 18:00",
                "scheduleKind": "one_shot",
                "sourceType": "direct",
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "用户确认标题"
    assert data["scheduleKind"] == "one_shot"
    with ScheduledTaskRepository() as repo:
        row = repo.get(data["scheduledTaskId"])
        assert row.instruction == "用户确认后的完整指令"


def test_confirmation_cancel_returns_204(desktop_api_client: TestClient):
    from src.business.scheduling.scheduling_confirmation_manager import create

    request_id = create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "x",
            "title": "取消测试",
            "source_ref": "x",
        },
        "ast_cancel",
    )
    resp = desktop_api_client.post(
        f"/api/scheduled-tasks/confirmations/{request_id}/decision",
        json={"decision": "cancel"},
    )
    assert resp.status_code == 204


def test_confirmation_double_submit_returns_404(desktop_api_client: TestClient):
    """first-decision-wins：已结算的 requestId 再次提交 → 404（不泄漏存在性）。"""
    from src.business.scheduling.scheduling_confirmation_manager import create

    request_id = create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "x",
            "title": "二次提交",
            "source_ref": "x",
        },
        "ast_double",
    )
    # 第一次 confirm
    desktop_api_client.post(
        f"/api/scheduled-tasks/confirmations/{request_id}/decision",
        json={"decision": "confirm"},
    )
    # 第二次 → 404
    resp = desktop_api_client.post(
        f"/api/scheduled-tasks/confirmations/{request_id}/decision",
        json={"decision": "cancel"},
    )
    assert resp.status_code == 404


def test_confirmation_pending_list(desktop_api_client: TestClient):
    from src.business.scheduling.scheduling_confirmation_manager import create

    create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "x",
            "title": "pending 展示",
            "source_ref": "x",
        },
        "ast_pending",
    )
    resp = desktop_api_client.get(
        "/api/scheduled-tasks/confirmations/pending?sessionId=ast_pending"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["sessionId"] == "ast_pending"
    assert item["status"] == "pending"
    assert item["draft"]["title"] == "pending 展示"
    assert item["draft"]["instruction"] == "x"
    assert item["draft"]["scheduleKind"] == "one_shot"
    assert item["draft"]["sourceType"] == "direct"
    assert item["unattendedAutoApprove"] is False


def test_confirmation_expiry_is_timezone_aware_for_browser_countdown(
    desktop_api_client: TestClient,
):
    from src.business.scheduling.scheduling_confirmation_manager import create

    create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "x",
            "title": "时区测试",
            "source_ref": "x",
        },
        "ast_expiry_timezone",
    )

    resp = desktop_api_client.get(
        "/api/scheduled-tasks/confirmations/pending?sessionId=ast_expiry_timezone"
    )

    assert resp.status_code == 200
    expires_at = datetime.fromisoformat(resp.json()["items"][0]["expiresAt"])
    assert expires_at.tzinfo is not None, "浏览器倒计时需要无歧义的带时区过期时间"
    assert expires_at.utcoffset() == timedelta(0)


def test_confirmation_pending_without_session_returns_global_card(
    desktop_api_client: TestClient,
):
    from src.business.scheduling.scheduling_confirmation_manager import create

    request_id = create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "global",
            "title": "全局恢复",
            "source_ref": "global",
            "scheduleDescription": "立即",
        },
        "ast_global_pending",
    )

    resp = desktop_api_client.get("/api/scheduled-tasks/confirmations/pending")

    assert resp.status_code == 200
    assert request_id in {item["requestId"] for item in resp.json()["items"]}


def test_confirmation_pending_excludes_other_sessions(desktop_api_client: TestClient):
    from src.business.scheduling.scheduling_confirmation_manager import create

    create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "x",
            "title": "A",
            "source_ref": "x",
        },
        "ast_a",
    )
    create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "x",
            "title": "B",
            "source_ref": "x",
        },
        "ast_b",
    )
    resp = desktop_api_client.get("/api/scheduled-tasks/confirmations/pending?sessionId=ast_a")
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["sessionId"] == "ast_a"


# ---------------------------------------------------------------------------
# 错误映射：token 不进响应正文（守卫测试补强）
# ---------------------------------------------------------------------------


def test_response_body_never_contains_token(desktop_api_client: TestClient):
    """任意 endpoint 的响应正文都不含 session token（守卫测试）。"""
    _make_task(title="token 守卫")
    paths = [
        "/api/scheduled-tasks",
        "/api/scheduled-tasks?status=active",
    ]
    for path in paths:
        resp = desktop_api_client.get(path)
        assert "test-session-token" not in resp.text, f"path {path} leaked token"
