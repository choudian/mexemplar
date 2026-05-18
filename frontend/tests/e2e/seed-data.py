"""Grand Tour e2e 测试种子数据脚本。

在 sidecar 启动前调用，创建 SQLite 数据库并写入测试数据。
sidecar 启动后将直接打开这个已有数据的数据库。
用法：uv run python frontend/tests/e2e/seed-data.py --data-dir <path>
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# 确保项目根目录在 sys.path 中
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.data.models_sqlite import Session, Tool, TeachingFailureRecord
from src.data.repos import ToolRepository, SessionRepository, MessageRepository, TeachingFailureRepository
from src.data.sqlalchemy_manager import get_sqlalchemy_manager
from src.business.agents.config import AgentType


def seed_all(data_dir: str) -> None:
    os.environ["EXEMPLAR_DATA_DIR"] = data_dir
    db_path = os.path.join(data_dir, "mexemplar.db")

    # 初始化数据库管理器（首次调用生效）
    manager = get_sqlalchemy_manager(db_path)
    manager.initialize()

    _seed_assistant_session()
    _seed_skills()
    print("[seed] 测试数据写入完成")


def _seed_assistant_session() -> None:
    """创建一个助手会话和若干历史消息。"""
    session_id = "gt_session_1"
    repo = SessionRepository()
    repo.create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )

    msg_repo = MessageRepository()
    now = datetime.now(timezone.utc)
    messages = [
        ("assistant", "你好！我是你的 AI 助手。有什么我可以帮你的吗？"),
        ("user", "帮我整理一下今天的任务"),
    ]
    for seq, (role, content) in enumerate(messages, start=1):
        msg_repo.create(
            __import__("src.data.models_sqlite", fromlist=["Message"]).Message(
                message_id=f"gt_msg_{seq}",
                session_id=session_id,
                sequence=seq,
                role=role,
                content=content,
                message_type="normal",
                is_archived=False,
                tool_calls=None,
                tool_call_id=None,
                tool_name=None,
                compressed_range=None,
                created_at=now,
            )
        )
    print(f"[seed] 助手会话 {session_id} + {len(messages)} 条消息")


def _seed_skills() -> None:
    """创建已发布、待考核、失败三种状态的技能。"""
    repo = ToolRepository()
    skills = [
        Tool(
            tool_id="gt_published_1",
            tool_name="邮件分类",
            description="自动将收到的客户邮件按优先级分类",
            source="teaching",
            status="published",
            trial_success_count=3,
            trial_count=3,
            execution_code='print("classify email")',
            code_language="python",
            code_version="1.0",
            steps=[],
            parameters=[],
        ),
        Tool(
            tool_id="gt_published_2",
            tool_name="报告生成",
            description="根据分类结果生成每日摘要报告",
            source="teaching",
            status="published",
            trial_success_count=3,
            trial_count=3,
            execution_code='print("generate report")',
            code_language="python",
            code_version="1.0",
            steps=[],
            parameters=[],
        ),
        Tool(
            tool_id="gt_pending_1",
            tool_name="数据清洗",
            description="自动清洗和格式化客户数据",
            source="intent",
            status="pending",
            trial_success_count=0,
            trial_count=0,
            execution_code='print("clean data")',
            code_language="python",
            code_version="1.0",
            steps=[],
            parameters=[],
        ),
    ]
    for skill in skills:
        repo.create(skill)
    print(f"[seed] {len(skills)} 个技能")

    # 失败记录
    failure_repo = TeachingFailureRepository()
    failure_repo.create(
        TeachingFailureRecord(
            record_id="gt_fail_1",
            workflow_id="gt_wf_fail_1",
            tool_name="旧版导入",
            failed_stage="trial",
            error_summary="执行超时",
            error_type="TimeoutError",
            status="active",
            retry_count=1,
        )
    )
    print("[seed] 1 条失败记录")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    seed_all(args.data_dir)
