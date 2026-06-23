export const UI_EVENT_TYPES = [
  "assistant.message",
  "assistant.progress",
  "assistant.error",
  "assistant.confirmation",
  "assistant.clarification_requested",
  "assistant.clarification_resolved",
  "assistant.activity",
  "assistant.subagent",
  "assistant.task_graph.changed",
  "assistant.task_board.changed",
  "assistant.task_question.changed",
  "assistant.meeting.changed",
  "assistant.todo.changed",
  "recording.progress",
  "teaching.stage_changed",
  "teaching.progress",
  "trial.progress",
  "trial.preview_requested",
  "trial.preview_resolved",
  "tools.changed",
  "skill.changed",
  "skill.equipment.changed",
  "compositions.changed",
  "settings.changed",
  "brain_zone_changed",
  "brain_specialist_recruited",
  "brain_specialist_changed",
  "brain_context_ready",
  "backend.resync_required",
] as const;

export type UiEventType = (typeof UI_EVENT_TYPES)[number];

export const UI_EVENT_EXAMPLES = {
  "assistant.message": { "sequence": 1, "role": "assistant", "content": "Ready.", "rendering": "safe_markdown" },
  "assistant.progress": { "status": "running", "headline": "Assistant is working", "runId": "run-1" },
  "assistant.error": { "message": "Assistant failed to complete the request.", "type": "RuntimeError" },
  "assistant.confirmation": {
    "requestId": "req_1",
    "actionType": "exec",
    "sanitizedSummary": "命令首行: npm test",
    "status": "active",
  },
  "assistant.clarification_requested": {
    "requestId": "clr_1",
    "sessionId": "sess_1",
    "questions": [
      {
        "questionId": "q1",
        "question": "选择执行方式？",
        "header": "执行方式",
        "multiSelect": false,
        "options": [{ "optionId": "q1o1", "label": "按顺序执行" }],
      },
    ],
    "expiresAt": "2026-06-15T08:05:00Z",
    "status": "pending",
  },
  "assistant.clarification_resolved": { "requestId": "clr_1", "sessionId": "sess_1", "status": "answered" },
  "assistant.activity": { "kind": "tool_call", "toolName": "delegate_to_subagent", "text": "派发子任务", "seq": 1 },
  "assistant.subagent": {
    "subagentId": "sess_child_1",
    "label": "子助手 · 资料检索",
    "task": "检索最新季度报表",
    "status": "running",
  },
  "assistant.task_graph.changed": {
    "graphId": "tg_123",
    "taskId": "tsk_1",
    "changeType": "task_updated",
    "status": "running",
    "displayPhase": "reviewing",
    "requiresReview": true,
    "safeExplanation": "等待上级检查结果",
    "suspendReason": null,
    "sequence": 42,
  },
  "assistant.task_board.changed": {
    "taskId": "tsk_9",
    "graphId": "tg_123",
    "changeType": "claimed",
  },
  "assistant.task_question.changed": {
    "questionId": "qst_1",
    "taskId": "tsk_1",
    "graphId": "tg_123",
    "kind": "resource_request",
    "status": "escalated_to_parent",
    "changeType": "created",
  },
  "assistant.meeting.changed": {
    "channelId": "mtg_1",
    "graphId": "tg_123",
    "changeType": "message_added",
  },
  "assistant.todo.changed": {
    "taskId": "tsk_1",
    "todoId": "todo_1",
    "changeType": "updated",
  },
  "recording.progress": { "status": "recording", "message": "Recording started.", "recordingMode": "desktop" },
  "teaching.stage_changed": { "stage": "learning", "message": "Tool learning started." },
  "teaching.progress": { "status": "running", "headline": "Tool learning started" },
  "trial.progress": { "status": "succeeded", "published": false, "successCount": 1 },
  "trial.preview_requested": {
    "requestId": "preview_1",
    "workflowId": "rec_1",
    "trialId": "trial_1",
    "summary": "桌面试用需要确认。",
    "codePreview": "async def execute(): ...",
    "riskSummary": "将控制本机桌面。",
    "expires_at": "2026-05-16T00:00:30Z",
    "status": "pending",
  },
  "trial.preview_resolved": {
    "requestId": "preview_1",
    "workflowId": "rec_1",
    "trialId": "trial_1",
    "decision": "deny",
    "status": "timeout",
  },
  "tools.changed": { "reason": "catalog_invalidated" },
  "skill.changed": {
    "reason": "create",
    "skillId": "skl_abc",
    "chainRootId": "skl_abc",
  },
  "skill.equipment.changed": {
    "changeType": "equipped",
    "entityType": "assistant",
    "entityId": "_assistant",
    "skillId": "skl_abc",
  },
  "compositions.changed": { "reason": "catalog_invalidated" },
  "settings.changed": { "reason": "settings_invalidated", "keys": [] },
  "brain_zone_changed": { "zone": "hot", "entryId": "entry_1", "changeType": "create" },
  "brain_specialist_recruited": {
    "specialistId": "spec_1",
    "name": "报表专员",
    "reason": "检测到持续报表委托",
    "managementUrl": "/brain/specialists",
  },
  "brain_specialist_changed": { "specialistId": "spec_1", "changeType": "update" },
  "brain_context_ready": { "sessionId": "sess_1" },
  "backend.resync_required": { "reason": "replay_gap", "domains": ["teaching", "tools", "brain", "skill"] },
} as const satisfies Record<UiEventType, Record<string, unknown>>;

export const UI_EVENT_PAYLOAD_ENUMS = {
  "assistant.message": {
    "role": ["assistant", "summary", "user"],
    "rendering": ["plain_text", "safe_markdown"],
  },
  "assistant.confirmation": {
    "actionType": [
      "edit_file",
      "exec",
      "skill.edit_protected",
      "skill.soft_delete",
      "unknown",
      "write_file",
    ],
    "status": ["active"],
  },
  "assistant.clarification_requested": {
    "status": ["pending"],
  },
  "assistant.clarification_resolved": {
    "status": ["answered", "cancelled", "shutdown", "stopped", "timeout"],
  },
  "assistant.progress": {
    "status": ["cancelled", "failed", "running", "succeeded", "waiting_for_user"],
  },
  "assistant.activity": {
    "kind": ["reasoning", "tool_call", "tool_result"],
  },
  "assistant.subagent": {
    "status": ["done", "failed", "running", "suspended"],
  },
  "assistant.task_graph.changed": {
    "changeType": [
      "adjudication_created",
      "adjudication_decided",
      "edge_created",
      "graph_cancelled",
      "graph_completed",
      "graph_continued",
      "graph_created",
      "graph_stopped",
      "root_failed",
      "task_created",
      "task_updated",
    ],
    "status": [
      "cancelled",
      "completed",
      "failed",
      "pending_dispatch",
      "running",
      "suspended",
    ],
    "displayPhase": [
      "done",
      "needs_attention",
      "paused",
      "reviewing",
      "running",
    ],
    "suspendReason": [
      "user_stop",
      "waiting_system",
      "waiting_user",
    ],
  },
  "assistant.task_board.changed": {
    "changeType": ["claimed", "completed", "expired", "opened", "rejected", "released"],
  },
  "assistant.task_question.changed": {
    "kind": ["capability_request", "clarification", "resource_request"],
    "status": [
      "answered",
      "cancelled",
      "escalated_to_parent",
      "escalated_to_user",
      "expired",
      "open",
    ],
    "changeType": ["answered", "cancelled", "created", "escalated_to_user", "expired"],
  },
  "assistant.meeting.changed": {
    "changeType": [
      "closed_abandoned",
      "closed_timeout",
      "concluded",
      "message_added",
      "opened",
    ],
  },
  "assistant.todo.changed": {
    "changeType": ["created", "deleted", "reordered", "updated"],
    "status": ["doing", "done", "skipped", "todo"],
  },
  "teaching.stage_changed": {
    "stage": [
      "abandoned",
      "failed",
      "intent_confirmation",
      "learning",
      "published",
      "recording",
      "selecting",
      "trial_validation",
    ],
  },
  "trial.preview_requested": {
    "status": ["pending"],
  },
  "trial.preview_resolved": {
    "decision": ["approve", "deny"],
    "status": [
      "already_resolved",
      "approved",
      "conflict",
      "denied",
      "disconnect",
      "expired",
      "overflow",
      "shutdown",
      "timeout",
    ],
  },
  "skill.changed": {
    "reason": [
      "bootstrap_fallback_used",
      "create",
      "soft_delete",
      "supersede",
      "user_edit",
    ],
    "callerType": ["assistant", "specialist", "system", "user"],
  },
  "skill.equipment.changed": {
    "changeType": [
      "default_propagate",
      "equipped",
      "force_remove_on_soft_delete",
      "reorder",
      "supersede_transfer",
      "unequipped",
    ],
    "entityType": ["assistant", "specialist"],
  },
} as const satisfies Partial<Record<UiEventType, Record<string, readonly string[]>>>;

export type UiEventHandlerDomain =
  | "assistant"
  | "teaching"
  | "skills"
  | "skill"
  | "compositions"
  | "settings"
  | "brain"
  | "resync";

export const UI_EVENT_HANDLER_DOMAINS = {
  "assistant.message": "assistant",
  "assistant.progress": "assistant",
  "assistant.error": "assistant",
  "assistant.confirmation": "assistant",
  "assistant.clarification_requested": "assistant",
  "assistant.clarification_resolved": "assistant",
  "assistant.activity": "assistant",
  "assistant.subagent": "assistant",
  "assistant.task_graph.changed": "assistant",
  "assistant.task_board.changed": "assistant",
  "assistant.task_question.changed": "assistant",
  "assistant.meeting.changed": "assistant",
  "assistant.todo.changed": "assistant",
  "recording.progress": "teaching",
  "teaching.stage_changed": "teaching",
  "teaching.progress": "teaching",
  "trial.progress": "teaching",
  "trial.preview_requested": "teaching",
  "trial.preview_resolved": "teaching",
  "tools.changed": "skills",
  "skill.changed": "skill",
  "skill.equipment.changed": "skill",
  "compositions.changed": "compositions",
  "settings.changed": "settings",
  "brain_zone_changed": "brain",
  "brain_specialist_recruited": "brain",
  "brain_specialist_changed": "brain",
  "brain_context_ready": "brain",
  "backend.resync_required": "resync",
} as const satisfies Record<UiEventType, UiEventHandlerDomain>;

export type TeachingStage =
  | "selecting"
  | "recording"
  | "intent_confirmation"
  | "learning"
  | "trial_validation"
  | "published"
  | "failed"
  | "abandoned";

type AssistantMessageRole = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.message"]["role"][number];
type AssistantMessageRendering = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.message"]["rendering"][number];
type AssistantConfirmationActionType =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.confirmation"]["actionType"][number];
type AssistantConfirmationStatus = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.confirmation"]["status"][number];

interface UiEventEnvelope<TType extends UiEventType = UiEventType, TPayload = Record<string, unknown>> {
  eventId: string;
  sequence: number;
  sessionId: string;
  causationId?: string | null;
  type: TType;
  scope: Record<string, string>;
  payload: TPayload;
  createdAt: string;
}

export type AssistantMessageEvent = UiEventEnvelope<
  "assistant.message",
  {
    sequence: number;
    role: AssistantMessageRole;
    content: string;
    createdAt: string | null;
    rendering: AssistantMessageRendering;
    failure?: {
      category:
        | "authentication"
        | "invalid_request"
        | "quota"
        | "network"
        | "provider"
        | "iteration_limit"
        | "internal";
      message: string;
      suggestion: string;
      attemptCount: number;
      failedAt: string;
    };
  }
>;

export type AssistantConfirmationEvent = UiEventEnvelope<
  "assistant.confirmation",
  {
    requestId: string;
    sessionId?: string;
    actionType: AssistantConfirmationActionType;
    sanitizedSummary: string;
    status: AssistantConfirmationStatus;
    expiresAt?: string | null;
    affectedSkillId?: string;
    affectedEquipmentCount?: number;
    affectedSpecialistNames?: string[];
  }
>;

export interface ClarificationOptionPayload {
  optionId: string;
  label: string;
  description?: string | null;
  preview?: string | null;
}

export interface ClarificationQuestionPayload {
  questionId: string;
  question: string;
  header: string;
  multiSelect: boolean;
  options: ClarificationOptionPayload[];
}

export type ClarificationRequestedEvent = UiEventEnvelope<
  "assistant.clarification_requested",
  {
    requestId: string;
    sessionId: string;
    questions: ClarificationQuestionPayload[];
    expiresAt?: string | null;
    status: "pending";
  }
>;

export type ClarificationResolvedEvent = UiEventEnvelope<
  "assistant.clarification_resolved",
  {
    requestId: string;
    sessionId: string;
    status: "answered" | "cancelled" | "timeout" | "stopped" | "shutdown";
  }
>;

type TeachingStageChangedEvent = UiEventEnvelope<
  "teaching.stage_changed",
  {
    stage: TeachingStage;
    status?: string;
    message?: string;
    headline?: string;
    failureStage?: string | null;
    successCount?: number | null;
    published?: boolean;
  }
>;

type RecordingProgressEvent = UiEventEnvelope<
  "recording.progress",
  {
    status?: string;
    message?: string;
    headline?: string;
    recordingMode?: string;
    actionCount?: number;
    degraded?: boolean;
    subsystem?: string;
    error?: string;
  }
>;

type TeachingProgressEvent = UiEventEnvelope<
  "teaching.progress",
  {
    status: string;
    message?: string;
    headline?: string;
    question?: string;
    failureStage?: string | null;
    error?: string;
    type?: string;
  }
>;

type TrialProgressEvent = UiEventEnvelope<
  "trial.progress",
  {
    status: string;
    message?: string;
    headline?: string;
    toolId?: string;
    successCount?: number | null;
    published?: boolean;
    trialId?: string;
    result?: string;
    error?: string;
    type?: string;
  }
>;

export type TrialPreviewRequestedEvent = UiEventEnvelope<
  "trial.preview_requested",
  {
    requestId: string;
    workflowId: string;
    trialId: string;
    summary: string;
    codePreview: string;
    riskSummary: string;
    expires_at: string;
    status: "pending";
  }
>;

type TrialPreviewResolvedEvent = UiEventEnvelope<
  "trial.preview_resolved",
  {
    requestId: string;
    workflowId: string;
    trialId?: string;
    decision: "approve" | "deny";
    status:
      | "approved"
      | "denied"
      | "timeout"
      | "disconnect"
      | "overflow"
      | "shutdown"
      | "already_resolved"
      | "conflict"
      | "expired";
    message?: string;
  }
>;

export type ResyncRequiredEvent = UiEventEnvelope<
  "backend.resync_required",
  {
    reason: string;
    domains?: string[];
    lastAvailableSequence?: number | null;
    eventSessionId?: string;
  }
>;

export type BrainZoneChangedEvent = UiEventEnvelope<
  "brain_zone_changed",
  {
    zone: string;
    entryId?: string;
    changeType: string;
  }
>;

export type BrainSpecialistRecruitedEvent = UiEventEnvelope<
  "brain_specialist_recruited",
  {
    specialistId: string;
    name: string;
    reason: string;
    managementUrl?: string;
  }
>;

export type BrainSpecialistChangedEvent = UiEventEnvelope<
  "brain_specialist_changed",
  {
    specialistId: string;
    changeType: string;
  }
>;

export type BrainContextReadyEvent = UiEventEnvelope<
  "brain_context_ready",
  {
    sessionId: string;
  }
>;

type SkillChangedReason = (typeof UI_EVENT_PAYLOAD_ENUMS)["skill.changed"]["reason"][number];
type SkillChangedCallerType = (typeof UI_EVENT_PAYLOAD_ENUMS)["skill.changed"]["callerType"][number];
type SkillEquipmentChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["skill.equipment.changed"]["changeType"][number];
type SkillEquipmentEntityType = (typeof UI_EVENT_PAYLOAD_ENUMS)["skill.equipment.changed"]["entityType"][number];
type TaskBoardChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_board.changed"]["changeType"][number];
type TaskGraphChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_graph.changed"]["changeType"][number];
type TaskGraphStatus = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_graph.changed"]["status"][number];
type TaskGraphDisplayPhase = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_graph.changed"]["displayPhase"][number];
type TaskGraphSuspendReason = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_graph.changed"]["suspendReason"][number];
type TaskQuestionKind = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_question.changed"]["kind"][number];
type TaskQuestionStatus = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_question.changed"]["status"][number];
type TaskQuestionChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_question.changed"]["changeType"][number];
type MeetingChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.meeting.changed"]["changeType"][number];
type TodoChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.todo.changed"]["changeType"][number];
type TodoStatus = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.todo.changed"]["status"][number];

export type TaskBoardChangedEvent = UiEventEnvelope<
  "assistant.task_board.changed",
  {
    taskId: string;
    graphId?: string;
    changeType: TaskBoardChangeType;
    claimStatus?: string;
    updatedAt?: string;
  }
>;

export type TaskGraphChangedEvent = UiEventEnvelope<
  "assistant.task_graph.changed",
  {
    graphId: string;
    taskId?: string | null;
    changeType: TaskGraphChangeType;
    status?: TaskGraphStatus | null;
    displayPhase?: TaskGraphDisplayPhase | null;
    requiresReview?: boolean | null;
    safeExplanation?: string | null;
    suspendReason?: TaskGraphSuspendReason | null;
    sequence?: number | null;
  }
>;

export type TaskQuestionChangedEvent = UiEventEnvelope<
  "assistant.task_question.changed",
  {
    questionId: string;
    taskId: string;
    graphId?: string;
    kind?: TaskQuestionKind;
    status?: TaskQuestionStatus;
    changeType: TaskQuestionChangeType;
  }
>;

export type MeetingChangedEvent = UiEventEnvelope<
  "assistant.meeting.changed",
  {
    channelId: string;
    graphId?: string;
    taskId?: string;
    changeType: MeetingChangeType;
    sequence?: number | null;
    status?: string;
  }
>;

export type TodoChangedEvent = UiEventEnvelope<
  "assistant.todo.changed",
  {
    taskId: string;
    todoId: string;
    changeType: TodoChangeType;
    status?: TodoStatus;
    sortOrder?: number;
  }
>;

export type SkillChangedEvent = UiEventEnvelope<
  "skill.changed",
  {
    reason: SkillChangedReason;
    skillId: string;
    chainRootId: string;
    newSkillId?: string | null;
    callerType?: SkillChangedCallerType | null;
    callerId?: string | null;
    bootstrapFallbackUsed?: boolean;
    bootstrapFallbackInfo?: { reason: string | null; seedFilePath: string | null } | null;
  }
>;

export type SkillEquipmentChangedEvent = UiEventEnvelope<
  "skill.equipment.changed",
  {
    changeType: SkillEquipmentChangeType;
    entityType: SkillEquipmentEntityType;
    entityId: string;
    skillId: string;
    unequippedReason?: string | null;
  }
>;

export type UiEvent =
  | AssistantMessageEvent
  | AssistantConfirmationEvent
  | ClarificationRequestedEvent
  | ClarificationResolvedEvent
  | TeachingStageChangedEvent
  | RecordingProgressEvent
  | TeachingProgressEvent
  | TrialProgressEvent
  | TrialPreviewRequestedEvent
  | TrialPreviewResolvedEvent
  | ResyncRequiredEvent
  | BrainZoneChangedEvent
  | BrainSpecialistRecruitedEvent
  | BrainSpecialistChangedEvent
  | BrainContextReadyEvent
  | SkillChangedEvent
  | SkillEquipmentChangedEvent
  | TaskBoardChangedEvent
  | TaskGraphChangedEvent
  | TaskQuestionChangedEvent
  | MeetingChangedEvent
  | TodoChangedEvent
  | UiEventEnvelope<
      Exclude<
        UiEventType,
        | "assistant.message"
        | "assistant.confirmation"
        | "assistant.clarification_requested"
        | "assistant.clarification_resolved"
        | "recording.progress"
        | "teaching.stage_changed"
        | "teaching.progress"
        | "trial.progress"
        | "trial.preview_requested"
        | "trial.preview_resolved"
        | "backend.resync_required"
        | "brain_zone_changed"
        | "brain_specialist_recruited"
        | "brain_specialist_changed"
        | "brain_context_ready"
        | "skill.changed"
        | "skill.equipment.changed"
        | "assistant.task_graph.changed"
        | "assistant.task_board.changed"
        | "assistant.task_question.changed"
        | "assistant.meeting.changed"
        | "assistant.todo.changed"
      >
    >;

const UI_EVENT_TYPE_SET = new Set<string>(UI_EVENT_TYPES);
const ASSISTANT_MESSAGE_ROLE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.message"].role);
const ASSISTANT_MESSAGE_RENDERING_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.message"].rendering);
const ASSISTANT_FAILURE_CATEGORY_SET = new Set<string>([
  "authentication",
  "invalid_request",
  "quota",
  "network",
  "provider",
  "iteration_limit",
  "internal",
]);
const ASSISTANT_CONFIRMATION_ACTION_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.confirmation"].actionType);
const ASSISTANT_CONFIRMATION_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.confirmation"].status);
const CLARIFICATION_RESOLVED_STATUS_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["assistant.clarification_resolved"].status,
);
const TEACHING_STAGE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["teaching.stage_changed"].stage);
const TRIAL_PREVIEW_REQUEST_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["trial.preview_requested"].status);
const TRIAL_PREVIEW_DECISION_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["trial.preview_resolved"].decision);
const TRIAL_PREVIEW_RESOLUTION_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["trial.preview_resolved"].status);
const SKILL_CHANGED_REASON_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["skill.changed"].reason);
const SKILL_CHANGED_CALLER_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["skill.changed"].callerType);
const SKILL_EQUIPMENT_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["skill.equipment.changed"].changeType);
const SKILL_EQUIPMENT_ENTITY_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["skill.equipment.changed"].entityType);
const TASK_GRAPH_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_graph.changed"].changeType);
const TASK_GRAPH_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_graph.changed"].status);
const TASK_GRAPH_DISPLAY_PHASE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_graph.changed"].displayPhase);
const TASK_GRAPH_SUSPEND_REASON_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_graph.changed"].suspendReason);
const TASK_QUESTION_KIND_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_question.changed"].kind);
const TASK_QUESTION_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_question.changed"].status);
const TASK_QUESTION_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_question.changed"].changeType);
const TASK_BOARD_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_board.changed"].changeType);
const MEETING_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.meeting.changed"].changeType);
const TODO_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.todo.changed"].changeType);
const TODO_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.todo.changed"].status);

function isUiEventType(value: string): value is UiEventType {
  return UI_EVENT_TYPE_SET.has(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function parseScope(value: unknown): Record<string, string> | null {
  if (value === undefined || value === null) return {};
  if (!isRecord(value)) return null;
  const entries = Object.entries(value);
  if (entries.some(([, entryValue]) => typeof entryValue !== "string")) return null;
  return Object.fromEntries(entries) as Record<string, string>;
}

function hasWorkflowScope(event: { scope: Record<string, string> }): boolean {
  return typeof event.scope.workflowId === "string" && event.scope.workflowId.length > 0;
}

function isValidDateString(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

function hasStringPayloadFields(payload: Record<string, unknown>, fields: string[]): boolean {
  return fields.every((field) => typeof payload[field] === "string" && String(payload[field]).length > 0);
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}

function isOptionalNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

function isOptionalNumber(value: unknown): value is number | undefined {
  return value === undefined || (typeof value === "number" && Number.isFinite(value));
}

function isOptionalNullableNumber(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || (typeof value === "number" && Number.isFinite(value));
}

function isEnumMember<T extends string>(set: Set<string>, value: unknown): value is T {
  return typeof value === "string" && set.has(value);
}

function isOptionalNullableEnumMember<T extends string>(set: Set<string>, value: unknown): value is T | null | undefined {
  return value === undefined || value === null || isEnumMember<T>(set, value);
}

function makeEnumGuard<T extends string>(set: Set<string>) {
  return (v: unknown): v is T => isEnumMember<T>(set, v);
}

const isAssistantMessageRole = makeEnumGuard<AssistantMessageRole>(ASSISTANT_MESSAGE_ROLE_SET);
const isAssistantMessageRendering = makeEnumGuard<AssistantMessageRendering>(ASSISTANT_MESSAGE_RENDERING_SET);
const isAssistantConfirmationActionType = makeEnumGuard<AssistantConfirmationActionType>(ASSISTANT_CONFIRMATION_ACTION_SET);
const isAssistantConfirmationStatus = makeEnumGuard<AssistantConfirmationStatus>(ASSISTANT_CONFIRMATION_STATUS_SET);
const isSkillChangedReason = makeEnumGuard<SkillChangedReason>(SKILL_CHANGED_REASON_SET);
const isSkillEquipmentChangeType = makeEnumGuard<SkillEquipmentChangeType>(SKILL_EQUIPMENT_CHANGE_TYPE_SET);
const isSkillEquipmentEntityType = makeEnumGuard<SkillEquipmentEntityType>(SKILL_EQUIPMENT_ENTITY_TYPE_SET);
const isTaskGraphChangeType = makeEnumGuard<TaskGraphChangeType>(TASK_GRAPH_CHANGE_TYPE_SET);
const isTaskQuestionChangeType = makeEnumGuard<TaskQuestionChangeType>(TASK_QUESTION_CHANGE_TYPE_SET);
const isTaskBoardChangeType = makeEnumGuard<TaskBoardChangeType>(TASK_BOARD_CHANGE_TYPE_SET);
const isMeetingChangeType = makeEnumGuard<MeetingChangeType>(MEETING_CHANGE_TYPE_SET);
const isTodoChangeType = makeEnumGuard<TodoChangeType>(TODO_CHANGE_TYPE_SET);
const isOptionalTaskGraphStatus = (v: unknown): v is TaskGraphStatus | null | undefined =>
  isOptionalNullableEnumMember<TaskGraphStatus>(TASK_GRAPH_STATUS_SET, v);
const isOptionalTaskGraphDisplayPhase = (v: unknown): v is TaskGraphDisplayPhase | null | undefined =>
  isOptionalNullableEnumMember<TaskGraphDisplayPhase>(TASK_GRAPH_DISPLAY_PHASE_SET, v);
const isOptionalTaskGraphSuspendReason = (v: unknown): v is TaskGraphSuspendReason | null | undefined =>
  isOptionalNullableEnumMember<TaskGraphSuspendReason>(TASK_GRAPH_SUSPEND_REASON_SET, v);
const isOptionalTaskQuestionKind = (v: unknown): v is TaskQuestionKind | undefined =>
  v === undefined || isEnumMember<TaskQuestionKind>(TASK_QUESTION_KIND_SET, v);
const isOptionalTaskQuestionStatus = (v: unknown): v is TaskQuestionStatus | undefined =>
  v === undefined || isEnumMember<TaskQuestionStatus>(TASK_QUESTION_STATUS_SET, v);
const isOptionalTodoStatus = (v: unknown): v is TodoStatus | undefined =>
  v === undefined || isEnumMember<TodoStatus>(TODO_STATUS_SET, v);
const isOptionalSkillChangedCallerType = (v: unknown): v is SkillChangedCallerType | null | undefined =>
  isOptionalNullableEnumMember<SkillChangedCallerType>(SKILL_CHANGED_CALLER_TYPE_SET, v);

function parseAssistantMessagePayload(payload: Record<string, unknown>): AssistantMessageEvent["payload"] | null {
  if (
    typeof payload.sequence !== "number" ||
    !Number.isInteger(payload.sequence) ||
    payload.sequence < 0 ||
    !isAssistantMessageRole(payload.role) ||
    typeof payload.content !== "string" ||
    !isOptionalNullableString(payload.createdAt) ||
    !isAssistantMessageRendering(payload.rendering)
  ) {
    return null;
  }
  const rawFailure = payload.failure;
  let failure: AssistantMessageEvent["payload"]["failure"];
  if (rawFailure !== undefined) {
    if (
      payload.role !== "user" ||
      !isRecord(rawFailure) ||
      !ASSISTANT_FAILURE_CATEGORY_SET.has(String(rawFailure.category)) ||
      typeof rawFailure.message !== "string" ||
      typeof rawFailure.suggestion !== "string" ||
      typeof rawFailure.attemptCount !== "number" ||
      !Number.isInteger(rawFailure.attemptCount) ||
      rawFailure.attemptCount < 1 ||
      !isValidDateString(rawFailure.failedAt)
    ) {
      return null;
    }
    failure = {
      category: rawFailure.category as NonNullable<typeof failure>["category"],
      message: rawFailure.message,
      suggestion: rawFailure.suggestion,
      attemptCount: rawFailure.attemptCount,
      failedAt: rawFailure.failedAt,
    };
  }
  return {
    sequence: payload.sequence,
    role: payload.role,
    content: payload.content,
    createdAt: payload.createdAt ?? null,
    rendering: payload.rendering,
    ...(failure ? { failure } : {}),
  };
}

function parseAssistantConfirmationPayload(
  payload: Record<string, unknown>,
): AssistantConfirmationEvent["payload"] | null {
  if (
    typeof payload.requestId !== "string" ||
    !isAssistantConfirmationActionType(payload.actionType) ||
    typeof payload.sanitizedSummary !== "string" ||
    !isAssistantConfirmationStatus(payload.status) ||
    !isOptionalString(payload.sessionId) ||
    !isOptionalNullableString(payload.expiresAt) ||
    !isOptionalString(payload.affectedSkillId) ||
    !isOptionalNumber(payload.affectedEquipmentCount)
  ) {
    return null;
  }
  const affectedSpecialistNames = payload.affectedSpecialistNames;
  if (affectedSpecialistNames !== undefined && !isStringArray(affectedSpecialistNames)) return null;
  return {
    requestId: payload.requestId,
    sessionId: payload.sessionId,
    actionType: payload.actionType,
    sanitizedSummary: payload.sanitizedSummary,
    status: payload.status,
    expiresAt: payload.expiresAt,
    affectedSkillId: payload.affectedSkillId,
    affectedEquipmentCount: payload.affectedEquipmentCount,
    affectedSpecialistNames,
  };
}

function parseClarificationOption(value: unknown): ClarificationOptionPayload | null {
  if (!isRecord(value)) return null;
  if (typeof value.optionId !== "string" || typeof value.label !== "string") return null;
  if (!isOptionalNullableString(value.description) || !isOptionalNullableString(value.preview)) return null;
  return {
    optionId: value.optionId,
    label: value.label,
    description: (value.description ?? null) as string | null,
    preview: (value.preview ?? null) as string | null,
  };
}

function parseClarificationQuestion(value: unknown): ClarificationQuestionPayload | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.questionId !== "string" ||
    typeof value.question !== "string" ||
    typeof value.header !== "string" ||
    typeof value.multiSelect !== "boolean" ||
    !Array.isArray(value.options)
  ) {
    return null;
  }
  const options: ClarificationOptionPayload[] = [];
  for (const raw of value.options) {
    const option = parseClarificationOption(raw);
    if (!option) return null;
    options.push(option);
  }
  return {
    questionId: value.questionId,
    question: value.question,
    header: value.header,
    multiSelect: value.multiSelect,
    options,
  };
}

function parseClarificationRequestedPayload(
  payload: Record<string, unknown>,
): ClarificationRequestedEvent["payload"] | null {
  if (
    typeof payload.requestId !== "string" ||
    typeof payload.sessionId !== "string" ||
    payload.status !== "pending" ||
    !Array.isArray(payload.questions) ||
    !isOptionalNullableString(payload.expiresAt)
  ) {
    return null;
  }
  const questions: ClarificationQuestionPayload[] = [];
  for (const raw of payload.questions) {
    const question = parseClarificationQuestion(raw);
    if (!question) return null;
    questions.push(question);
  }
  return {
    requestId: payload.requestId,
    sessionId: payload.sessionId,
    questions,
    expiresAt: (payload.expiresAt ?? null) as string | null,
    status: "pending",
  };
}

function parseSkillChangedPayload(payload: Record<string, unknown>): SkillChangedEvent["payload"] | null {
  if (
    !isSkillChangedReason(payload.reason) ||
    !hasStringPayloadFields(payload, ["skillId", "chainRootId"]) ||
    !isOptionalNullableString(payload.newSkillId) ||
    !isOptionalSkillChangedCallerType(payload.callerType) ||
    !isOptionalNullableString(payload.callerId) ||
    (payload.bootstrapFallbackUsed !== undefined && typeof payload.bootstrapFallbackUsed !== "boolean")
  ) {
    return null;
  }
  let bootstrapFallbackInfo: SkillChangedEvent["payload"]["bootstrapFallbackInfo"];
  if (payload.bootstrapFallbackInfo === undefined) {
    bootstrapFallbackInfo = undefined;
  } else if (payload.bootstrapFallbackInfo === null) {
    bootstrapFallbackInfo = null;
  } else if (
    isRecord(payload.bootstrapFallbackInfo) &&
    isOptionalNullableString(payload.bootstrapFallbackInfo.reason) &&
    isOptionalNullableString(payload.bootstrapFallbackInfo.seedFilePath)
  ) {
    bootstrapFallbackInfo = {
      reason: payload.bootstrapFallbackInfo.reason ?? null,
      seedFilePath: payload.bootstrapFallbackInfo.seedFilePath ?? null,
    };
  } else {
    return null;
  }
  return {
    reason: payload.reason,
    skillId: payload.skillId as string,
    chainRootId: payload.chainRootId as string,
    newSkillId: payload.newSkillId ?? null,
    callerType: payload.callerType ?? null,
    callerId: payload.callerId ?? null,
    bootstrapFallbackUsed: payload.bootstrapFallbackUsed,
    bootstrapFallbackInfo,
  };
}

function parseSkillEquipmentChangedPayload(payload: Record<string, unknown>): SkillEquipmentChangedEvent["payload"] | null {
  if (
    !isSkillEquipmentChangeType(payload.changeType) ||
    !isSkillEquipmentEntityType(payload.entityType) ||
    !hasStringPayloadFields(payload, ["entityId", "skillId"]) ||
    !isOptionalNullableString(payload.unequippedReason)
  ) {
    return null;
  }
  return {
    changeType: payload.changeType,
    entityType: payload.entityType,
    entityId: payload.entityId as string,
    skillId: payload.skillId as string,
    unequippedReason: payload.unequippedReason ?? null,
  };
}

function parseTaskGraphChangedPayload(payload: Record<string, unknown>): TaskGraphChangedEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["graphId"]) ||
    !isTaskGraphChangeType(payload.changeType) ||
    !isOptionalNullableString(payload.taskId) ||
    !isOptionalTaskGraphStatus(payload.status) ||
    !isOptionalTaskGraphDisplayPhase(payload.displayPhase) ||
    (payload.requiresReview !== undefined &&
      payload.requiresReview !== null &&
      typeof payload.requiresReview !== "boolean") ||
    !isOptionalNullableString(payload.safeExplanation) ||
    !isOptionalTaskGraphSuspendReason(payload.suspendReason) ||
    !isOptionalNullableNumber(payload.sequence)
  ) {
    return null;
  }
  return {
    graphId: payload.graphId as string,
    taskId: payload.taskId ?? null,
    changeType: payload.changeType,
    status: payload.status ?? null,
    displayPhase: payload.displayPhase ?? null,
    requiresReview: payload.requiresReview ?? null,
    safeExplanation: payload.safeExplanation ?? null,
    suspendReason: payload.suspendReason ?? null,
    sequence: payload.sequence ?? null,
  };
}

function parseTaskBoardChangedPayload(payload: Record<string, unknown>): TaskBoardChangedEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["taskId"]) ||
    !isTaskBoardChangeType(payload.changeType) ||
    !isOptionalString(payload.graphId) ||
    !isOptionalString(payload.claimStatus) ||
    !isOptionalString(payload.updatedAt)
  ) {
    return null;
  }
  return {
    taskId: payload.taskId as string,
    graphId: payload.graphId,
    changeType: payload.changeType,
    claimStatus: payload.claimStatus,
    updatedAt: payload.updatedAt,
  };
}

function parseTaskQuestionChangedPayload(payload: Record<string, unknown>): TaskQuestionChangedEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["questionId", "taskId"]) ||
    !isTaskQuestionChangeType(payload.changeType) ||
    !isOptionalString(payload.graphId) ||
    !isOptionalTaskQuestionKind(payload.kind) ||
    !isOptionalTaskQuestionStatus(payload.status)
  ) {
    return null;
  }
  return {
    questionId: payload.questionId as string,
    taskId: payload.taskId as string,
    graphId: payload.graphId,
    kind: payload.kind,
    status: payload.status,
    changeType: payload.changeType,
  };
}

function parseMeetingChangedPayload(payload: Record<string, unknown>): MeetingChangedEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["channelId"]) ||
    !isMeetingChangeType(payload.changeType) ||
    !isOptionalString(payload.graphId) ||
    !isOptionalString(payload.taskId) ||
    !isOptionalNullableNumber(payload.sequence) ||
    !isOptionalString(payload.status)
  ) {
    return null;
  }
  return {
    channelId: payload.channelId as string,
    graphId: payload.graphId,
    taskId: payload.taskId,
    changeType: payload.changeType,
    sequence: payload.sequence,
    status: payload.status,
  };
}

function parseTodoChangedPayload(payload: Record<string, unknown>): TodoChangedEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["taskId", "todoId"]) ||
    !isTodoChangeType(payload.changeType) ||
    !isOptionalTodoStatus(payload.status) ||
    !isOptionalNumber(payload.sortOrder)
  ) {
    return null;
  }
  return {
    taskId: payload.taskId as string,
    todoId: payload.todoId as string,
    changeType: payload.changeType,
    status: payload.status,
    sortOrder: payload.sortOrder,
  };
}

export function parseUiEvent(value: unknown): UiEvent | null {
  if (!isRecord(value)) return null;
  const candidate = value as Partial<UiEventEnvelope>;
  const scope = parseScope(candidate.scope);
  if (
    typeof candidate.eventId !== "string" ||
    typeof candidate.sequence !== "number" ||
    !Number.isFinite(candidate.sequence) ||
    !Number.isInteger(candidate.sequence) ||
    candidate.sequence < 0 ||
    typeof candidate.sessionId !== "string" ||
    typeof candidate.type !== "string" ||
    !isUiEventType(candidate.type) ||
    scope === null ||
    !isRecord(candidate.payload)
  ) {
    return null;
  }
  const event = {
    eventId: candidate.eventId,
    sequence: candidate.sequence,
    sessionId: candidate.sessionId,
    causationId: candidate.causationId ?? null,
    type: candidate.type,
    scope,
    payload: candidate.payload,
    createdAt: typeof candidate.createdAt === "string" ? candidate.createdAt : new Date().toISOString(),
  };
  if (event.type === "assistant.message") {
    const payload = parseAssistantMessagePayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as AssistantMessageEvent;
  }
  if (event.type === "assistant.confirmation") {
    const payload = parseAssistantConfirmationPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as AssistantConfirmationEvent;
  }
  if (event.type === "assistant.clarification_requested") {
    const payload = parseClarificationRequestedPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as ClarificationRequestedEvent;
  }
  if (event.type === "assistant.clarification_resolved") {
    if (
      !hasStringPayloadFields(event.payload, ["requestId", "sessionId"]) ||
      !CLARIFICATION_RESOLVED_STATUS_SET.has(String(event.payload.status))
    ) {
      return null;
    }
    return event as ClarificationResolvedEvent;
  }
  if (event.type === "teaching.stage_changed") {
    if (!hasWorkflowScope(event) || !TEACHING_STAGE_SET.has(String(event.payload.stage))) return null;
    return event as TeachingStageChangedEvent;
  }
  if (event.type === "recording.progress" || event.type === "teaching.progress" || event.type === "trial.progress") {
    if (!hasWorkflowScope(event)) return null;
    if ((event.type === "teaching.progress" || event.type === "trial.progress") && typeof event.payload.status !== "string") {
      return null;
    }
    return event as RecordingProgressEvent | TeachingProgressEvent | TrialProgressEvent;
  }
  if (event.type === "trial.preview_requested") {
    if (
      !hasWorkflowScope(event) ||
      !hasStringPayloadFields(event.payload, ["requestId", "workflowId", "trialId", "summary", "codePreview", "riskSummary"]) ||
      event.payload.workflowId !== event.scope.workflowId ||
      !TRIAL_PREVIEW_REQUEST_STATUS_SET.has(String(event.payload.status)) ||
      !isValidDateString(event.payload.expires_at)
    ) {
      return null;
    }
    return event as TrialPreviewRequestedEvent;
  }
  if (event.type === "trial.preview_resolved") {
    if (
      !hasWorkflowScope(event) ||
      !hasStringPayloadFields(event.payload, ["requestId", "workflowId", "decision", "status"]) ||
      event.payload.workflowId !== event.scope.workflowId ||
      !TRIAL_PREVIEW_DECISION_SET.has(String(event.payload.decision)) ||
      !TRIAL_PREVIEW_RESOLUTION_STATUS_SET.has(String(event.payload.status))
    ) {
      return null;
    }
    return event as TrialPreviewResolvedEvent;
  }
  if (event.type === "backend.resync_required") {
    if (
      typeof event.payload.reason !== "string" ||
      (event.payload.domains !== undefined && !isStringArray(event.payload.domains))
    ) {
      return null;
    }
    return event as ResyncRequiredEvent;
  }
  if (event.type === "brain_zone_changed") {
    if (!hasStringPayloadFields(event.payload, ["zone", "changeType"])) return null;
    return event as BrainZoneChangedEvent;
  }
  if (event.type === "brain_specialist_recruited") {
    if (!hasStringPayloadFields(event.payload, ["specialistId", "name", "reason"])) return null;
    return event as BrainSpecialistRecruitedEvent;
  }
  if (event.type === "brain_specialist_changed") {
    if (!hasStringPayloadFields(event.payload, ["specialistId", "changeType"])) return null;
    return event as BrainSpecialistChangedEvent;
  }
  if (event.type === "brain_context_ready") {
    if (!hasStringPayloadFields(event.payload, ["sessionId"])) return null;
    return event as BrainContextReadyEvent;
  }
  if (event.type === "skill.changed") {
    const payload = parseSkillChangedPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as SkillChangedEvent;
  }
  if (event.type === "skill.equipment.changed") {
    const payload = parseSkillEquipmentChangedPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as SkillEquipmentChangedEvent;
  }
  if (event.type === "assistant.task_graph.changed") {
    if (typeof event.scope.sessionId !== "string") return null;
    const payload = parseTaskGraphChangedPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as TaskGraphChangedEvent;
  }
  if (event.type === "assistant.task_board.changed") {
    if (typeof event.scope.sessionId !== "string") return null;
    const payload = parseTaskBoardChangedPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as TaskBoardChangedEvent;
  }
  if (event.type === "assistant.task_question.changed") {
    if (typeof event.scope.sessionId !== "string") return null;
    const payload = parseTaskQuestionChangedPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as TaskQuestionChangedEvent;
  }
  if (event.type === "assistant.meeting.changed") {
    if (typeof event.scope.sessionId !== "string") return null;
    const payload = parseMeetingChangedPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as MeetingChangedEvent;
  }
  if (event.type === "assistant.todo.changed") {
    if (typeof event.scope.sessionId !== "string") return null;
    const payload = parseTodoChangedPayload(event.payload);
    if (!payload) return null;
    return { ...event, payload } as TodoChangedEvent;
  }
  return event as UiEvent;
}

export function parseEventFrame(frame: string): UiEvent | null {
  const data = frame
    .split("\n")
    .find((line) => line.startsWith("data: "))
    ?.slice(6);
  if (!data) return null;
  try {
    return parseUiEvent(JSON.parse(data));
  } catch {
    return null;
  }
}

export function getUiEventHandlerDomain(event: UiEvent): UiEventHandlerDomain {
  return UI_EVENT_HANDLER_DOMAINS[event.type];
}


export function isResyncRequiredEvent(event: UiEvent): event is ResyncRequiredEvent {
  return event.type === "backend.resync_required";
}

export type TeachingUiEvent =
  | RecordingProgressEvent
  | TeachingStageChangedEvent
  | TeachingProgressEvent
  | TrialProgressEvent
  | TrialPreviewRequestedEvent
  | TrialPreviewResolvedEvent;

export function isTeachingUiEvent(event: UiEvent): event is TeachingUiEvent {
  return getUiEventHandlerDomain(event) === "teaching";
}

export const PROGRESS_EVENT_TYPES = new Set<UiEventType>([
  "recording.progress",
  "teaching.progress",
  "trial.progress",
]);
