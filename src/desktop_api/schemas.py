from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

BackendStatus = Literal["starting", "ready", "degraded", "failed", "shutting_down"]
SessionStatus = Literal["active", "suspended", "completed", "failed", "archived"]
UiTheme = Literal["light", "dark", "system", "sage"]
UiDensity = Literal["compact", "comfy"]


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


class AssistantMessage(BaseModel):
    sequence: int
    role: Literal["user", "assistant", "summary"]
    content: str
    createdAt: datetime | None = None
    rendering: Literal["plain_text", "safe_markdown"]


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


class AssistantStopRequest(BaseModel):
    runId: str | None = None


class AssistantStopResponse(BaseModel):
    accepted: bool


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
    section: Literal["ai", "web", "recording", "data", "about"]
    valueKind: Literal["string", "integer", "number", "boolean", "enum", "path", "secret", "action"]
    description: str = ""
    options: list[str] = Field(default_factory=list)
    validationRules: dict[str, Any] = Field(default_factory=dict)
    status: Literal["available", "missing_secret", "invalid", "unavailable"] = "available"


class SettingSection(BaseModel):
    id: Literal["ai", "web", "recording", "data", "about"]
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
