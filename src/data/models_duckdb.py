"""
SQLAlchemy ORM 模型 - DuckDB 数据库 (mexemplar.duckdb)

包含：recording_sessions, actions, network_requests, sibling_snapshots,
     filter_decisions

注意：DuckDB 使用 Sequence 而不是 SERIAL 来实现自增主键
参考：https://github.com/Mause/duckdb_engine#auto-incrementing-id-columns
"""

from datetime import datetime
from typing import Optional, Any
import sqlalchemy
from sqlalchemy import String, Integer, Text, DateTime, Boolean, JSON, Float, LargeBinary, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


# ⭐ 定义序列对象（DuckDB 需要）
action_id_seq = sqlalchemy.Sequence('action_id_seq')
request_id_seq = sqlalchemy.Sequence('request_id_seq')
snapshot_id_seq = sqlalchemy.Sequence('snapshot_id_seq')
decision_id_seq = sqlalchemy.Sequence('decision_id_seq')


class RecordingSession(Base):
    """录制会话表"""
    __tablename__ = "recording_sessions"

    recording_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))  # recording, stopped
    recording_mode: Mapped[str] = mapped_column(String(20))  # browser, desktop
    browser_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    session_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # 关系
    actions: Mapped[list["Action"]] = lambda: relationship(
        "Action", back_populates="recording_session"
    )

    def __repr__(self) -> str:
        return f"<RecordingSession(recording_id={self.recording_id!r}, status={self.status!r})>"


class Action(Base):
    """操作记录表"""
    __tablename__ = "actions"

    action_id: Mapped[int] = mapped_column(
        Integer,
        action_id_seq,
        server_default=action_id_seq.next_value(),
        primary_key=True
    )
    recording_id: Mapped[str] = mapped_column(String(50), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(50))
    recording_mode: Mapped[str] = mapped_column(String(20))
    app_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    process_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    window_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dom_element: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    dom_tree_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    visual_features: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    screenshot_before: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    screenshot_after: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)

    # 关系
    recording_session: Mapped["RecordingSession"] = lambda: relationship(
        "RecordingSession", back_populates="actions"
    )
    network_requests: Mapped[list["NetworkRequest"]] = lambda: relationship(
        "NetworkRequest", back_populates="action"
    )

    def __repr__(self) -> str:
        return f"<Action(action_id={self.action_id!r}, type={self.action_type!r})>"


class NetworkRequest(Base):
    """网络请求表"""
    __tablename__ = "network_requests"

    request_id: Mapped[int] = mapped_column(
        Integer,
        request_id_seq,
        server_default=request_id_seq.next_value(),
        primary_key=True
    )
    action_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    recording_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(10))
    request_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    request_headers: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    request_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    filtered: Mapped[bool] = mapped_column(Boolean, default=False)
    filter_reason: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    filtered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_recommendation: Mapped[bool] = mapped_column(Boolean, default=False)
    importance_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # 关系
    action: Mapped[Optional["Action"]] = lambda: relationship(
        "Action", back_populates="network_requests"
    )

    def __repr__(self) -> str:
        return f"<NetworkRequest(request_id={self.request_id!r}, url={self.url[:50]!r}...)"


class SiblingSnapshot(Base):
    """兄弟元素快照表"""
    __tablename__ = "sibling_snapshots"

    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        snapshot_id_seq,
        server_default=snapshot_id_seq.next_value(),
        primary_key=True
    )
    action_id: Mapped[int] = mapped_column(Integer, index=True)
    recording_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    container_selector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    item_selector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    list_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    siblings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    structure_similarity: Mapped[float] = mapped_column(Float, default=0.0)
    is_homogeneous: Mapped[bool] = mapped_column(Boolean, default=False)
    clicked_index: Mapped[int] = mapped_column(Integer, default=-1)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return f"<SiblingSnapshot(snapshot_id={self.snapshot_id!r}, action_id={self.action_id!r})>"


class FilterDecision(Base):
    """过滤决策表"""
    __tablename__ = "filter_decisions"

    decision_id: Mapped[int] = mapped_column(
        Integer,
        decision_id_seq,
        server_default=decision_id_seq.next_value(),
        primary_key=True
    )
    request_id: Mapped[str] = mapped_column(String(50))
    action_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    recording_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    decision: Mapped[str] = mapped_column(String(20))  # keep, filter
    source: Mapped[str] = mapped_column(String(20))  # rule, llm
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    pattern_matched: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    request_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    action_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<FilterDecision(decision_id={self.decision_id!r}, decision={self.decision!r})>"
