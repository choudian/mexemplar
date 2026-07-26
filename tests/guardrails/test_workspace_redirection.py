"""门卫：执行体 workspace 重定向注入（坐实 D4 承重假设 / FR-014a 文件爆炸半径）。

经 AgentLoop 端到端验证：当 ``AgentConfig.workspace_root`` 注入为指定根目录时，
执行体的 write_file 实际以该根为 workspace——根内放行；根外在 allow_all 关闭时 fail-closed，开启时经确认链放行（反转自 2026-07-26，原 FR-003 外部写硬拒改为可由全部允许覆盖）。

设计要点：
- ``monkeypatch.chdir`` 到一个**与注入根不同的临时目录**，确保 ``cwd != workspace_root``。
  这样若 agent_loop 仍错误地用 ``Path.cwd()``（D2 病灶），两个测试都会失败（RED）；
  改用注入值后都通过（GREEN）。
- write_file 经 AgentLoop 带 confirmation pre_hook，测试环境用 ``set_auto_approve_enabled``
  放行该 pre_hook，使 handler 的 path 检查（真正的爆炸半径闸门）能被执行到；teardown
  复位确认状态以免污染其他测试。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType
from src.business.agents.tools import builtin_general_tools as general_tools
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from tests.conftest import MockLLMClient


@pytest.fixture(autouse=True)
def _auto_approve_builtin_tools():
    """放行 write_file 的 confirmation pre_hook，让 path 检查能跑到；用完复位。"""
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)
    yield
    general_tools.reset_confirmation_state_for_tests()


def _run_write(workspace_root: Path, write_path: Path, session_id: str, mock_config) -> dict:
    """经 AgentLoop 端到端调用 write_file，workspace_root 注入到 AgentConfig。

    返回 write_file 产生的工具结果 envelope（已 json.loads）。
    """
    config = AgentConfig(
        agent_type=AgentType.PM,
        system_prompt="test",
        max_iterations=5,
        workspace_root=workspace_root,
    )
    write_tool = next(td for td in general_tools.BUILTIN_GENERAL_TOOLS if td.name == "write_file")
    loop = AgentLoop(
        config,
        MockLLMClient(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallInfo(
                            id="call-1",
                            name="write_file",
                            args={"path": str(write_path), "content": "x"},
                        )
                    ],
                ),
                LLMResponse(content="done", tool_calls=[]),
            ]
        ),
        mock_config,
    )
    loop.run(session_id=session_id, user_input="go", tools=[write_tool])
    ctx = loop._get_context_manager(session_id)
    tool_msgs = [m for m in ctx._msg_repo.get_context(session_id) if m.role == "tool"]
    assert tool_msgs, "write_file 未产生工具结果"
    return json.loads(tool_msgs[0].content)


def test_injected_workspace_root_allows_write_inside(tmp_path, monkeypatch, mock_config):
    """注入 workspace_root 后，根内写文件放行。"""
    wt_root = tmp_path / "wt_root"
    wt_root.mkdir()
    cwd_dir = tmp_path / "cwd_dir"  # cwd 与注入根不同，确保走注入值而非 cwd
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)

    payload = _run_write(wt_root, wt_root / "inside.txt", "ws-redir-inside", mock_config)

    assert payload["outcome"] == "success"
    assert (wt_root / "inside.txt").exists()


def test_injected_workspace_root_resolves_relative_write_inside(tmp_path, monkeypatch, mock_config):
    """相对路径必须按注入 workspace_root 解析，而不是按进程 cwd 解析。"""
    wt_root = tmp_path / "wt_root"
    wt_root.mkdir()
    cwd_dir = tmp_path / "cwd_dir"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)

    payload = _run_write(wt_root, Path("inside.txt"), "ws-redir-relative", mock_config)

    assert payload["outcome"] == "success"
    assert (wt_root / "inside.txt").read_text(encoding="utf-8") == "x"
    assert not (cwd_dir / "inside.txt").exists()


def test_injected_workspace_root_allows_write_outside_under_allow_all(tmp_path, monkeypatch, mock_config):
    """allow_all 开启时，根外写文件经确认链放行（反转 FR-003 外部写硬边界）。

    autouse fixture 已开 allow_all=True，越界写走 _confirm_or_reject 短路放行并记审计，
    落盘成功。
    """
    wt_root = tmp_path / "wt_root"
    wt_root.mkdir()
    cwd_dir = tmp_path / "cwd_dir"  # cwd 内、wt_root 外的安全越界目标
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)
    outside = cwd_dir / "outside.txt"

    payload = _run_write(wt_root, outside, "ws-redir-outside-allow", mock_config)

    assert payload["outcome"] == "success"
    assert outside.exists()
    assert outside.read_text(encoding="utf-8") == "x"
