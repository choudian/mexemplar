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
  "assistant.external_coding.changed",
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
  "improvement_proposal.changed",
  "scheduled_task.completed",
  "scheduled_task.needs_takeover",
  "scheduled_task.changed",
  "scheduling.confirmation_requested",
  "scheduling.confirmation_resolved",
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
  "assistant.external_coding.changed": {
    "codingSessionId": "ecs_123",
    "sessionId": "sess_1",
    "ownerType": "task",
    "ownerId": "tsk_1",
    "tool": "claude_code",
    "status": "plan_ready",
    "phase": "plan",
    "changeType": "plan_ready",
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
  "improvement_proposal.changed": { "proposalId": "prop_abc", "sourceReviewId": "rev_1", "status": "pending_review", "severity": "med", "changeType": "created" },
  "scheduled_task.completed": { "taskId": "sch_abc", "taskTitle": "查竞品价格", "runId": "schr_xyz", "sessionId": "ast_001", "outcome": "succeeded", "summary": "竞品 A 价格 99 元", "failureReason": null },
  "scheduled_task.needs_takeover": { "taskId": "sch_abc", "taskTitle": "查竞品价格", "runId": "schr_xyz", "sessionId": "ast_001", "reason": "needs_user_input" },
  "scheduled_task.changed": { "taskId": "sch_abc", "changeType": "created" },
  "scheduling.confirmation_requested": { "requestId": "scf_abc", "sessionId": "ast_001", "draft": { "title": "查竞品价格", "scheduleDescription": "每天 09:00", "instruction": "查询竞品价格并汇总", "scheduleKind": "recurring", "sourceType": "direct" }, "unattendedAutoApprove": false, "expiresAt": "2026-07-19T12:00:00+00:00" },
  "scheduling.confirmation_resolved": { "requestId": "scf_abc", "sessionId": "ast_001", "status": "confirmed" },
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
  "assistant.external_coding.changed": {
    "ownerType": ["task", "workflow"],
    "tool": ["claude_code", "codex_cli"],
    "status": [
      "abandoned",
      "completed",
      "created",
      "failed",
      "implementing",
      "interrupted",
      "merge_blocked",
      "merge_ready",
      "merged",
      "plan_approved",
      "plan_ready",
      "plan_rejected",
      "planning",
      "rollback_proposed",
      "rolled_back",
      "waiting_user",
    ],
    "phase": ["done", "implement", "merge", "plan", "rollback"],
    "changeType": [
      "abandoned",
      "completed",
      "created",
      "merge_analysis",
      "merge_failed",
      "merged",
      "missing_artifact",
      "plan_approved",
      "plan_invalid",
      "plan_ready",
      "plan_rejected",
      "protocol_violation",
      "result_invalid",
      "resumed",
      "review_recorded",
      "rollback_failed",
      "rollback_proposed",
      "rolled_back",
      "start_failed",
      "waiting_user",
    ],
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
  "improvement_proposal.changed": {
    "status": ["approved", "done", "failed", "in_progress", "pending_review", "rejected"],
    "changeType": ["approved", "created", "done", "failed", "in_progress", "rejected"],
  },
  "scheduled_task.completed": {
    "outcome": ["failed", "succeeded"],
  },
  "scheduled_task.needs_takeover": {
    "reason": ["failed_takeover", "needs_user_input"],
  },
  "scheduled_task.changed": {
    "changeType": ["created", "deleted", "fired", "paused", "resumed", "status_changed"],
  },
  "scheduling.confirmation_resolved": {
    "status": ["cancelled", "confirmed", "shutdown", "stopped", "timeout"],
  },
  "scheduling.confirmation_requested": {
    "status": ["pending"],
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
  | "scheduled"
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
  "assistant.external_coding.changed": "assistant",
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
  "improvement_proposal.changed": "brain",
  "scheduled_task.completed": "scheduled",
  "scheduled_task.needs_takeover": "scheduled",
  "scheduled_task.changed": "scheduled",
  "scheduling.confirmation_requested": "scheduled",
  "scheduling.confirmation_resolved": "scheduled",
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

export type AssistantMessageRole = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.message"]["role"][number];
export type AssistantMessageRendering = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.message"]["rendering"][number];
export type AssistantConfirmationActionType =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.confirmation"]["actionType"][number];
export type AssistantConfirmationStatus = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.confirmation"]["status"][number];

export interface UiEventEnvelope<TType extends UiEventType = UiEventType, TPayload = Record<string, unknown>> {
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

export type TeachingStageChangedEvent = UiEventEnvelope<
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

export type RecordingProgressEvent = UiEventEnvelope<
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

export type TeachingProgressEvent = UiEventEnvelope<
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

export type TrialProgressEvent = UiEventEnvelope<
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

export type TrialPreviewResolvedEvent = UiEventEnvelope<
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

export type ImprovementProposalChangedEvent = UiEventEnvelope<
  "improvement_proposal.changed",
  {
    proposalId: string;
    sourceReviewId: string;
    status: "pending_review" | "approved" | "in_progress" | "done" | "failed" | "rejected";
    severity: string | null;
    changeType: "created" | "approved" | "rejected" | "in_progress" | "done" | "failed";
  }
>;

export type ScheduledTaskCompletedOutcome =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["scheduled_task.completed"]["outcome"][number];
export type ScheduledTaskNeedsTakeoverReason =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["scheduled_task.needs_takeover"]["reason"][number];
export type ScheduledTaskChangeType =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["scheduled_task.changed"]["changeType"][number];
export type SchedulingConfirmationStatus =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["scheduling.confirmation_resolved"]["status"][number];
export type SchedulingConfirmationRequestStatus =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["scheduling.confirmation_requested"]["status"][number];
export type SchedulingDraftKind = "one_shot" | "recurring";
export type SchedulingDraftSource = "direct" | "todo";

export interface SchedulingConfirmationDraftPayload {
  title: string;
  scheduleDescription: string;
  instruction: string;
  scheduleKind: SchedulingDraftKind;
  sourceType: SchedulingDraftSource;
}

export type ScheduledTaskCompletedEvent = UiEventEnvelope<
  "scheduled_task.completed",
  {
    taskId: string;
    taskTitle?: string | null;
    runId: string;
    sessionId: string;
    outcome: ScheduledTaskCompletedOutcome;
    summary?: string | null;
    failureReason?: string | null;
  }
>;

export type ScheduledTaskNeedsTakeoverEvent = UiEventEnvelope<
  "scheduled_task.needs_takeover",
  {
    taskId: string;
    taskTitle?: string | null;
    runId: string;
    sessionId: string;
    reason: ScheduledTaskNeedsTakeoverReason;
  }
>;

export type ScheduledTaskChangedEvent = UiEventEnvelope<
  "scheduled_task.changed",
  {
    taskId: string;
    changeType: ScheduledTaskChangeType;
  }
>;

export type SchedulingConfirmationRequestedEvent = UiEventEnvelope<
  "scheduling.confirmation_requested",
  {
    requestId: string;
    sessionId: string;
    draft: SchedulingConfirmationDraftPayload;
    unattendedAutoApprove?: boolean;
    expiresAt: string;
    status: SchedulingConfirmationRequestStatus;
  }
>;

export type SchedulingConfirmationResolvedEvent = UiEventEnvelope<
  "scheduling.confirmation_resolved",
  {
    requestId: string;
    sessionId: string;
    status: SchedulingConfirmationStatus;
  }
>;

export type SkillChangedReason = (typeof UI_EVENT_PAYLOAD_ENUMS)["skill.changed"]["reason"][number];
export type SkillChangedCallerType = (typeof UI_EVENT_PAYLOAD_ENUMS)["skill.changed"]["callerType"][number];
export type SkillEquipmentChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["skill.equipment.changed"]["changeType"][number];
export type SkillEquipmentEntityType = (typeof UI_EVENT_PAYLOAD_ENUMS)["skill.equipment.changed"]["entityType"][number];
export type TaskBoardChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_board.changed"]["changeType"][number];
export type TaskGraphChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_graph.changed"]["changeType"][number];
export type TaskGraphStatus = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_graph.changed"]["status"][number];
export type TaskGraphDisplayPhase = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_graph.changed"]["displayPhase"][number];
export type TaskGraphSuspendReason = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_graph.changed"]["suspendReason"][number];
export type TaskQuestionKind = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_question.changed"]["kind"][number];
export type TaskQuestionStatus = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_question.changed"]["status"][number];
export type TaskQuestionChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.task_question.changed"]["changeType"][number];
export type MeetingChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.meeting.changed"]["changeType"][number];
export type TodoChangeType = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.todo.changed"]["changeType"][number];
export type TodoStatus = (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.todo.changed"]["status"][number];
export type ExternalCodingEventOwnerType =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.external_coding.changed"]["ownerType"][number];
export type ExternalCodingEventTool =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.external_coding.changed"]["tool"][number];
export type ExternalCodingEventStatus =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.external_coding.changed"]["status"][number];
export type ExternalCodingEventPhase =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.external_coding.changed"]["phase"][number];
export type ExternalCodingEventChangeType =
  (typeof UI_EVENT_PAYLOAD_ENUMS)["assistant.external_coding.changed"]["changeType"][number];

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

export type ExternalCodingChangedEvent = UiEventEnvelope<
  "assistant.external_coding.changed",
  {
    codingSessionId: string;
    sessionId?: string | null;
    ownerType: ExternalCodingEventOwnerType;
    ownerId: string;
    tool: ExternalCodingEventTool;
    status: ExternalCodingEventStatus;
    phase: ExternalCodingEventPhase;
    changeType: ExternalCodingEventChangeType;
    updatedAt?: string | null;
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
  | ImprovementProposalChangedEvent
  | SkillChangedEvent
  | SkillEquipmentChangedEvent
  | TaskBoardChangedEvent
  | TaskGraphChangedEvent
  | TaskQuestionChangedEvent
  | MeetingChangedEvent
  | TodoChangedEvent
  | ExternalCodingChangedEvent
  | ScheduledTaskCompletedEvent
  | ScheduledTaskNeedsTakeoverEvent
  | ScheduledTaskChangedEvent
  | SchedulingConfirmationRequestedEvent
  | SchedulingConfirmationResolvedEvent
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
        | "assistant.external_coding.changed"
        | "scheduled_task.completed"
        | "scheduled_task.needs_takeover"
        | "scheduled_task.changed"
        | "scheduling.confirmation_requested"
        | "scheduling.confirmation_resolved"
      >
    >;
