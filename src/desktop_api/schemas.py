from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

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
    role: Literal["user", "assistant"]
    content: str
    createdAt: datetime | None = None
    rendering: Literal["plain_text", "safe_markdown"]


class AssistantMessagesResponse(BaseModel):
    items: list[AssistantMessage] = Field(default_factory=list)
    hasMoreBefore: bool = False
    nextBeforeSequence: int | None = None


class AssistantSendMessageRequest(BaseModel):
    content: str


class AssistantSendMessageResponse(BaseModel):
    accepted: bool
    sessionId: str


class AssistantConfirmationDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]


class AssistantConfirmationDecisionResponse(BaseModel):
    requestId: str
    decision: Literal["approve", "deny"]
    accepted: bool


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


class SkillSummary(BaseModel):
    toolId: str
    name: str
    description: str = ""
    status: Literal["pending", "published", "failed", "offline"]
    source: str = ""
    trialSuccessCount: int = 0
    workflowId: str | None = None
    failureStage: str | None = None
    errorSummary: str = ""


class SkillCategoryResponse(BaseModel):
    category: Literal["pending", "published", "failed"]
    count: int = 0
    items: list[SkillSummary] = Field(default_factory=list)


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
    members: list[CompositionMemberRequest] = Field(default_factory=list, min_length=1)
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
    section: Literal["ai", "recording", "data", "about"]
    valueKind: Literal["string", "integer", "number", "boolean", "enum", "path", "secret", "action"]
    description: str = ""
    options: list[str] = Field(default_factory=list)
    validationRules: dict[str, Any] = Field(default_factory=dict)
    status: Literal["available", "missing_secret", "invalid", "unavailable"] = "available"


class SettingSection(BaseModel):
    id: Literal["ai", "recording", "data", "about"]
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
