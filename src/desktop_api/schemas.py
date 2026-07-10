from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

BackendStatus = Literal["starting", "ready", "degraded", "failed", "shutting_down"]
SessionStatus = Literal["active", "suspended", "completed", "failed", "archived"]
UiTheme = Literal["light", "dark", "system", "sage"]
UiDensity = Literal["compact", "comfy"]
AssistantExecutorType = Literal["ephemeral_subagent", "specialist"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthCheck(BaseModel):
    name: str
    status: Literal["ok", "degraded", "failed"]
    message: str = ""


class BackendConnectionState(BaseModel):
    status: BackendStatus
    message: str = ""
    checks: list[HealthCheck] = Field(default_factory=list)
    serverTime: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BootstrapUser(BaseModel):
    displayName: str = ""
    statusLabel: str = "Local ready"


class BootstrapNavigation(BaseModel):
    pendingSkillCount: int = 0
    publishedSkillCount: int = 0
    failureCount: int = 0
    compositionCount: int = 0


class BootstrapSettingsSummary(BaseModel):
    theme: UiTheme = "sage"
    dark: bool = False
    density: UiDensity = "comfy"


class BootstrapBrainConfig(BaseModel):
    segmentIdleThresholdSeconds: int = 300


class BootstrapResponse(BaseModel):
    connection: BackendConnectionState
    user: BootstrapUser = Field(default_factory=BootstrapUser)
    navigation: BootstrapNavigation = Field(default_factory=BootstrapNavigation)
    settingsSummary: BootstrapSettingsSummary = Field(default_factory=BootstrapSettingsSummary)
    brain: BootstrapBrainConfig = Field(default_factory=BootstrapBrainConfig)


class UiEvent(BaseModel):
    eventId: str
    sequence: int
    sessionId: str
    causationId: str | None = None
    type: str
    scope: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AssistantSessionSummary(BaseModel):
    sessionId: str
    title: str
    preview: str = ""
    status: SessionStatus = "active"
    createdAt: datetime | None = None
    updatedAt: datetime | None = None
    dateLabel: str = ""


class AssistantSessionListResponse(BaseModel):
    items: list[AssistantSessionSummary] = Field(default_factory=list)
    hasMore: bool = False


class AssistantCreateSessionRequest(BaseModel):
    toolIds: list[str] | None = None
    title: str | None = None


class AssistantCreateSessionResponse(BaseModel):
    sessionId: str


class AssistantRenameSessionRequest(BaseModel):
    title: str


class AssistantMessageFailure(BaseModel):
    category: Literal[
        "authentication",
        "invalid_request",
        "quota",
        "network",
        "provider",
        "iteration_limit",
        "internal",
    ]
    message: str
    suggestion: str
    attemptCount: int = Field(ge=1)
    failedAt: datetime


class AssistantMessage(BaseModel):
    sequence: int
    role: Literal["user", "assistant", "summary"]
    content: str
    createdAt: datetime | None = None
    rendering: Literal["plain_text", "safe_markdown"]
    failure: AssistantMessageFailure | None = None


class AssistantMessagesResponse(BaseModel):
    items: list[AssistantMessage] = Field(default_factory=list)
    hasMoreBefore: bool = False
    nextBeforeSequence: int | None = None


class AssistantContinueSubagentDirective(BaseModel):
    subagentId: str
    supplemental: str | None = None


class AssistantSendMessageRequest(BaseModel):
    content: str
    continueSubagent: AssistantContinueSubagentDirective | None = None


class AssistantSendMessageResponse(BaseModel):
    accepted: bool
    sessionId: str


class AssistantRetryRequest(BaseModel):
    messageSequence: int = Field(ge=1)
    content: str | None = None


class AssistantRetryResponse(BaseModel):
    accepted: bool
    sessionId: str
    messageSequence: int


class AssistantStopRequest(BaseModel):
    runId: str | None = None


class AssistantStopResponse(BaseModel):
    accepted: bool


TaskStatus = Literal[
    "pending_dispatch",
    "running",
    "suspended",
    "completed",
    "failed",
    "cancelled",
]
TaskDisplayPhase = Literal["running", "reviewing", "needs_attention", "paused", "done"]
TaskSuspendReason = Literal["waiting_user", "waiting_system", "user_stop"]


# I8: 运行时同步断言——business StrEnum 与 schema Literal 必须保持一致。
# 新增/删除状态值时，如果只改了一边，import 时会立刻报错。
def _assert_enum_literal_sync() -> None:
    from src.business.task_collaboration.models import (
        TaskStatus as _TaskStatusEnum,
        SuspendReason as _SuspendReasonEnum,
    )

    _status_values = {s.value for s in _TaskStatusEnum}
    _literal_values = set(TaskStatus.__args__)  # type: ignore[attr-defined]
    assert _status_values == _literal_values, (
        f"TaskStatus enum/label mismatch: enum={_status_values - _literal_values} "
        f"literal={_literal_values - _status_values}"
    )
    _suspend_values = {s.value for s in _SuspendReasonEnum}
    _suspend_literal_values = set(TaskSuspendReason.__args__)  # type: ignore[attr-defined]
    assert _suspend_values == _suspend_literal_values, (
        f"SuspendReason enum/label mismatch: enum={_suspend_values - _suspend_literal_values} "
        f"literal={_suspend_literal_values - _suspend_values}"
    )

    # External coding enum/literal sync
    from src.business.external_coding.models import (
        CodingSessionStatus as _CSStatus,
        CodingPhase as _CSPhase,
        ExternalCodingTool as _CSTool,
        OwnerType as _CSOwnerType,
        LaunchMode as _CSLaunchMode,
        AttemptStatus as _CSAttemptStatus,
        ConflictRisk as _CSConflictRisk,
        MergeRecordStatus as _CSMergeStatus,
        RollbackStrategy as _CSRollbackStrategy,
        RollbackDecisionStatus as _CSRollbackDecisionStatus,
        ErrorCategory as _CSErrorCategory,
        QuotaState as _CSQuotaState,
    )

    _sync_pairs: list[tuple[type, type, str]] = [
        (_CSStatus, ExternalCodingStatus, "CodingSessionStatus"),
        (_CSPhase, ExternalCodingPhase, "CodingPhase"),
        (_CSTool, ExternalCodingTool, "ExternalCodingTool"),
        (_CSOwnerType, ExternalCodingOwnerType, "OwnerType"),
        (_CSLaunchMode, ExternalCodingLaunchMode, "LaunchMode"),
        (_CSAttemptStatus, ExternalCodingAttemptStatus, "AttemptStatus"),
        (_CSConflictRisk, ExternalCodingConflictRisk, "ConflictRisk"),
        (_CSMergeStatus, ExternalCodingMergeRecordStatus, "MergeRecordStatus"),
        (_CSRollbackStrategy, ExternalCodingRollbackStrategy, "RollbackStrategy"),
        (_CSRollbackDecisionStatus, ExternalCodingRollbackDecisionStatus, "RollbackDecisionStatus"),
        (_CSErrorCategory, ExternalCodingErrorCategory, "ErrorCategory"),
        (_CSQuotaState, ExternalCodingQuotaState, "QuotaState"),
    ]
    for enum_cls, literal_cls, name in _sync_pairs:
        enum_values = {e.value for e in enum_cls}
        literal_values = set(literal_cls.__args__)  # type: ignore[attr-defined]
        assert enum_values == literal_values, (
            f"{name} enum/label mismatch: enum={enum_values - literal_values} "
            f"literal={literal_values - enum_values}"
        )


class AssistantTaskAssignee(BaseModel):
    type: AssistantExecutorType
    id: str
    label: str | None = None


class AssistantTaskSnapshot(BaseModel):
    taskId: str
    graphId: str
    parentTaskId: str | None = None
    title: str
    descriptionPreview: str
    status: TaskStatus
    displayPhase: TaskDisplayPhase
    requiresReview: bool = False
    requiresConfirmation: bool = False
    safeExplanation: str = ""
    suspendReason: TaskSuspendReason | None = None
    assignee: AssistantTaskAssignee | None = None
    adjudicationId: str | None = None
    updatedAt: datetime | None = None
    externalCodingSessions: list[ExternalCodingSessionTaskSummary] = Field(default_factory=list)


class AssistantTaskEdgeSnapshot(BaseModel):
    sourceTaskId: str
    targetTaskId: str
    type: Literal["dependency", "delegation", "question", "meeting_channel", "resource_request"]


class AssistantTaskAdjudicationSnapshot(BaseModel):
    adjudicationId: str
    taskId: str
    safeSummary: str
    deliveredStatus: Literal["done", "stuck", "failed_input"]


class AssistantTaskGraphSnapshot(BaseModel):
    graphId: str
    sessionId: str
    userMessageSequence: int | None = None
    version: int
    tasks: list[AssistantTaskSnapshot] = Field(default_factory=list)
    edges: list[AssistantTaskEdgeSnapshot] = Field(default_factory=list)
    adjudications: list[AssistantTaskAdjudicationSnapshot] = Field(default_factory=list)


class AssistantCurrentTaskGraphResponse(BaseModel):
    graph: AssistantTaskGraphSnapshot | None = None


class AssistantTaskGraphStopRequest(BaseModel):
    runId: str | None = None


class AssistantTaskGraphStopResponse(BaseModel):
    accepted: bool
    graphId: str
    affectedTaskCount: int
    cancelSignalAccepted: bool = False


class AssistantTaskGraphContinueResponse(BaseModel):
    accepted: bool
    graphId: str
    resumedTaskCount: int
    startedAttemptCount: int = 0


class AssistantTaskGraphCancelRequest(BaseModel):
    expectedGraphVersion: int | None = None


class AssistantTaskGraphCancelResponse(BaseModel):
    accepted: bool
    graphId: str
    cancelledTaskCount: int


ExternalCodingTool = Literal["claude_code", "codex_cli"]
ExternalCodingLaunchMode = Literal["headless", "interactive"]
ExternalCodingOwnerType = Literal["task", "workflow"]
ExternalCodingStatus = Literal[
    "created",
    "planning",
    "plan_ready",
    "plan_approved",
    "plan_rejected",
    "implementing",
    "interrupted",
    "waiting_user",
    "completed",
    "merge_ready",
    "merged",
    "merge_blocked",
    "rollback_proposed",
    "rolled_back",
    "abandoned",
    "failed",
]
ExternalCodingPhase = Literal["plan", "implement", "merge", "rollback", "done"]
ExternalCodingAttemptStatus = Literal["running", "succeeded", "failed", "interrupted"]
ExternalCodingConflictRisk = Literal["low", "overlap", "conflict_predicted", "unknown"]
ExternalCodingMergeRecordStatus = Literal[
    "analysis_ready", "merged", "blocked", "failed", "rolled_back"
]
ExternalCodingRollbackStrategy = Literal["revert_commit", "reverse_patch", "reset_hard", "manual"]
ExternalCodingRollbackDecisionStatus = Literal["proposed", "applied", "blocked", "failed"]
ExternalCodingErrorCategory = Literal[
    "quota_exhausted",
    "missing_artifact",
    "protocol_violation",
    "process_error",
    "login_required",
    "network",
    "model_unavailable",
    "unknown",
]
ExternalCodingQuotaState = Literal["available", "low", "exhausted", "unknown"]

# Run sync assertions after all Literal types are defined
_assert_enum_literal_sync()


class ExternalCodingAttemptDetail(BaseModel):
    attemptId: str
    codingSessionId: str
    phase: ExternalCodingPhase
    launchMode: ExternalCodingLaunchMode
    commandSummary: str | None = None
    externalSessionRef: str | None = None
    status: ExternalCodingAttemptStatus
    pid: int | None = None
    exitCode: int | None = None
    startedAt: str | None = None
    finishedAt: str | None = None
    logPath: str | None = None
    logTail: str | None = None
    errorCategory: ExternalCodingErrorCategory | None = None
    errorMessage: str | None = None


class ExternalCodingQuotaObservation(BaseModel):
    observationId: str
    tool: ExternalCodingTool
    state: ExternalCodingQuotaState
    source: str | None = None
    confidence: float = 0.0
    resetAt: str | None = None
    checkedAt: str | None = None
    safeDetail: str | None = None


class ExternalCodingMergeRecordDetail(BaseModel):
    mergeRecordId: str
    codingSessionId: str
    targetBranch: str | None = None
    targetWorktreePath: str | None = None
    preMergeHead: str | None = None
    codingBranchHead: str | None = None
    dirtyFiles: list[str] = Field(default_factory=list)
    changedFiles: list[str] = Field(default_factory=list)
    overlapFiles: list[str] = Field(default_factory=list)
    conflictRisk: ExternalCodingConflictRisk
    agentDecision: str | None = None
    status: ExternalCodingMergeRecordStatus
    mergeCommit: str | None = None
    error: str | None = None
    createdAt: str | None = None
    mergedAt: str | None = None


class ExternalCodingRollbackDecisionDetail(BaseModel):
    rollbackId: str
    codingSessionId: str
    mergeRecordId: str | None = None
    intentSummary: str
    chosenStrategy: ExternalCodingRollbackStrategy
    safeExplanation: str
    requiresConfirmation: bool = True
    confirmedBy: str | None = None
    status: ExternalCodingRollbackDecisionStatus
    createdAt: str | None = None
    appliedAt: str | None = None


class ExternalCodingArtifacts(BaseModel):
    handoff: dict[str, str | None] = Field(default_factory=dict)
    plan: dict[str, str | None] | None = None
    result: dict[str, str | None] | None = None


class ExternalCodingSessionTaskSummary(BaseModel):
    """Lightweight summary for embedding in task snapshots."""

    codingSessionId: str
    tool: ExternalCodingTool
    status: ExternalCodingStatus
    phase: ExternalCodingPhase


class ExternalCodingSessionSummary(BaseModel):
    codingSessionId: str
    sessionId: str | None = None
    ownerType: ExternalCodingOwnerType
    ownerId: str
    tool: ExternalCodingTool
    launchMode: ExternalCodingLaunchMode
    status: ExternalCodingStatus
    phase: ExternalCodingPhase
    selectedReason: str | None = None
    quotaState: ExternalCodingQuotaState | None = None
    worktreePath: str
    branchName: str
    artifactDir: str
    planPreview: str | None = None
    resultPreview: str | None = None
    logTail: str | None = None
    lastErrorCategory: str | None = None
    lastErrorMessage: str | None = None
    resumeCount: int = 0
    reviewRecommended: bool = True
    reviewSkippedReason: str | None = None
    createdAt: str
    updatedAt: str
    completedAt: str | None = None


class ExternalCodingSessionDetail(ExternalCodingSessionSummary):
    attempts: list[ExternalCodingAttemptDetail] = Field(default_factory=list)
    quota: list[ExternalCodingQuotaObservation] = Field(default_factory=list)
    mergeRecords: list[ExternalCodingMergeRecordDetail] = Field(default_factory=list)
    rollbackDecisions: list[ExternalCodingRollbackDecisionDetail] = Field(default_factory=list)
    availableActions: list[str] = Field(default_factory=list)
    artifacts: ExternalCodingArtifacts = Field(default_factory=ExternalCodingArtifacts)


class ExternalCodingSessionListResponse(BaseModel):
    items: list[ExternalCodingSessionSummary] = Field(default_factory=list)


class ExternalCodingSessionCreateRequest(BaseModel):
    sessionId: str | None = None
    ownerType: ExternalCodingOwnerType
    ownerId: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    context: str = ""
    toolPreference: Literal["auto", "claude_code", "codex_cli"] = "auto"
    launchMode: ExternalCodingLaunchMode = "headless"
    targetBranch: str | None = None
    targetWorktreePath: str | None = None
    explicitExhaustedOverride: bool = False


class ExternalCodingPlanDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "clarification_requested"]
    decidedBy: Literal["agent", "user"] = "agent"
    feedback: str = ""


class ExternalCodingResumeRequest(BaseModel):
    instruction: str = ""
    phase: Literal["plan", "implement"] | None = None


class ExternalCodingReviewOutcomeRequest(BaseModel):
    independentlyReviewed: bool
    independentlyTested: bool
    skippedReason: str = ""


class ExternalCodingAbandonRequest(BaseModel):
    reason: str = Field(min_length=1)


class ExternalCodingMergeAnalysisRequest(BaseModel):
    targetBranch: str = Field(min_length=1)
    targetWorktreePath: str = Field(min_length=1)


class ExternalCodingMergeRequest(BaseModel):
    mergeRecordId: str = Field(min_length=1)
    agentDecision: str = ""


class ExternalCodingRollbackPlanRequest(BaseModel):
    intentSummary: str = Field(min_length=1)


class ExternalCodingRollbackConfirmRequest(BaseModel):
    rollbackId: str = Field(min_length=1)
    confirmedBy: Literal["agent", "user"] = "agent"


class ExternalCodingEscalateRequest(BaseModel):
    reason: str = Field(min_length=1)


class AssistantTaskAdjudicationDecisionRequest(BaseModel):
    decision: Literal["accepted", "returned", "abandoned"]
    instruction: str = ""


class AssistantTaskAdjudicationDecisionResponse(BaseModel):
    accepted: bool
    adjudicationId: str
    taskId: str
    graphId: str
    decision: Literal["accepted", "returned", "abandoned"]
    taskStatus: TaskStatus


class AssistantTaskBoardItem(BaseModel):
    taskId: str
    graphId: str
    title: str
    status: TaskStatus
    claimStatus: Literal["open", "claimed"]
    claimId: str | None = None
    assignee: AssistantTaskAssignee | None = None
    updatedAt: datetime | None = None


class AssistantTaskBoardResponse(BaseModel):
    items: list[AssistantTaskBoardItem] = Field(default_factory=list)


class AssistantTaskBoardClaimRequest(BaseModel):
    claimerType: AssistantExecutorType
    claimerId: str = Field(min_length=1)
    leaseSeconds: int = Field(default=60, ge=1, le=86_400)


class AssistantTaskBoardClaimResponse(BaseModel):
    accepted: bool
    claimId: str
    taskId: str
    status: Literal["claimed", "released", "expired", "rejected", "completed"]


class AssistantMeetingParticipant(BaseModel):
    type: AssistantExecutorType
    id: str
    label: str | None = None


class AssistantMeetingMessage(BaseModel):
    sequence: int
    senderId: str
    content: str
    createdAt: datetime | None = None


class AssistantMeetingTranscriptResponse(BaseModel):
    channelId: str
    status: Literal["open", "concluded", "closed_timeout", "closed_abandoned"]
    participants: list[AssistantMeetingParticipant] = Field(default_factory=list)
    turnsUsed: int = 0
    turnBudget: int = 0
    messages: list[AssistantMeetingMessage] = Field(default_factory=list)
    nextAfterSequence: int | None = None
    conclusion: str | None = None


class AssistantTodoItem(BaseModel):
    todoId: str
    text: str
    status: Literal["todo", "doing", "done", "skipped"]
    sortOrder: int


class AssistantTodoResponse(BaseModel):
    taskId: str
    items: list[AssistantTodoItem] = Field(default_factory=list)


class AssistantTodoUpdateRequest(BaseModel):
    executorType: AssistantExecutorType
    executorId: str = Field(min_length=1)
    items: list[AssistantTodoItem] = Field(default_factory=list)


UserTodoStatus = Literal["pending", "in_progress", "done"]
UserTodoPriority = Literal["low", "medium", "high", "urgent"]


class UserTodoItem(BaseModel):
    todoId: str
    title: str
    description: str = ""
    status: UserTodoStatus
    priority: UserTodoPriority
    sortOrder: int = 0
    createdAt: datetime | None = None
    updatedAt: datetime | None = None
    completedAt: datetime | None = None


class UserTodoListResponse(BaseModel):
    items: list[UserTodoItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0


class UserTodoCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    priority: UserTodoPriority = "medium"

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title is required")
        return value


class UserTodoUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: UserTodoStatus | None = None
    priority: UserTodoPriority | None = None

    @field_validator("title")
    @classmethod
    def optional_title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title is required")
        return value


class UserTodoCompleteRequest(BaseModel):
    done: bool = True


class AssistantActivityStep(BaseModel):
    kind: Literal["reasoning", "tool_call", "tool_result"]
    toolName: str | None = None
    text: str
    seq: int
    redacted: bool = False


class AssistantTranscriptResponse(BaseModel):
    steps: list[AssistantActivityStep]
    compressed: bool = False


class AssistantSubagentSummary(BaseModel):
    subagentId: str
    label: str
    task: str
    status: Literal["running", "done", "suspended", "failed"]
    lastOutput: str | None = None
    turnStartSequence: int | None = None


class AssistantSubagentListResponse(BaseModel):
    items: list[AssistantSubagentSummary]


class AssistantConfirmationDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]


class AssistantConfirmationDecisionResponse(BaseModel):
    requestId: str
    decision: Literal["approve", "deny"]
    accepted: bool


class AssistantClarificationOption(BaseModel):
    optionId: str
    label: str
    description: str | None = None
    preview: str | None = None


class AssistantClarificationQuestion(BaseModel):
    questionId: str
    question: str
    header: str
    multiSelect: bool = False
    options: list[AssistantClarificationOption]


class AssistantClarificationSnapshot(BaseModel):
    requestId: str
    sessionId: str
    questions: list[AssistantClarificationQuestion]
    expiresAt: str | None = None
    status: Literal["pending"] = "pending"


class AssistantClarificationPendingResponse(BaseModel):
    clarification: AssistantClarificationSnapshot | None = None


class AssistantClarificationAnswerInput(BaseModel):
    questionId: str
    selectedOptionIds: list[str] = Field(default_factory=list)
    otherText: str | None = None


class AssistantClarificationDecisionRequest(BaseModel):
    decision: Literal["submit", "cancel"]
    answers: list[AssistantClarificationAnswerInput] = Field(default_factory=list)


class AssistantClarificationDecisionResponse(BaseModel):
    requestId: str
    status: Literal["answered", "cancelled", "timeout", "stopped", "shutdown"]
    accepted: bool


class AssistantAutoApproveRequest(BaseModel):
    enabled: bool


class AssistantAutoApproveResponse(BaseModel):
    enabled: bool


class SegmentBoundaryRequest(BaseModel):
    session_id: str = Field(min_length=1)
    reason: Literal["window_close", "new_session", "token_limit"] = "window_close"


TeachingMode = Literal["browser", "extension", "desktop"]
TeachingStage = Literal[
    "selecting",
    "recording",
    "intent_confirmation",
    "learning",
    "trial_validation",
    "published",
    "failed",
    "abandoned",
]


class RecordingModeReadiness(BaseModel):
    mode: TeachingMode
    status: Literal["ready", "needs_setup", "unavailable"]
    message: str = ""
    actions: list[str] = Field(default_factory=list)


class TeachingReadinessResponse(BaseModel):
    modes: list[RecordingModeReadiness] = Field(default_factory=list)


class TeachingCreateRunRequest(BaseModel):
    mode: TeachingMode


class TeachingRunResponse(BaseModel):
    workflowId: str
    mode: TeachingMode
    stage: TeachingStage
    readiness: TeachingReadinessResponse | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class TeachingRecordingStartRequest(BaseModel):
    mode: TeachingMode
    windowMinimized: bool = False


class TeachingDesktopHealthDecisionRequest(BaseModel):
    decision: Literal["continue", "discard", "rerecord"]


class TeachingIntentReplyRequest(BaseModel):
    content: str


class TrialPreviewDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]


class TrialPreviewDecisionResponse(BaseModel):
    requestId: str
    decision: Literal["approve", "deny"]
    accepted: bool
    status: Literal["approved", "denied", "already_resolved", "conflict", "expired"]


class ToolSummary(BaseModel):
    toolId: str
    name: str
    description: str = ""
    status: Literal["pending", "published", "failed", "offline"]
    source: str = ""
    trialSuccessCount: int = 0
    workflowId: str | None = None
    failureStage: str | None = None
    errorSummary: str = ""
    is_builtin: bool = False


class SkillCategoryResponse(BaseModel):
    category: Literal["pending", "published", "failed"]
    count: int = 0
    items: list[ToolSummary] = Field(default_factory=list)


SkillOrigin = Literal[
    "system_bootstrap",
    "user_edit",
    "assistant_tool_call",
    "specialist_tool_call",
    "external_import",
]
SkillStatus = Literal["active", "superseded", "soft_deleted"]
BrainEntryStatus = Literal["active", "fading", "invalidated", "soft-deleted"]
EquipmentStatus = Literal["active", "unequipped"]
EquipmentEntityType = Literal["assistant", "specialist"]
UnequippedReason = Literal["user_unequip", "force_remove_on_soft_delete", "supersede_transfer"]
MAX_TOOL_WHITELIST_LENGTH = 200


class BrainEditEntryRequest(BaseModel):
    content: str = Field(..., min_length=1)
    scope: str | None = None

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class BrainCreateSpecialistRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    role_definition: str = Field(..., min_length=1)
    tool_whitelist: list[str] = Field(default_factory=list, max_length=MAX_TOOL_WHITELIST_LENGTH)

    @field_validator("name", "description", "role_definition")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("tool_whitelist")
    @classmethod
    def whitelist_items_not_empty(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class BrainUpdateSpecialistRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=1)
    role_definition: str | None = Field(default=None, min_length=1)
    tool_whitelist: list[str] | None = Field(
        default=None,
        max_length=MAX_TOOL_WHITELIST_LENGTH,
    )
    change_reason: str | None = None

    @field_validator("name", "description", "role_definition")
    @classmethod
    def optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value is not None else None

    @field_validator("tool_whitelist")
    @classmethod
    def optional_whitelist_items_not_empty(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item.strip()]


class SkillSummary(BaseModel):
    skill_id: str
    name: str
    description: str
    trigger_conditions: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    version: int = 1
    chain_root_id: str
    origin: SkillOrigin
    is_protected: bool = False
    loaded_count: int = 0
    referenced_count: int = 0
    equipped_count: int = 0
    last_referenced_at: datetime | None = None
    created_at: datetime | None = None


class SkillSourceSegment(BaseModel):
    segment_id: str
    source_zone: Literal["archive", "failure"]
    segment_summary: str = ""
    segment_status: BrainEntryStatus = "active"


class SkillDetail(SkillSummary):
    body_markdown: str
    parent_skill_id: str | None = None
    status: SkillStatus = "active"
    source_segments: list[SkillSourceSegment] = Field(default_factory=list)


class SkillListResponse(BaseModel):
    items: list[SkillSummary] = Field(default_factory=list)


class SkillSoftDeleteResponse(BaseModel):
    deleted_skill_id: str
    pruned_equipment_count: int = 0
    affected_specialist_ids: list[str] = Field(default_factory=list)


class SkillVersionNode(BaseModel):
    skill_id: str
    version: int
    name: str
    description: str
    trigger_conditions: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    body_markdown: str
    diff_from_previous: str | None = None
    origin: SkillOrigin
    changed_by: str | None = None
    change_reason: str | None = None
    created_at: datetime | None = None


class SkillHistoryResponse(BaseModel):
    chain_root_id: str
    nodes: list[SkillVersionNode] = Field(default_factory=list)


class SkillEquipmentItem(BaseModel):
    skill_id: str
    chain_root_id: str
    name: str
    description: str
    trigger_conditions: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    missing_required_tools: list[str] = Field(default_factory=list)
    equipped_order: int = 0
    equipped_at: datetime | None = None


class SkillEquipmentAuditRow(BaseModel):
    equipped_entity_type: EquipmentEntityType
    equipped_entity_id: str
    equipped_entity_name: str = ""
    status: EquipmentStatus
    equipped_at: datetime | None = None
    unequipped_at: datetime | None = None
    unequipped_reason: UnequippedReason | None = None

    @model_validator(mode="after")
    def status_fields_consistent(self) -> "SkillEquipmentAuditRow":
        if self.status == "unequipped":
            if self.unequipped_at is None or self.unequipped_reason is None:
                raise ValueError(
                    "unequipped rows must have both unequipped_at and unequipped_reason"
                )
        elif self.status == "active":
            if self.unequipped_at is not None or self.unequipped_reason is not None:
                raise ValueError("active rows must not have unequipped_at or unequipped_reason")
        return self


class SkillEquipmentAuditResponse(BaseModel):
    skill_id: str
    rows: list[SkillEquipmentAuditRow] = Field(default_factory=list)


class EquipmentUpdateItem(BaseModel):
    skill_id: str = Field(min_length=1)
    equipped_order: int = 0


class EquipmentUpdateRequest(BaseModel):
    skills: list[EquipmentUpdateItem] = Field(default_factory=list)


class EquipmentUpdateResponse(BaseModel):
    active_equipment_count: int = 0
    newly_equipped: list[str] = Field(default_factory=list)
    newly_unequipped: list[str] = Field(default_factory=list)
    reordered: list[str] = Field(default_factory=list)


class BootstrapStatusResponse(BaseModel):
    bootstrap_active_skill_id: str | None = None
    fallback_used: bool = False
    seed_file_path: str = ""
    last_seed_check_at: datetime | None = None


class TokenBudgetThresholds(BaseModel):
    warn_threshold: int = Field(gt=0)
    danger_threshold: int = Field(gt=0)

    @model_validator(mode="after")
    def warn_below_danger(self) -> "TokenBudgetThresholds":
        if self.warn_threshold >= self.danger_threshold:
            raise ValueError(
                f"warn_threshold ({self.warn_threshold}) must be less than "
                f"danger_threshold ({self.danger_threshold})"
            )
        return self


class EntityEquipmentResponse(BaseModel):
    entity_type: EquipmentEntityType
    entity_id: str
    entity_name: str
    tool_whitelist: list[str] = Field(default_factory=list)
    active_equipment: list[SkillEquipmentItem] = Field(default_factory=list)
    token_budget_estimate: int = 0
    token_budget_thresholds: TokenBudgetThresholds


class CompositionSummary(BaseModel):
    compositionId: str
    name: str
    description: str = ""
    mode: Literal["range", "ordered"]
    status: Literal["draft", "published", "offline"]
    displayStatus: Literal["draft", "published", "offline", "needs_review"] | None = None
    needsReview: bool = False
    members: list[dict[str, Any]] = Field(default_factory=list)
    applicability: str = ""


class SkillMetadataUpdateRequest(BaseModel):
    name: str
    description: str = ""


class SkillActionResponse(BaseModel):
    accepted: bool = True
    toolId: str | None = None
    workflowId: str | None = None
    message: str = ""


class SkillTrialReplyRequest(BaseModel):
    content: str = Field(min_length=1)


class CompositionMemberRequest(BaseModel):
    toolId: str = Field(min_length=1)
    selectedOrder: int = Field(default=1, ge=1)
    executionOrder: int | None = Field(default=None, ge=1)


class CompositionUpsertRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    mode: Literal["range", "ordered"] = "range"
    applicability: str = ""
    members: list[CompositionMemberRequest] = Field(default_factory=list, min_length=2)
    assistantEnabled: bool = True
    recommendOrder: bool = False


class CompositionListResponse(BaseModel):
    items: list[CompositionSummary] = Field(default_factory=list)


class CompositionAiHelperRequest(BaseModel):
    name: str = ""
    description: str = ""
    mode: Literal["range", "ordered"] = "range"
    applicability: str = ""
    members: list[CompositionMemberRequest] = Field(default_factory=list)


class CompositionApplicabilityResponse(BaseModel):
    applicability: str


class CompositionOrderResponse(BaseModel):
    members: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ""


class CompositionTrialRequest(BaseModel):
    task: str = ""
    context: str = ""


class SettingDescriptor(BaseModel):
    key: str
    label: str
    section: Literal["ai", "web", "tool_output", "recording", "data", "about"]
    valueKind: Literal["string", "integer", "number", "boolean", "enum", "path", "secret", "action"]
    description: str = ""
    options: list[str] = Field(default_factory=list)
    validationRules: dict[str, Any] = Field(default_factory=dict)
    status: Literal["available", "missing_secret", "invalid", "unavailable"] = "available"
    advanced: bool = False


class SettingSection(BaseModel):
    id: Literal["ai", "web", "tool_output", "recording", "data", "about"]
    label: str
    items: list[SettingDescriptor] = Field(default_factory=list)
    actions: list[SettingDescriptor] = Field(default_factory=list)


class SettingsSchemaResponse(BaseModel):
    sections: list[SettingSection] = Field(default_factory=list)


class SettingsValuesResponse(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    status: dict[str, str] = Field(default_factory=dict)


class SettingsValuesUpdateRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class SettingsSecretWriteRequest(BaseModel):
    value: str


class SettingsSecretResponse(BaseModel):
    secretKey: str
    present: bool
    masked: str = ""


class SettingsActionRequest(BaseModel):
    confirmed: bool = False


class SettingsActionResponse(BaseModel):
    actionName: str
    status: Literal["completed", "failed", "unavailable"]
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class DebugLimits(BaseModel):
    maxRecords: int
    maxRecordBytes: int
    maxTotalBytes: int


class DebugControlStatus(BaseModel):
    enabled: bool
    armedAt: str | None = None
    retentionEpoch: str | None = None
    warning: str
    limits: DebugLimits


class DebugControlRequest(BaseModel):
    enabled: bool
    warningAcknowledged: bool = False


class DebugTraceListItem(BaseModel):
    traceId: str
    method: str
    source: str
    agentType: str | None = None
    sessionId: str | None = None
    workflowId: str | None = None
    workUnitId: str | None = None
    iteration: int | None = None
    outcome: str
    detailAvailability: str
    retainedBytes: int
    createdAt: datetime
    completedAt: datetime | None = None
    summary: str | None = None
    linkedTransitionIds: list[str] = Field(default_factory=list)


class DebugTraceListResponse(BaseModel):
    items: list[DebugTraceListItem] = Field(default_factory=list)
    retainedBytes: int = 0
    omittedCount: int = 0
    warning: str


class DebugTraceDetail(BaseModel):
    traceId: str
    method: str
    source: str
    agentType: str | None = None
    sessionId: str | None = None
    workflowId: str | None = None
    workUnitId: str | None = None
    iteration: int | None = None
    inputMessages: Any = None
    inputMedia: Any = None
    inputTools: Any = None
    outputContent: str | None = None
    outputToolCalls: Any = None
    outcome: str
    errorSummary: str | None = None
    detailAvailability: str
    retainedBytes: int
    linkedTransitionIds: list[str] = Field(default_factory=list)
    createdAt: datetime
    completedAt: datetime | None = None


class DebugFlowListItem(BaseModel):
    workflowId: str
    transitionCount: int
    lastEventType: str
    lastCreatedAt: datetime | None = None
    linkedTraceCount: int = 0


class DebugFlowListResponse(BaseModel):
    items: list[DebugFlowListItem] = Field(default_factory=list)


class DebugFlowDetailResponse(BaseModel):
    workflowId: str
    transitions: list[dict[str, Any]] = Field(default_factory=list)


class DebugReferenceResponse(BaseModel):
    referenceId: str
    content: str | None = None
    available: bool
    truncated: bool = False
    nextChunk: str | None = None
