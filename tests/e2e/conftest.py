from __future__ import annotations

import os
import time
import json
import shutil
import socket
import sys
import threading
import uuid
from src.utils.timezone import from_timestamp_utc_naive
from collections import deque
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from src.business.ai.llm_client import LLMResponse
from src.data.models_sqlite import (
    SkillComposition,
    SkillCompositionMember,
    TeachingFailureRecord,
    Tool,
)
from src.data.repositories import (
    SkillCompositionRepository,
    TeachingFailureRepository,
    ToolRepository,
)
from src.utils.events import RecordingEventData, connect, emit
from tests.e2e.robot import TestRobot


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        key = (service, username)
        if key not in self._store:
            raise PasswordDeleteError("password not found")
        del self._store[key]


class ScriptedLLMClient:
    def __init__(self) -> None:
        self._responses: deque[Any] = deque()
        self._lock = threading.Lock()

    def extend(self, responses: Iterable[Any]) -> None:
        with self._lock:
            self._responses.extend(responses)

    def push(self, *responses: Any) -> None:
        self.extend(responses)

    def remaining(self) -> int:
        with self._lock:
            return len(self._responses)

    def chat(self, prompt: str, **kwargs) -> str:
        response = self._pop()
        return response if isinstance(response, str) else (response.content or "")

    def chat_with_tools(self, messages, tools, **kwargs) -> LLMResponse:
        response = self._pop()
        if isinstance(response, LLMResponse):
            return response
        raise AssertionError(
            f"ScriptedLLMClient 期望 LLMResponse，但拿到了 {type(response).__name__}"
        )

    def _pop(self) -> Any:
        with self._lock:
            if not self._responses:
                raise AssertionError("ScriptedLLMClient 没有预置响应可用")
            return self._responses.popleft()


def _reserve_websocket_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class E2ERuntime:
    root: Path
    keyring_service_name: str
    keyring: InMemoryKeyring


def _reset_runtime_singletons() -> None:
    import src.business.memory.assistant_memory as memory_module
    import src.data.duckdb_manager as duckdb_module
    import src.data.sqlalchemy_manager as sqlalchemy_module
    import src.data.unified_config as unified_config_module
    from src.recording.browser_recorder import BrowserRecorder
    from src.utils.events import clear_all

    clear_all()

    duckdb_instance = duckdb_module._duckdb_instance
    if duckdb_instance is not None:
        try:
            duckdb_instance.close()
        except Exception:
            pass
    duckdb_module._duckdb_instance = None

    sqlalchemy_instance = sqlalchemy_module._sqlalchemy_instance
    if sqlalchemy_instance is not None:
        try:
            sqlalchemy_instance.close()
        except Exception:
            pass
    sqlalchemy_module._sqlalchemy_instance = None

    unified_config = unified_config_module._unified_config_manager
    if unified_config is not None:
        try:
            unified_config._sa.close()
        except Exception:
            pass
    unified_config_module._unified_config_manager = None

    memory_module._memory_manager = None
    BrowserRecorder._shared_ws_server = None


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args) -> None:  # noqa: A003
        return


@pytest.fixture(scope="session")
def require_e2e_opt_in():
    if os.environ.get("EXEMPLAR_RUN_E2E_GUI") != "1":
        pytest.skip("设置 EXEMPLAR_RUN_E2E_GUI=1 后才会执行 headful GUI E2E 测试")


@pytest.fixture(scope="session")
def real_app(require_e2e_opt_in):
    os.environ.pop("QT_QPA_PLATFORM", None)
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(scope="session")
def local_test_server(require_e2e_opt_in):
    fixtures_dir = Path(__file__).parent / "fixtures"
    handler = partial(_QuietStaticHandler, directory=str(fixtures_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}/test_page.html"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def isolated_runtime(monkeypatch):
    runtime_base = Path(__file__).resolve().parent / ".runtime"
    runtime_base.mkdir(parents=True, exist_ok=True)
    for stale_dir in runtime_base.iterdir():
        if stale_dir.is_dir():
            shutil.rmtree(stale_dir, ignore_errors=True)

    runtime_root = runtime_base / uuid.uuid4().hex
    service_name = f"exemplar-e2e-{uuid.uuid4().hex[:8]}"
    memory_keyring = InMemoryKeyring()

    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(runtime_root))
    monkeypatch.setenv("EXEMPLAR_KEYRING_SERVICE_NAME", service_name)

    import keyring

    original_keyring = keyring.get_keyring()
    keyring.set_keyring(memory_keyring)

    _reset_runtime_singletons()
    runtime_root.mkdir(parents=True, exist_ok=True)
    memory_keyring.set_password(service_name, "anthropic_api_key", "sk-e2e-test")

    try:
        yield E2ERuntime(
            root=runtime_root,
            keyring_service_name=service_name,
            keyring=memory_keyring,
        )
    finally:
        _reset_runtime_singletons()
        keyring.set_keyring(original_keyring)
        shutil.rmtree(runtime_root, ignore_errors=True)


@pytest.fixture
def mock_llm(monkeypatch, request):
    if request.node.get_closest_marker("real_llm"):
        yield None
        return

    scripted = ScriptedLLMClient()
    patched_cls = type(
        "PatchedLangChainLLMClient",
        (),
        {
            "__init__": lambda self, *args, **kwargs: None,
            "chat": lambda self, *args, **kwargs: scripted.chat(*args, **kwargs),
            "chat_with_tools": lambda self, *args, **kwargs: scripted.chat_with_tools(
                *args, **kwargs
            ),
        },
    )

    import src.business.ai.llm_client as llm_module
    import src.business.services.skill_composition.service as composition_service_module

    monkeypatch.setattr(llm_module, "LangChainLLMClient", patched_cls)
    monkeypatch.setattr(
        composition_service_module,
        "LangChainLLMClient",
        patched_cls,
        raising=False,
    )
    yield scripted


@pytest.fixture
def main_window(real_app, isolated_runtime, mock_llm, monkeypatch):
    from src.ui.main_window import MainWindow
    from src.data.unified_config import UnifiedConfigManager

    monkeypatch.setattr(MainWindow, "_warmup_orchestrator_async", lambda self: None)
    monkeypatch.setattr(
        UnifiedConfigManager,
        "get_websocket_port",
        lambda self: _reserve_websocket_port(),
    )

    window = MainWindow()
    window.show()
    window.resize(1280, 800)
    window.raise_()
    window.activateWindow()
    QTest.qWait(600)

    try:
        yield window
    finally:
        window.close()
        QTest.qWait(400)


@pytest.fixture
def robot(main_window, request):
    timeout_profile = "real" if request.node.get_closest_marker("real_llm") else "mock"
    test_robot = TestRobot(main_window, timeout_profile=timeout_profile)
    if main_window.browser_recorder is not None:
        main_window.browser_recorder.playwright_driver.on_browser_ready = test_robot.browser.attach
    return test_robot


@pytest.fixture
def event_log():
    signal_names = [
        "agent_error",
        "requirement_confirmed",
        "code_completed",
        "review_passed",
        "review_failed",
        "tool_saved",
        "trial_success",
        "trial_failed",
        "triage_completed",
        "tool_published",
        "teaching_failure_updated",
        "teaching_failure_resolved",
        "teaching_failure_retrying",
    ]
    events: dict[str, list[dict[str, Any]]] = {name: [] for name in signal_names}
    disconnectors = []

    for name in signal_names:
        def handler(sender, _name=name, **kwargs):
            events[_name].append(kwargs)

        disconnectors.append((name, handler, connect(name, handler, weak=False)))

    try:
        yield events
    finally:
        from src.utils.events import _signals

        for name, handler, _ in disconnectors:
            try:
                _signals.signal(name).disconnect(handler)
            except Exception:
                pass


@pytest.fixture
def tool_repo():
    return ToolRepository()


@pytest.fixture
def failure_repo():
    return TeachingFailureRepository()


@pytest.fixture
def composition_repo():
    return SkillCompositionRepository()


@pytest.fixture
def published_tool_factory():
    def factory(
        *,
        tool_name: str = "已发布技能",
        description: str = "测试技能",
        parameters: list[dict] | None = None,
        code: str | None = None,
        execution_strategy: str = "api",
        workflow_id: str | None = None,
        source: str = "intent",
        trial_success_count: int = 3,
        tool_id: str | None = None,
    ) -> Tool:
        tool = Tool(
            tool_id=tool_id or f"tool_{uuid.uuid4().hex[:8]}",
            tool_name=tool_name,
            description=description,
            parameters=parameters or [],
            execution_code=code
            or (
                "async def execute(**kwargs):\n"
                "    return {'success': True, 'message': 'ok', 'data': kwargs}\n"
            ),
            execution_strategy=execution_strategy,
            dependencies=[],
            steps=[],
            workflow_id=workflow_id or f"wf_{uuid.uuid4().hex[:8]}",
            source=source,
            status="published",
            trial_success_count=trial_success_count,
        )
        return ToolRepository().create(tool)

    return factory


@pytest.fixture
def pending_tool_factory():
    def factory(
        *,
        tool_name: str = "待考核技能",
        description: str = "待考核测试技能",
        parameters: list[dict] | None = None,
        code: str | None = None,
        execution_strategy: str = "api",
        workflow_id: str | None = None,
        source: str = "intent",
        trial_success_count: int = 0,
        tool_id: str | None = None,
    ) -> Tool:
        tool = Tool(
            tool_id=tool_id or f"tool_{uuid.uuid4().hex[:8]}",
            tool_name=tool_name,
            description=description,
            parameters=parameters or [],
            execution_code=code
            or (
                "async def execute(**kwargs):\n"
                "    return {'success': True, 'message': 'ok', 'data': kwargs}\n"
            ),
            execution_strategy=execution_strategy,
            dependencies=[],
            steps=[],
            workflow_id=workflow_id or f"wf_{uuid.uuid4().hex[:8]}",
            source=source,
            status="pending",
            trial_success_count=trial_success_count,
        )
        return ToolRepository().create(tool)

    return factory


@pytest.fixture
def failure_record_factory():
    def factory(
        *,
        workflow_id: str | None = None,
        tool_name: str = "失败技能",
        failed_stage: str = "pm",
        error_summary: str = "测试失败",
        error_type: str = "test_error",
        status: str = "active",
        retry_count: int = 1,
    ) -> TeachingFailureRecord:
        record = TeachingFailureRecord(
            record_id=f"failure_{uuid.uuid4().hex[:8]}",
            workflow_id=workflow_id or f"wf_{uuid.uuid4().hex[:8]}",
            tool_name=tool_name,
            failed_stage=failed_stage,
            error_summary=error_summary,
            error_type=error_type,
            status=status,
            retry_count=retry_count,
        )
        return TeachingFailureRepository().create(record)

    return factory


@pytest.fixture
def skill_composition_factory():
    def factory(
        *,
        composition_name: str = "测试组合",
        tool_ids: list[str],
        mode: str = "range",
        status: str = "draft",
        needs_review: bool = False,
        description: str | None = None,
        applicability: str = "用于测试",
        assistant_enabled: bool = True,
        recommend_order: bool = False,
        composition_id: str | None = None,
    ) -> SkillComposition:
        resolved_composition_id = composition_id or f"comp_{uuid.uuid4().hex[:8]}"
        composition = SkillComposition(
            composition_id=resolved_composition_id,
            composition_name=composition_name,
            description=description,
            applicability=applicability,
            mode=mode,
            status=status,
            assistant_enabled=assistant_enabled,
            recommend_order=recommend_order,
            needs_review=needs_review,
        )
        members = [
            SkillCompositionMember(
                member_id=f"member_{uuid.uuid4().hex[:8]}",
                composition_id=resolved_composition_id,
                tool_id=tool_id,
                selected_order=index,
                execution_order=index if mode == "ordered" else None,
            )
            for index, tool_id in enumerate(tool_ids, start=1)
        ]
        SkillCompositionRepository().create(composition, members)
        return composition

    return factory


@pytest.fixture
def simulate_recording_completion(main_window):
    def _write_duckdb_recording(recording_id: str, action_count: int) -> None:
        """写入模拟录制数据到 DuckDB，让 PM Agent 有数据可分析"""
        from src.data.duckdb_manager import DuckDBManager

        db = DuckDBManager()
        if db.conn is None:
            db.initialize()
        now = time.time()

        db.insert(
            "recording_sessions",
            {
                "recording_id": recording_id,
                "status": "completed",
                "recording_mode": "browser",
                "browser_type": "chromium",
                "start_time": from_timestamp_utc_naive(now - 10),
                "end_time": from_timestamp_utc_naive(now),
                "metadata": json.dumps({"url": "https://www.baidu.com"}, ensure_ascii=False),
            },
            auto_commit=True,
        )

        actions = [
            {
                "recording_id": recording_id,
                "sequence_number": 1,
                "action_type": "navigate",
                "recording_mode": "browser",
                "url": "https://www.baidu.com",
                "parameters": json.dumps({"url": "https://www.baidu.com"}, ensure_ascii=False),
                "timestamp": from_timestamp_utc_naive(now - 9),
            },
            {
                "recording_id": recording_id,
                "sequence_number": 2,
                "action_type": "click",
                "recording_mode": "browser",
                "dom_element": json.dumps({
                    "tag": "input",
                    "type": "text",
                    "id": "kw",
                    "name": "wd",
                    "placeholder": "请输入搜索关键词",
                }, ensure_ascii=False),
                "parameters": json.dumps({"selector": "#kw"}, ensure_ascii=False),
                "timestamp": from_timestamp_utc_naive(now - 7),
            },
            {
                "recording_id": recording_id,
                "sequence_number": 3,
                "action_type": "type",
                "recording_mode": "browser",
                "dom_element": json.dumps({
                    "tag": "input",
                    "type": "text",
                    "id": "kw",
                    "name": "wd",
                }, ensure_ascii=False),
                "parameters": json.dumps({"text": "Python教程", "selector": "#kw"}, ensure_ascii=False),
                "timestamp": from_timestamp_utc_naive(now - 5),
            },
            {
                "recording_id": recording_id,
                "sequence_number": 4,
                "action_type": "click",
                "recording_mode": "browser",
                "dom_element": json.dumps({
                    "tag": "input",
                    "type": "submit",
                    "id": "su",
                    "value": "百度一下",
                }, ensure_ascii=False),
                "parameters": json.dumps({"selector": "#su"}, ensure_ascii=False),
                "timestamp": from_timestamp_utc_naive(now - 3),
            },
        ]
        for action in actions[:action_count]:
            db.insert("actions", action, auto_commit=True)

    def run(*, workflow_id: str | None = None, action_count: int = 3) -> str:
        recording_id = workflow_id or f"rec_{uuid.uuid4().hex[:8]}"
        _write_duckdb_recording(recording_id, action_count)
        assert main_window._ensure_agent_bridge(timeout=10.0)
        main_window._on_switch_to_intent_page()
        emit(
            "recording_completed",
            event_data=RecordingEventData(
                session_id=recording_id,
                recording_mode="browser",
                start_time=time.time() - 1,
                end_time=time.time(),
                action_count=action_count,
            ),
        )
        return recording_id

    return run
