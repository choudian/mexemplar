from src.execution.desktop_trial_runner import run_desktop_trial


def test_desktop_trial_subprocess_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_desktop_trial(
        """
async def execute() -> dict:
    return {"ok": True, "summary": "done", "details": {"x": 1}}
""",
        "trial-ok",
    )

    assert result.ok is True
    assert result.exit_code == 0
    assert result.summary == "done"


def test_desktop_trial_execute_tool_uses_desktop_runner(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import src.data.repositories as repositories
    from src.business.agents.tools import trial_tools
    from src.execution.desktop_trial_models import TrialResult
    from src.utils import events

    class _ToolRepository:
        def get_by_workflow_id(self, workflow_id):
            assert workflow_id == "wf-1"
            return SimpleNamespace(execution_code="async def execute() -> dict:\n    return {}\n")

    monkeypatch.setattr(repositories, "ToolRepository", _ToolRepository)
    seen = []
    events.clear_all()
    events.connect(
        "desktop_trial_preview_ready",
        lambda sender, **kwargs: seen.append(("preview", kwargs["workflow_id"])) or True,
        weak=False,
    )
    events.connect(
        "desktop_trial_finished",
        lambda sender, **kwargs: seen.append(("finished", kwargs["workflow_id"])),
        weak=False,
    )

    def _fake_run(code, trial_id):
        assert "async def execute" in code
        return TrialResult(
            ok=True,
            summary="done",
            details={"x": 1},
            exit_code=0,
            timed_out=False,
            stdout_path=tmp_path / "stdout.log",
            stderr_path=tmp_path / "stderr.log",
            trial_id=trial_id,
        )

    monkeypatch.setattr(trial_tools, "run_desktop_trial", _fake_run)
    tools = {tool.name: tool for tool in trial_tools.create_desktop_trial_tools("wf-1")}

    payload = __import__("json").loads(tools["execute_tool"].handler({}))

    assert payload["ok"] is True
    assert payload["summary"] == "done"
    assert seen == [("preview", "wf-1"), ("finished", "wf-1")]
    events.clear_all()


def test_desktop_trial_execute_tool_honors_preview_cancel(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import src.data.repositories as repositories
    from src.business.agents.tools import trial_tools
    from src.utils import events

    class _ToolRepository:
        def get_by_workflow_id(self, workflow_id):
            assert workflow_id == "wf-2"
            return SimpleNamespace(execution_code="async def execute() -> dict:\n    return {}\n")

    monkeypatch.setattr(repositories, "ToolRepository", _ToolRepository)
    events.clear_all()
    events.connect(
        "desktop_trial_preview_ready",
        lambda sender, **kwargs: False,
        weak=False,
    )

    def _must_not_run(code, trial_id):
        raise AssertionError("runner should not start after preview cancel")

    monkeypatch.setattr(trial_tools, "run_desktop_trial", _must_not_run)
    tools = {tool.name: tool for tool in trial_tools.create_desktop_trial_tools("wf-2")}

    payload = __import__("json").loads(tools["execute_tool"].handler({}))

    assert payload["ok"] is False
    assert payload["details"]["cancelled"] is True
    assert payload["details"]["reason"] == "desktop_trial_preview_cancelled"
    assert payload["stdout_path"] is None
    assert payload["stderr_path"] is None
    events.clear_all()


def test_desktop_trial_execute_tool_runs_without_preview_listener(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import src.data.repositories as repositories
    from src.business.agents.tools import trial_tools
    from src.execution.desktop_trial_models import TrialResult
    from src.utils import events

    class _ToolRepository:
        def get_by_workflow_id(self, workflow_id):
            assert workflow_id == "wf-3"
            return SimpleNamespace(execution_code="async def execute() -> dict:\n    return {}\n")

    monkeypatch.setattr(repositories, "ToolRepository", _ToolRepository)
    events.clear_all()

    def _fake_run(code, trial_id):
        assert "async def execute" in code
        return TrialResult(
            ok=True,
            summary="done without preview listener",
            details={},
            exit_code=0,
            timed_out=False,
            stdout_path=tmp_path / "stdout.log",
            stderr_path=tmp_path / "stderr.log",
            trial_id=trial_id,
        )

    monkeypatch.setattr(trial_tools, "run_desktop_trial", _fake_run)
    tools = {tool.name: tool for tool in trial_tools.create_desktop_trial_tools("wf-3")}

    payload = __import__("json").loads(tools["execute_tool"].handler({}))

    assert payload["ok"] is True
    assert payload["summary"] == "done without preview listener"
    events.clear_all()


def test_desktop_trial_execute_tool_runs_after_preview_listener_error(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import src.data.repositories as repositories
    from src.business.agents.tools import trial_tools
    from src.execution.desktop_trial_models import TrialResult
    from src.utils import events

    class _ToolRepository:
        def get_by_workflow_id(self, workflow_id):
            assert workflow_id == "wf-4"
            return SimpleNamespace(execution_code="async def execute() -> dict:\n    return {}\n")

    monkeypatch.setattr(repositories, "ToolRepository", _ToolRepository)
    events.clear_all()

    def _broken_listener(sender, **kwargs):
        raise RuntimeError("preview bridge failed")

    events.connect("desktop_trial_preview_ready", _broken_listener, weak=False)

    def _fake_run(code, trial_id):
        assert "async def execute" in code
        return TrialResult(
            ok=True,
            summary="done after preview listener error",
            details={},
            exit_code=0,
            timed_out=False,
            stdout_path=tmp_path / "stdout.log",
            stderr_path=tmp_path / "stderr.log",
            trial_id=trial_id,
        )

    monkeypatch.setattr(trial_tools, "run_desktop_trial", _fake_run)
    tools = {tool.name: tool for tool in trial_tools.create_desktop_trial_tools("wf-4")}

    payload = __import__("json").loads(tools["execute_tool"].handler({}))

    assert payload["ok"] is True
    assert payload["summary"] == "done after preview listener error"
    events.clear_all()
