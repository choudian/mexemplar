"""build_task_graph 工具 handler 安全测试。

确保 LLM 经工具入口注入的特权字段（workspaceRoot）在落库前被剥离——该字段只允许
受信的 proposal_bridge 直连 service 设置（026 C2）。
"""

from src.business.agents.tools.assistant_tools import create_build_task_graph_handler


class _FakeTaskGraphService:
    """记录传给 build_task_graph 的 nodes，避免连库与 scheduler 副作用。"""

    def __init__(self) -> None:
        self.captured_nodes: list[dict] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def build_task_graph(self, *, session_id, nodes, dependencies, user_message_sequence):
        self.captured_nodes = nodes
        # graphId=None 避免触发 _trigger_graph_scheduler_start 真实调度
        return {"graphId": None}


def test_build_task_graph_handler_strips_workspace_root_injection():
    """LLM 注入的 workspaceRoot / workspace_root 必须在 handler 层剥离。

    Regression (026 C2): build_task_graph 工具同时挂给主助理与规划专员，handler 曾把
    nodes 原样透传 service.build_task_graph，service 直接 node.get("workspaceRoot")
    落库为 task.workspace_root。LLM（或 prompt injection）在 node 里带上任意路径即可
    重定向执行体 blast radius，且 is_improvement_workspace_root 对该路径为 False，
    proposal 沙箱守卫不激活。
    """
    fake = _FakeTaskGraphService()
    handler = create_build_task_graph_handler(
        "session-c2",
        user_message_sequence_provider=lambda: 1,
        service_factory=lambda: fake,
    )

    handler(
        nodes=[
            {
                "nodeId": "n1",
                "title": "t1",
                "description": "d1",
                "workspaceRoot": "/evil/workspace-1",
            },
            {
                "nodeId": "n2",
                "title": "t2",
                "description": "d2",
                "workspace_root": "/evil/workspace-2",
            },
        ]
    )

    assert fake.captured_nodes is not None
    for node in fake.captured_nodes:
        assert "workspaceRoot" not in node
        assert "workspace_root" not in node
