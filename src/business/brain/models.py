"""
大脑架构共享常量和数据类
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Zone(str, Enum):
    HOT = "hot"
    PERSISTENT = "persistent"
    ARCHIVE = "archive"
    SUBCONSCIOUS = "subconscious"
    FAILURE = "failure"
    PREDICTION = "prediction"


class SegmentStatus(str, Enum):
    PENDING = "pending"
    DISTILLING = "distilling"
    COMPLETED = "completed"
    FAILED = "failed"


class EntryStatus(str, Enum):
    ACTIVE = "active"
    FADING = "fading"
    INVALIDATED = "invalidated"
    SOFT_DELETED = "soft-deleted"


class EntryType(str, Enum):
    EVENT = "event"
    INSIGHT = "insight"


class EntryOrigin(str, Enum):
    DISTILLATION = "distillation"
    USER_EDIT = "user_edit"
    SYSTEM_MIGRATION = "system_migration"
    MANUAL = "manual"


class BoundaryReason(str, Enum):
    WINDOW_CLOSE = "window_close"
    IDLE = "idle"
    NEW_SESSION = "new_session"
    TOKEN_LIMIT = "token_limit"


class SpecialistOrigin(str, Enum):
    AUTO_RECRUITMENT = "auto_recruitment"
    USER_CONVERSATION = "user_conversation"
    USER_MANAGEMENT_UI = "user_management_ui"


ZONE_LABELS = {
    Zone.HOT: "热区",
    Zone.PERSISTENT: "持久区",
    Zone.ARCHIVE: "归档区",
    Zone.SUBCONSCIOUS: "潜意识区",
    Zone.FAILURE: "失败区",
    Zone.PREDICTION: "猜测区",
}

VALID_TRANSITIONS: dict[SegmentStatus, set[SegmentStatus]] = {
    SegmentStatus.PENDING: {SegmentStatus.DISTILLING},
    SegmentStatus.DISTILLING: {
        SegmentStatus.COMPLETED,
        SegmentStatus.FAILED,
        SegmentStatus.PENDING,
    },
    SegmentStatus.FAILED: {SegmentStatus.PENDING},
    SegmentStatus.COMPLETED: set(),
}


@dataclass(frozen=True)
class ZoneSummary:
    zone: str
    label: str
    entry_count: int
    fading_count: int = 0


@dataclass(frozen=True)
class SegmentBoundaryPayload:
    session_id: str
    segment_id: str
    reason: str


@dataclass(frozen=True)
class MemoryEntryData:
    entry_id: str
    zone: str
    content: str
    status: str
    origin: str
    reason: str
    entry_type: Optional[str] = None
    scope: Optional[str] = None
    source_segment_id: Optional[str] = None
    source_session_id: Optional[str] = None
    superseded_by: Optional[str] = None
    loaded_count: int = 0
    referenced_count: int = 0
    relevance_score: float = 1.0
    verification_checkpoint: Optional[str] = None
    verification_status: Optional[str] = None
    verification_rationale: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class DistillationZoneOutput:
    """单个分区的沉淀输出"""

    content: str
    reason: str
    entry_type: Optional[str] = None
    scope: Optional[str] = None


@dataclass(frozen=True)
class DistillationOutput:
    """一次沉淀 LLM 调用的完整输出"""

    hot_zone: list[DistillationZoneOutput] = field(default_factory=list)
    persistent_zone: list[DistillationZoneOutput] = field(default_factory=list)
    archive_zone: list[DistillationZoneOutput] = field(default_factory=list)
    subconscious_zone: list[DistillationZoneOutput] = field(default_factory=list)
    failure_zone: list[DistillationZoneOutput] = field(default_factory=list)
