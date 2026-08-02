"""
SQLAlchemy ORM 模型 - SQLite 数据库 (mexemplar.db)

包含：tools, sessions, messages, workflow_transitions (Agent 会话相关)
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    DDL,
    event,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """所有模型的基类"""

    pass


class Tool(Base):
    """工具定义表"""

    __tablename__ = "tools"

    tool_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, server_default="[]")
    steps: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, server_default="[]")

    # 代码执行相关字段
    execution_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    code_language: Mapped[str] = mapped_column(String(20), default="python")
    code_version: Mapped[str] = mapped_column(String(20), default="1.0")
    execution_strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dependencies: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, server_default="[]")

    # 意图和试用相关字段
    source_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    trial_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_tool_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Agent 工作流相关字段
    workflow_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    trial_success_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Tool(tool_id={self.tool_id!r}, tool_name={self.tool_name!r})>"


class SkillComposition(Base):
    """技能组合定义表"""

    __tablename__ = "skill_compositions"

    composition_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    composition_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applicability: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="range")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    assistant_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recommend_order: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<SkillComposition(composition_id={self.composition_id!r}, "
            f"composition_name={self.composition_name!r}, status={self.status!r})>"
        )


class SkillCompositionMember(Base):
    """技能组合成员关系表"""

    __tablename__ = "skill_composition_members"
    __table_args__ = (
        UniqueConstraint("composition_id", "tool_id", name="uq_skill_composition_member_tool"),
    )

    member_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    composition_id: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(50), nullable=False)
    selected_order: Mapped[int] = mapped_column(Integer, default=0)
    execution_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return (
            f"<SkillCompositionMember(member_id={self.member_id!r}, "
            f"composition_id={self.composition_id!r}, tool_id={self.tool_id!r})>"
        )


# ===== Agent 会话相关模型 =====


class Session(Base):
    """会话表 ORM 模型"""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    workflow_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    # v30（033 调度中心）：会话来源——区分「用户手动开」与「定时任务触发」。
    # 聊天屏列表按 source='scheduled' 排除（FR-021）；Segment opt-out 用 is_scheduled 廉价判定。
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    scheduled_task_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_scheduled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def get_tool_id_set(self) -> Optional[set]:
        """解析 tool_ids JSON 字段为 set。None 表示全部工具。"""
        if not self.tool_ids:
            return None
        import json

        parsed = json.loads(self.tool_ids)
        if isinstance(parsed, dict):
            tool_ids = parsed.get("member_tool_ids") or parsed.get("tool_ids") or []
            return set(tool_ids)
        return set(parsed)

    def get_composition_id_set(self) -> Optional[set]:
        """从 tool_ids JSON dict 中提取 composition_id。

        Trial session 的 tool_ids 格式为
        ``{"composition_id": "...", "member_tool_ids": [...]}``；
        list 格式（普通授权 session）不含 composition_id。

        Returns:
            包含单个 composition_id 的 set，或 None（= 全量放行，
            与 DynamicToolManager 的 None 语义一致）。
        """
        if not self.tool_ids:
            return None
        import json

        parsed = json.loads(self.tool_ids)
        if isinstance(parsed, dict):
            composition_id = parsed.get("composition_id")
            if composition_id:
                return {composition_id}
        return None

    def parse_tool_ids(self) -> tuple[Optional[set], Optional[set]]:
        """单次解析 tool_ids JSON，返回 (tool_id_set, composition_id_set)。

        避免连续调用 get_tool_id_set + get_composition_id_set 时重复解析。
        """
        if not self.tool_ids:
            return None, None
        import json

        parsed = json.loads(self.tool_ids)
        if isinstance(parsed, dict):
            tool_ids = set(parsed.get("member_tool_ids") or parsed.get("tool_ids") or [])
            composition_id = parsed.get("composition_id")
            return (tool_ids if tool_ids else None, {composition_id} if composition_id else None)
        return (set(parsed) if parsed else None), None

    def __repr__(self) -> str:
        return f"<Session(session_id={self.session_id!r}, agent_type={self.agent_type!r}, status={self.status!r})>"


class Message(Base):
    """消息表 ORM 模型"""

    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_type: Mapped[str] = mapped_column(String(20), default="normal")
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_calls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compressed_range: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # v34：本次 LLM 调用的 token 用量 JSON；provider 未上报时为 NULL。
    token_usage: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<Message(message_id={self.message_id!r}, session_id={self.session_id!r}, sequence={self.sequence!r})>"


class WorkflowTransition(Base):
    """工作流交接记录表 ORM 模型"""

    __tablename__ = "workflow_transitions"

    transition_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(50), nullable=False)
    from_session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<WorkflowTransition(transition_id={self.transition_id!r}, workflow_id={self.workflow_id!r})>"


# ===== 办公助理相关模型 =====


class AssistantProfile(Base):
    """助理用户偏好档案表"""

    __tablename__ = "assistant_profile"

    profile_id: Mapped[str] = mapped_column(String(50), primary_key=True, default="default")
    display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    style: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<AssistantProfile(profile_id={self.profile_id!r}, display_name={self.display_name!r})>"


class PendingAssistantTask(Base):
    """助理异步任务队列表"""

    __tablename__ = "pending_assistant_tasks"

    task_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<PendingAssistantTask(task_id={self.task_id!r}, task_type={self.task_type!r}, status={self.status!r})>"


class AssistantTask(Base):
    """Assistant 协作任务图中的持久工作项。"""

    __tablename__ = "assistant_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_dispatch', 'running', 'suspended', "
            "'completed', 'abandoned', 'cancelled')",
            name="ck_assistant_tasks_status",
        ),
        CheckConstraint(
            "suspend_reason IS NULL OR suspend_reason IN "
            "('waiting_user', 'waiting_system', 'user_stop', "
            "'budget_exhausted', 'quota_exhausted', 'interrupted', 'blocked_by_defect')",
            name="ck_assistant_tasks_suspend_reason",
        ),
        CheckConstraint(
            "(status = 'suspended' AND suspend_reason IS NOT NULL) OR "
            "(status != 'suspended' AND suspend_reason IS NULL)",
            name="ck_assistant_tasks_suspend_reason_required",
        ),
        CheckConstraint(
            "waiting_on IS NULL OR waiting_on IN ('user', 'assistant', 'system')",
            name="ck_assistant_tasks_waiting_on",
        ),
        # waiting_on 与 suspend_reason 同生同灭：不允许"有原因却不知道等谁"或反之。
        CheckConstraint(
            "(status = 'suspended' AND waiting_on IS NOT NULL) OR "
            "(status != 'suspended' AND waiting_on IS NULL)",
            name="ck_assistant_tasks_waiting_on_required",
        ),
        CheckConstraint(
            "assignee_type IS NULL OR assignee_type IN ('ephemeral_subagent', 'specialist')",
            name="ck_assistant_tasks_assignee_type",
        ),
        Index("idx_assistant_tasks_graph_status", "graph_id", "status"),
        Index("idx_assistant_tasks_graph_parent", "graph_id", "parent_task_id"),
        Index("idx_assistant_tasks_session_message", "session_id", "user_message_sequence"),
        Index("idx_assistant_tasks_graph_version", "graph_id", "task_version"),
    )

    task_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(50), nullable=False)
    root_task_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    parent_task_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    user_message_sequence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_dispatch")
    suspend_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # 暂停时球在谁手上（user/assistant/system）。这是持久化的通知意图——
    # 落库即等于通知已发出，派发时直接读它，不做第二次判断。
    waiting_on: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    assignee_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    assignee_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    owner_session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    capability_scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    workspace_root: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    graph_version: Mapped[int] = mapped_column(Integer, default=1)
    task_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AssistantTaskEdge(Base):
    """Assistant Task 图的有向边。"""

    __tablename__ = "assistant_task_edges"
    __table_args__ = (
        CheckConstraint(
            "edge_type IN ('dependency', 'delegation', 'question', 'meeting_channel', 'resource_request')",
            name="ck_assistant_task_edges_type",
        ),
        CheckConstraint(
            "propagation IN ('blocking', 'cancel_cascade', 'message_only', 'none')",
            name="ck_assistant_task_edges_propagation",
        ),
        Index("idx_assistant_task_edges_graph_source", "graph_id", "source_task_id"),
        Index("idx_assistant_task_edges_graph_target", "graph_id", "target_task_id"),
    )

    edge_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    target_task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(30), nullable=False)
    propagation: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AssistantTaskQuestion(Base):
    """持久化的 agent-to-agent question/resource/capability request route。"""

    __tablename__ = "assistant_task_questions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('clarification', 'resource_request', 'capability_request')",
            name="ck_assistant_task_questions_kind",
        ),
        CheckConstraint(
            "status IN ('open', 'escalated_to_parent', 'escalated_to_user', 'answered', 'cancelled', 'expired')",
            name="ck_assistant_task_questions_status",
        ),
        Index("idx_assistant_task_questions_task_status", "task_id", "status"),
        Index("idx_assistant_task_questions_graph_status", "graph_id", "status"),
        Index("idx_assistant_task_questions_status_expires", "status", "expires_at"),
    )

    question_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(50), nullable=False)
    task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_task_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    asker_type: Mapped[str] = mapped_column(String(40), nullable=False)
    asker_id: Mapped[str] = mapped_column(String(80), nullable=False)
    recipient_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    recipient_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    safe_answer_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capability_delta: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    escalated_to_user: Mapped[bool] = mapped_column(Boolean, default=False)
    user_request_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AssistantTaskAttempt(Base):
    """一次 Task 运行实例，保存 lease、heartbeat、checkpoint 和 fence token。"""

    __tablename__ = "assistant_task_attempts"
    __table_args__ = (
        CheckConstraint(
            "executor_type IN ('ephemeral_subagent', 'specialist')",
            name="ck_assistant_task_attempts_executor_type",
        ),
        CheckConstraint(
            "status IN ('starting', 'running', 'succeeded', 'paused', 'failed', 'cancelled', 'fenced')",
            name="ck_assistant_task_attempts_status",
        ),
        Index("idx_assistant_task_attempts_task_status", "task_id", "status"),
        Index("idx_assistant_task_attempts_status_lease", "status", "lease_expires_at"),
        # FR-003 容量=1：按 executor 查"是否已有 active attempt"的支撑索引。
        Index(
            "idx_assistant_task_attempts_executor_status",
            "executor_type",
            "executor_id",
            "status",
        ),
        # FR-003 容量=1 的 DB 层兜底：应用层 read-check-write 在并发下可能双双通过
        # active=None 守卫，partial unique index 是最后防线——同一 task、或同一
        # executor 不允许出现两个 active（starting/running）attempt。仅约束 active 状态；
        # I3：paused 不算 active（暂停即释放执行者槽，续跑开新 attempt），与终态行
        # （succeeded/failed/cancelled/fenced）一样不占名额。
        Index(
            "uq_assistant_task_attempts_active_task",
            "task_id",
            unique=True,
            sqlite_where=text("status IN ('starting', 'running')"),
        ),
        Index(
            "uq_assistant_task_attempts_active_executor",
            "executor_type",
            "executor_id",
            unique=True,
            sqlite_where=text("status IN ('starting', 'running')"),
        ),
    )

    attempt_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    executor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    executor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    # 这次开工实际跑在哪个会话里。派活时执行体还没被创建，``executor_id`` 对临时子代理
    # 只能填任务 id 顶替，于是"谁在干这活"在库里不存在——归属校验和任务下钻都无处可查。
    # 执行体在 agent loop 启动前回填本列，专员同样受益（executor_id 是专员身份，不是现场）。
    executor_session_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="starting")
    lease_owner: Mapped[str] = mapped_column(String(80), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fence_token: Mapped[int] = mapped_column(Integer, default=1)
    checkpoint_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AssistantTaskOperation(Base):
    """TaskAttempt 内部副作用步骤的幂等性记录。"""

    __tablename__ = "assistant_task_operations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed', 'failed', 'unsafe_to_retry')",
            name="ck_assistant_task_operations_status",
        ),
        Index("idx_assistant_task_operations_task_key", "task_id", "operation_key"),
        Index(
            "uq_assistant_task_operations_non_failed_key",
            "task_id",
            "operation_key",
            unique=True,
            sqlite_where=text("status != 'failed'"),
        ),
    )

    operation_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(50), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_scope: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    safe_summary: Mapped[str] = mapped_column(Text, nullable=False)
    result_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AssistantTaskAdjudication(Base):
    """父侧待裁定项。"""

    __tablename__ = "assistant_task_adjudications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'decided')", name="ck_assistant_task_adjudications_status"
        ),
        CheckConstraint(
            "delivered_status IN ('done', 'stuck', 'failed_input')",
            name="ck_assistant_task_adjudications_delivered_status",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('accepted', 'returned', 'abandoned')",
            name="ck_assistant_task_adjudications_decision",
        ),
        Index("idx_assistant_task_adjudications_task_status", "task_id", "status"),
        Index("idx_assistant_task_adjudications_parent_status", "parent_session_id", "status"),
        Index(
            "uq_assistant_task_adjudications_pending_task",
            "task_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
    )

    adjudication_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    graph_id: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    delivered_status: Mapped[str] = mapped_column(String(30), nullable=False)
    safe_summary: Mapped[str] = mapped_column(Text, nullable=False)
    raw_result_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AssistantTaskClaim(Base):
    """看板认领 lease 和拒绝历史。"""

    __tablename__ = "assistant_task_claims"
    __table_args__ = (
        CheckConstraint(
            "status IN ('claimed', 'released', 'rejected', 'completed', 'expired')",
            name="ck_assistant_task_claims_status",
        ),
        CheckConstraint(
            "claimer_type IN ('ephemeral_subagent', 'specialist')",
            name="ck_assistant_task_claims_claimer_type",
        ),
        Index("idx_assistant_task_claims_task_status", "task_id", "status"),
        Index("idx_assistant_task_claims_status_lease", "status", "lease_expires_at"),
        # FR-003 容量=1：按 claimer 查"是否已有进行中的认领"的支撑索引。
        Index(
            "idx_assistant_task_claims_claimer_status",
            "claimer_type",
            "claimer_id",
            "status",
        ),
        Index(
            "uq_assistant_task_claims_active_claimer",
            "claimer_type",
            "claimer_id",
            unique=True,
            sqlite_where=text("status = 'claimed'"),
        ),
    )

    claim_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    claimer_type: Mapped[str] = mapped_column(String(40), nullable=False)
    claimer_id: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="claimed")
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class AssistantMeetingChannel(Base):
    """受监督的两方消息通道。"""

    __tablename__ = "assistant_meeting_channels"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'concluded', 'closed_timeout', 'closed_abandoned')",
            name="ck_assistant_meeting_channels_status",
        ),
        Index("idx_assistant_meeting_channels_graph", "graph_id"),
        Index("idx_assistant_meeting_channels_parent", "parent_task_id"),
    )

    channel_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    supervisor_session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    participant_a_type: Mapped[str] = mapped_column(String(40), nullable=False)
    participant_a_id: Mapped[str] = mapped_column(String(80), nullable=False)
    participant_b_type: Mapped[str] = mapped_column(String(40), nullable=False)
    participant_b_id: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    turn_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    time_budget_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    turns_used: Mapped[int] = mapped_column(Integer, default=0)
    conclusion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AssistantMeetingMessage(Base):
    """Meeting channel 中的一条消息。"""

    __tablename__ = "assistant_meeting_messages"
    __table_args__ = (
        Index("idx_assistant_meeting_messages_channel_sequence", "channel_id", "sequence"),
    )

    message_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(50), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(40), nullable=False)
    sender_id: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AssistantTodoItem(Base):
    """执行者私有 Todo checklist 项。"""

    __tablename__ = "assistant_todo_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('todo', 'doing', 'done', 'skipped')", name="ck_assistant_todo_items_status"
        ),
        CheckConstraint(
            "executor_type IN ('ephemeral_subagent', 'specialist')",
            name="ck_assistant_todo_items_executor_type",
        ),
        Index("idx_assistant_todo_items_task_sort", "task_id", "sort_order"),
    )

    todo_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    executor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    executor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class UserTodo(Base):
    """用户个人待办事项。"""

    __tablename__ = "user_todos"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'done')",
            name="ck_user_todos_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_user_todos_priority",
        ),
        Index("idx_user_todos_status_created", "status", "created_at"),
        Index("idx_user_todos_priority_created", "priority", "created_at"),
    )

    todo_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ScheduledTask(Base):
    """定时任务主表（033 调度中心）——用户埋下的「到点让 AI 做某事」的派工单。

    软删（``is_deleted=1``）保留历史可追溯；``unattended_auto_approve`` 是 CC-005
    受控破例持久化的 per-task 免确认开关，只能经确认卡勾选或详情页开关写入。
    不建 FK：``source_ref``（todo 来源时为 todo_id）与外部表解耦，悬空由业务层惰性自愈；
    ``instruction`` 保存用户在确认卡核定后的实际执行指令，避免 todo 引用与指令文本混用。
    """

    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('direct', 'todo')",
            name="ck_scheduled_tasks_source_type",
        ),
        CheckConstraint(
            "schedule_kind IN ('one_shot', 'recurring')",
            name="ck_scheduled_tasks_schedule_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'expired')",
            name="ck_scheduled_tasks_status",
        ),
        CheckConstraint(
            "unattended_auto_approve IN (0, 1)",
            name="ck_scheduled_tasks_unattended_auto_approve",
        ),
        CheckConstraint(
            "is_deleted IN (0, 1)",
            name="ck_scheduled_tasks_is_deleted",
        ),
        Index(
            "idx_scheduled_tasks_fire",
            "next_fire_at",
            sqlite_where=text("status = 'active' AND is_deleted = 0"),
        ),
        Index(
            "idx_scheduled_tasks_source_todo",
            "source_ref",
            sqlite_where=text("source_type = 'todo' AND is_deleted = 0"),
        ),
        Index(
            "uq_scheduled_tasks_session",
            "session_id",
            unique=True,
            sqlite_where=text("session_id IS NOT NULL"),
        ),
    )

    scheduled_task_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    schedule_payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    unattended_auto_approve: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executor_hint: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    next_fire_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # v32（034）：该任务当前复用的常驻 scheduled assistant session。
    session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<ScheduledTask(scheduled_task_id={self.scheduled_task_id!r}, "
            f"status={self.status!r}, schedule_kind={self.schedule_kind!r})>"
        )


class ScheduledTaskRun(Base):
    """定时任务执行账目（033/034）——一次触发产生的一条 append-only 执行记录。

    关联的 scheduled 主助理会话复用既有 sessions 表（只加 ``source`` 列），会话细节
    不重复存储。终态 succeeded/failed/skipped 不可逆；waiting_user ⇄ running 可逆。
    """

    __tablename__ = "scheduled_task_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'waiting_user', 'skipped')",
            name="ck_scheduled_task_runs_status",
        ),
        Index("idx_runs_task_started", "scheduled_task_id", "started_at"),
        Index("idx_runs_session", "session_id"),
        Index(
            "uq_runs_active_per_task",
            "scheduled_task_id",
            unique=True,
            sqlite_where=text("status IN ('running', 'waiting_user')"),
        ),
        Index(
            "uq_runs_active_per_session",
            "session_id",
            unique=True,
            sqlite_where=text("status IN ('running', 'waiting_user')"),
        ),
        Index(
            "uq_runs_session_trigger",
            "session_id",
            "trigger_message_sequence",
            unique=True,
            sqlite_where=text("trigger_message_sequence IS NOT NULL"),
        ),
    )

    run_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    scheduled_task_id: Mapped[str] = mapped_column(String(50), nullable=False)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # v32（034）：消息水位线只用于本 run 的持久消息/图查询窗口。
    baseline_message_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    # 预约时确定的首条 scheduled user 消息序号；历史 v31 run 无法可靠回填，保持 NULL。
    trigger_message_sequence: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    # v31：终态 UI 通知投递账本。终态先提交、事件成功后再确认；NULL 会由 worker 重试。
    terminal_event_delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )
    # 每次进入可投递状态都递增；ack 必须绑定该代次，避免旧事件吞掉后续终态。
    terminal_event_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<ScheduledTaskRun(run_id={self.run_id!r}, status={self.status!r})>"


class TeachingFailureRecord(Base):
    """技能教学失败记录表"""

    __tablename__ = "teaching_failure_records"

    record_id: Mapped[str] = mapped_column(String(50), primary_key=True)  # UUID
    workflow_id: Mapped[str] = mapped_column(String(50), unique=True)  # = recording_id
    tool_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    failed_stage: Mapped[str] = mapped_column(String(20))  # "pm"|"programmer"|"trial"
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )  # active|retrying|resolved|dismissed
    retry_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<TeachingFailureRecord(record_id={self.record_id!r}, workflow_id={self.workflow_id!r}, status={self.status!r})>"


class ToolSuggestionHistory(Base):
    """工具化建议历史表（重复模式检测 + 拒绝冷却）"""

    __tablename__ = "tool_suggestion_history"

    suggestion_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    accepted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    times_seen: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<ToolSuggestionHistory(suggestion_id={self.suggestion_id!r}, task_pattern={self.task_pattern!r})>"


class AssistantSummary(Base):
    """助理跨会话记忆摘要表"""

    __tablename__ = "assistant_summaries"

    summary_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<AssistantSummary(summary_id={self.summary_id!r}, level={self.level!r})>"


class AppSettings(Base):
    """全局配置键值表（替代 DatabaseManager.get_setting/set_setting）"""

    __tablename__ = "app_settings"

    setting_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    setting_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    setting_type: Mapped[str] = mapped_column(String(20), default="string")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return (
            f"<AppSettings(setting_key={self.setting_key!r}, setting_type={self.setting_type!r})>"
        )


class SchemaVersion(Base):
    """Schema 版本追踪表"""

    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)

    def __repr__(self) -> str:
        return f"<SchemaVersion(version={self.version!r})>"


# ===== 大脑架构相关模型 =====


class BrainSegment(Base):
    """大脑 Segment 表 - 一段连续对话的单位"""

    __tablename__ = "brain_segments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'distilling', 'completed', 'failed')",
            name="ck_brain_segments_status",
        ),
    )

    segment_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    all_empty_retried: Mapped[bool] = mapped_column(Boolean, default=False)
    boundary_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    message_id_start: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    message_id_end: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sealed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    distilling_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<BrainSegment(segment_id={self.segment_id!r}, status={self.status!r})>"


class BrainMemoryEntry(Base):
    """大脑记忆条目表 - 所有 6 个分区统一存储"""

    __tablename__ = "brain_memory_entries"
    __table_args__ = (
        CheckConstraint(
            "zone IN ('hot', 'persistent', 'archive', 'subconscious', 'failure', 'prediction', 'reflection')",
            name="ck_brain_memory_entries_zone",
        ),
        CheckConstraint(
            "status IN ('active', 'fading', 'invalidated', 'soft-deleted')",
            name="ck_brain_memory_entries_status",
        ),
    )

    entry_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    zone: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    origin: Mapped[str] = mapped_column(String(30), nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_segment_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    superseded_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    loaded_count: Mapped[int] = mapped_column(Integer, default=0)
    referenced_count: Mapped[int] = mapped_column(Integer, default=0)
    relevance_score: Mapped[float] = mapped_column(default=1.0)
    verification_checkpoint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    verification_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<BrainMemoryEntry(entry_id={self.entry_id!r}, zone={self.zone!r}, status={self.status!r})>"


class BrainSpecialist(Base):
    """大脑固定专员表"""

    __tablename__ = "brain_specialists"

    __table_args__ = (
        CheckConstraint(
            "role_kind IN ('executor', 'planner')",
            name="ck_brain_specialists_role_kind",
        ),
    )

    specialist_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    role_definition: Mapped[str] = mapped_column(Text, nullable=False)
    tool_whitelist: Mapped[str] = mapped_column(Text, nullable=False)
    composition_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    origin: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="executor")
    # v35 内置专员种子：preset_key 是稳定标识（用户改名后仍认得出），
    # preset_fingerprint 记录种子当时写入的内容摘要——与当前内容不符即表示
    # 用户改过，此后不再自动更新。两者均为 NULL 表示这是用户自建专员。
    preset_key: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    preset_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<BrainSpecialist(specialist_id={self.specialist_id!r}, name={self.name!r})>"


class BrainSpecialistVersion(Base):
    """专员版本历史表"""

    __tablename__ = "brain_specialist_versions"

    __table_args__ = (
        UniqueConstraint("specialist_id", "version", name="uq_brain_specialist_version"),
    )

    version_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    specialist_id: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    role_definition: Mapped[str] = mapped_column(Text, nullable=False)
    tool_whitelist: Mapped[str] = mapped_column(Text, nullable=False)
    composition_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    changed_by: Mapped[str] = mapped_column(String(20), nullable=False)
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<BrainSpecialistVersion(version_id={self.version_id!r}, version={self.version!r})>"


class BrainRecruitmentSignal(Base):
    """专员自动招募检测信号表"""

    __tablename__ = "brain_recruitment_signals"

    signal_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    delegation_count: Mapped[int] = mapped_column(Integer, default=0)
    example_session_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    example_delegation_summaries: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    specialist_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<BrainRecruitmentSignal(signal_id={self.signal_id!r}, task_pattern={self.task_pattern!r})>"


class BrainSkill(Base):
    """方法论资产表。"""

    __tablename__ = "brain_skills"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'soft_deleted')",
            name="ck_brain_skills_status",
        ),
        CheckConstraint(
            "origin IN ('system_bootstrap', 'user_edit', 'assistant_tool_call', "
            "'specialist_tool_call', 'external_import')",
            name="ck_brain_skills_origin",
        ),
        CheckConstraint(
            "(status = 'superseded') = (superseded_by IS NOT NULL)",
            name="ck_brain_skills_superseded_by_status",
        ),
    )

    skill_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_conditions: Mapped[str] = mapped_column(Text, nullable=False)
    required_tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    origin: Mapped[str] = mapped_column(String(30), nullable=False)
    parent_skill_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    superseded_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chain_root_id: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    last_changed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    loaded_count: Mapped[int] = mapped_column(Integer, default=0)
    referenced_count: Mapped[int] = mapped_column(Integer, default=0)
    last_referenced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<BrainSkill(skill_id={self.skill_id!r}, name={self.name!r}, status={self.status!r})>"
        )


class BrainSkillSourceSegment(Base):
    """方法论素材来源关联表。"""

    __tablename__ = "brain_skill_source_segments"
    __table_args__ = (
        CheckConstraint(
            "source_zone IN ('archive', 'failure')",
            name="ck_brain_skill_source_segments_zone",
        ),
        UniqueConstraint("skill_id", "segment_id", name="uq_brain_skill_source_segment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(String(50), nullable=False)
    segment_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_zone: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return (
            f"<BrainSkillSourceSegment(skill_id={self.skill_id!r}, "
            f"segment_id={self.segment_id!r})>"
        )


class ToolOutputReference(Base):
    """Persistent metadata for recoverable raw built-in tool output."""

    __tablename__ = "tool_output_references"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'expired', 'deleted')",
            name="ck_tool_output_references_status",
        ),
        Index("idx_tool_output_reference_id", "reference_id"),
        Index("idx_tool_output_session", "session_id"),
        Index("idx_tool_output_tool_call", "tool_call_id"),
        Index("idx_tool_output_status", "status"),
        Index("idx_tool_output_expires", "expires_at"),
    )

    reference_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    storage_root_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="app_data_tool_outputs"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/plain")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    redaction_profile: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    owner_workspace_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ToolOutputReference(reference_id={self.reference_id!r}, " f"status={self.status!r})>"
        )


class AssistantRunFailure(Base):
    """Persistent recovery state for a terminal Assistant turn failure."""

    __tablename__ = "assistant_run_failures"
    __table_args__ = (
        CheckConstraint(
            # 与 assistant_failure_classifier.KNOWN_FAILURE_CATEGORIES 同步，
            # 由 tests/data/test_assistant_run_failure_repository.py 的守卫测试钉住。
            # 漏了会让「记录失败」这件事本身失败——出了事连出过事都记不下来。
            "category IN ('authentication', 'invalid_request', 'quota', 'network', "
            "'provider', 'iteration_limit', 'internal', 'code_defect')",
            name="ck_assistant_run_failures_category",
        ),
        CheckConstraint(
            "status IN ('failed', 'retrying', 'resolved')",
            name="ck_assistant_run_failures_status",
        ),
        CheckConstraint("attempt_count >= 1", name="ck_assistant_run_failures_attempt_count"),
        Index(
            "uq_assistant_run_failure_current_session",
            "session_id",
            unique=True,
            sqlite_where=text("status IN ('failed', 'retrying')"),
        ),
        Index(
            "idx_assistant_run_failure_message",
            "session_id",
            "message_sequence",
        ),
        Index("idx_assistant_run_failure_status", "status"),
    )

    failure_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    message_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    safe_message: Mapped[str] = mapped_column(Text, nullable=False)
    safe_suggestion: Mapped[str] = mapped_column(Text, nullable=False)
    internal_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    exception_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="failed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    failed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AssistantRunFailure(failure_id={self.failure_id!r}, "
            f"session_id={self.session_id!r}, status={self.status!r})>"
        )


class BrainSkillEquipment(Base):
    """装备者与方法论之间的状态化关系。"""

    __tablename__ = "brain_skill_equipment"
    __table_args__ = (
        CheckConstraint(
            "equipped_entity_type IN ('assistant', 'specialist')",
            name="ck_brain_skill_equipment_entity_type",
        ),
        CheckConstraint(
            "status IN ('active', 'unequipped')",
            name="ck_brain_skill_equipment_status",
        ),
        CheckConstraint(
            "unequipped_reason IS NULL OR unequipped_reason IN "
            "('user_unequip', 'force_remove_on_soft_delete', 'supersede_transfer')",
            name="ck_brain_skill_equipment_reason",
        ),
        CheckConstraint(
            "(status = 'active' AND unequipped_at IS NULL AND unequipped_reason IS NULL) OR "
            "(status = 'unequipped' AND unequipped_at IS NOT NULL AND unequipped_reason IS NOT NULL)",
            name="ck_brain_skill_equipment_status_fields",
        ),
        Index(
            "uq_brain_skill_equipment_active",
            "equipped_entity_type",
            "equipped_entity_id",
            "skill_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipped_entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    equipped_entity_id: Mapped[str] = mapped_column(String(50), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    equipped_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    equipped_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    unequipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    unequipped_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return (
            f"<BrainSkillEquipment(entity={self.equipped_entity_type}:"
            f"{self.equipped_entity_id}, skill_id={self.skill_id!r}, status={self.status!r})>"
        )


event.listen(
    BrainSkill.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER IF NOT EXISTS trg_brain_skills_no_delete
        BEFORE DELETE ON brain_skills
        BEGIN
            SELECT RAISE(ABORT, 'brain_skills_no_physical_delete');
        END
        """
    ),
)

event.listen(
    BrainSkillEquipment.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER IF NOT EXISTS trg_brain_skill_equipment_no_delete
        BEFORE DELETE ON brain_skill_equipment
        BEGIN
            SELECT RAISE(ABORT, 'brain_skill_equipment_no_physical_delete');
        END
        """
    ),
)


class FeedbackSignal(Base):
    """用户管理界面的编辑/删除反馈信号表"""

    __tablename__ = "feedback_signals"

    signal_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    zone: Mapped[str] = mapped_column(String(20), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(50), nullable=False)
    context_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ===== 自我改进相关模型 =====


class PromptSupplement(Base):
    """prompt section 级补丁，用于自优化。"""

    __tablename__ = "prompt_supplements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'active', 'superseded', 'retracted')",
            name="ck_prompt_supplements_status",
        ),
    )

    supplement_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    target_section: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metric_evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    version: Mapped[int] = mapped_column(Integer, default=1)
    prompt_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PromptSupplement(supplement_id={self.supplement_id!r}, "
            f"target_section={self.target_section!r}, status={self.status!r})>"
        )


class ToolGapReport(Base):
    """检测到的工具能力缺口。"""

    __tablename__ = "tool_gap_reports"
    __table_args__ = (
        CheckConstraint(
            "gap_type IN ('missing_tool', 'repeated_pattern', 'high_iteration', 'bug_pattern')",
            name="ck_tool_gap_reports_gap_type",
        ),
        CheckConstraint(
            "status IN ('detected', 'trial_pending', 'resolved', 'trial_failed')",
            name="ck_tool_gap_reports_status",
        ),
    )

    report_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    gap_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pattern_signature: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    confidence: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="detected")
    evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<ToolGapReport(report_id={self.report_id!r}, "
            f"gap_type={self.gap_type!r}, status={self.status!r})>"
        )


class ToolFixProposal(Base):
    """工具 bug 修复提案。"""

    __tablename__ = "tool_fix_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'trial_pending', 'applied', 'rejected')",
            name="ck_tool_fix_proposals_status",
        ),
    )

    proposal_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(50), nullable=False)
    gap_report_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    proposed_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    before_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trial_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ToolFixProposal(proposal_id={self.proposal_id!r}, "
            f"tool_id={self.tool_id!r}, status={self.status!r})>"
        )


class SelfImprovementMetric(Base):
    """时序性能指标。"""

    __tablename__ = "self_improvement_metrics"

    metric_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    metric_value: Mapped[float] = mapped_column(nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=1)
    measured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    metadata_: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<SelfImprovementMetric(metric_id={self.metric_id!r}, "
            f"metric_type={self.metric_type!r})>"
        )


class SelfImprovementAuditLogEntry(Base):
    """自我改进追加审计日志。"""

    __tablename__ = "self_improvement_audit_log"

    audit_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    before_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metric_evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())

    def __repr__(self) -> str:
        return (
            f"<SelfImprovementAuditLogEntry(audit_id={self.audit_id!r}, "
            f"action_type={self.action_type!r})>"
        )


class ExecutionReview(Base):
    """执行复盘报告与后台处理队列。"""

    __tablename__ = "execution_reviews"
    __table_args__ = (Index("ix_execution_reviews_status_priority", "status", "priority"),)

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    turn_session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verdict: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    findings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    advisory: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model_used: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    reviewed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return f"<ExecutionReview(id={self.id!r}, status={self.status!r})>"


class ImprovementProposal(Base):
    """改进提案——从执行复盘 worth_changing finding 生成的可审批改进项。"""

    __tablename__ = "improvement_proposals"
    __table_args__ = (
        UniqueConstraint("source_review_id", "finding_index", name="uq_proposal_review_finding"),
        CheckConstraint(
            "status IN ('pending_review', 'approved', 'in_progress', 'done', 'failed', 'rejected')",
            name="ck_improvement_proposals_status",
        ),
        CheckConstraint(
            "result_tests_passed IN (0, 1) OR result_tests_passed IS NULL",
            name="ck_improvement_proposals_result_tests_passed",
        ),
        Index("ix_improvement_proposals_status", "status"),
        Index("ix_improvement_proposals_dedup_key", "dedup_key"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    source_review_id: Mapped[str] = mapped_column(String(50), nullable=False)
    finding_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_review")
    severity: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    finding_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dedup_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    what: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_supplement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    graph_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    worktree_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    branch_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    result_tests_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # v25：绑定的讨论会话 id（sessions.session_id）。一个提案至多一个；
    # 不建 FK——会话可被用户删除，绑定死亡由业务层惰性自愈重建。
    discussion_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    decided_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return f"<ImprovementProposal(id={self.id!r}, status={self.status!r})>"


class ExternalSkillInstall(Base):
    """外部技能安装记录表（v26，029）——brain_skills 的来源元数据伴生表。

    不建 FK：brain_skills 生命周期（supersede/软删）独立演进，绑定由业务层维护。
    "活跃安装" = uninstalled_at IS NULL；卸载置时间戳软记录，文件目录物理清理。
    """

    __tablename__ = "external_skill_installs"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('skills_sh', 'github')",
            name="ck_external_skill_installs_source_type",
        ),
        UniqueConstraint("skill_id", name="uq_external_skill_installs_skill_id"),
        Index("ix_external_skill_installs_source", "source_type", "source_ref"),
    )

    install_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    local_dir: Mapped[str] = mapped_column(String(500), nullable=False)
    installed_at: Mapped[str] = mapped_column(String(50), nullable=False)
    uninstalled_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ExternalSkillInstall(install_id={self.install_id!r}, "
            f"source={self.source_type!r}:{self.source_ref!r})>"
        )


class ExternalCodingSession(Base):
    """外部 coding session 主记录（v27，030）。"""

    __tablename__ = "external_coding_sessions"
    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('task', 'workflow')",
            name="ck_external_coding_sessions_owner_type",
        ),
        CheckConstraint(
            "tool IN ('claude_code', 'codex_cli')",
            name="ck_external_coding_sessions_tool",
        ),
        CheckConstraint(
            "launch_mode IN ('headless', 'interactive')",
            name="ck_external_coding_sessions_launch_mode",
        ),
        CheckConstraint(
            "status IN ("
            "'created','planning','plan_ready','plan_approved','plan_rejected',"
            "'implementing','interrupted','waiting_user','completed','merge_ready',"
            "'merged','merge_blocked','rollback_proposed','rolled_back','abandoned','failed'"
            ")",
            name="ck_external_coding_sessions_status",
        ),
        CheckConstraint(
            "phase IN ('plan','implement','merge','rollback','done')",
            name="ck_external_coding_sessions_phase",
        ),
        Index("ix_external_coding_sessions_owner", "owner_type", "owner_id", "updated_at"),
        Index("ix_external_coding_sessions_session", "session_id", "updated_at"),
        Index("ix_external_coding_sessions_status", "status", "updated_at"),
    )

    coding_session_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool: Mapped[str] = mapped_column(String(20), nullable=False)
    launch_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    selected_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quota_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    external_session_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    worktree_path: Mapped[str] = mapped_column(String(500), nullable=False)
    branch_name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_commit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_branch: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    target_worktree_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    artifact_dir: Mapped[str] = mapped_column(String(500), nullable=False)
    handoff_path: Mapped[str] = mapped_column(String(500), nullable=False)
    plan_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    result_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    plan_approved_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    plan_approved_by: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_error_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_skipped_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)
    completed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class ExternalCodingAttempt(Base):
    """外部 coding session 的一次 CLI 调用或续跑。"""

    __tablename__ = "external_coding_attempts"
    __table_args__ = (
        CheckConstraint("phase IN ('plan', 'implement')", name="ck_external_coding_attempts_phase"),
        CheckConstraint(
            "launch_mode IN ('headless', 'interactive')",
            name="ck_external_coding_attempts_launch_mode",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'interrupted', 'failed')",
            name="ck_external_coding_attempts_status",
        ),
        CheckConstraint(
            "((status = 'running' AND termination_unconfirmed = 1) OR "
            "(status != 'running' AND termination_unconfirmed = 0))",
            name="ck_external_coding_attempts_ownership_status",
        ),
        CheckConstraint(
            "(launch_started = 1 OR (pid IS NULL AND process_create_time IS NULL))",
            name="ck_external_coding_attempts_unlaunched_identity",
        ),
        CheckConstraint(
            "(process_create_time IS NULL OR pid IS NOT NULL)",
            name="ck_external_coding_attempts_process_identity",
        ),
        Index("ix_external_coding_attempts_session", "coding_session_id", "started_at"),
        Index(
            "uq_external_coding_attempts_active_session",
            "coding_session_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    attempt_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    coding_session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    launch_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    command_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_session_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # v33（035）：跨 sidecar 重启验证 PID 身份并保持 fail-closed ownership。
    process_create_time: Mapped[Optional[float]] = mapped_column(nullable=True)
    termination_unconfirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # False identifies a reservation that durably never crossed the spawn boundary.
    launch_started: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[str] = mapped_column(String(50), nullable=False)
    finished_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    log_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    log_tail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ExternalCodingQuotaObservation(Base):
    """外部 coding 工具 quota 的脱敏归一化观测。"""

    __tablename__ = "external_coding_quota_observations"
    __table_args__ = (
        CheckConstraint(
            "tool IN ('claude_code', 'codex_cli')",
            name="ck_external_coding_quota_tool",
        ),
        CheckConstraint(
            "state IN ('available', 'low', 'exhausted', 'unknown')",
            name="ck_external_coding_quota_state",
        ),
        Index("ix_external_coding_quota_tool_checked", "tool", "checked_at"),
    )

    observation_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tool: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    reset_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    checked_at: Mapped[str] = mapped_column(String(50), nullable=False)
    safe_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ExternalCodingMergeRecord(Base):
    """外部 coding session 自动合并审计记录。"""

    __tablename__ = "external_coding_merge_records"
    __table_args__ = (
        CheckConstraint(
            "conflict_risk IN ('low', 'overlap', 'conflict_predicted', 'unknown')",
            name="ck_external_coding_merge_conflict_risk",
        ),
        CheckConstraint(
            "status IN ('analysis_ready', 'merged', 'blocked', 'failed', 'rolled_back')",
            name="ck_external_coding_merge_status",
        ),
        Index("ix_external_coding_merge_session", "coding_session_id", "created_at"),
    )

    merge_record_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    coding_session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    target_worktree_path: Mapped[str] = mapped_column(String(500), nullable=False)
    pre_merge_head: Mapped[str] = mapped_column(String(100), nullable=False)
    coding_branch_head: Mapped[str] = mapped_column(String(100), nullable=False)
    dirty_files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    changed_files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    overlap_files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    conflict_risk: Mapped[str] = mapped_column(String(30), nullable=False)
    agent_decision: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    merge_commit: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    merged_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class ExternalCodingRollbackDecision(Base):
    """外部 coding session 回滚裁定记录。"""

    __tablename__ = "external_coding_rollback_decisions"
    __table_args__ = (
        CheckConstraint(
            "chosen_strategy IN ('revert_commit', 'reverse_patch', 'reset_hard', 'manual')",
            name="ck_external_coding_rollback_strategy",
        ),
        CheckConstraint(
            "status IN ('proposed', 'applied', 'blocked', 'failed')",
            name="ck_external_coding_rollback_status",
        ),
        Index("ix_external_coding_rollback_session", "coding_session_id", "created_at"),
    )

    rollback_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    coding_session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    merge_record_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    intent_summary: Mapped[str] = mapped_column(Text, nullable=False)
    chosen_strategy: Mapped[str] = mapped_column(String(30), nullable=False)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    applied_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class McpServer(Base):
    """MCP server 配置表（v24 migration）"""

    __tablename__ = "mcp_servers"
    __table_args__ = (
        CheckConstraint(
            "transport IN ('stdio', 'http')",
            name="ck_mcp_servers_transport",
        ),
        Index("uq_mcp_servers_name", "name", unique=True),
    )

    server_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    transport: Mapped[str] = mapped_column(String(20), nullable=False)
    command: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    args_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    headers_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    secret_header_keys_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    env_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    secret_env_keys_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_known_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    circuit_breaker_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tool_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tools_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preset_slug: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<McpServer(server_id={self.server_id!r}, name={self.name!r})>"
