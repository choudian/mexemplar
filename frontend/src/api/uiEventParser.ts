import {
  UI_EVENT_HANDLER_DOMAINS,
  UI_EVENT_PAYLOAD_ENUMS,
  UI_EVENT_TYPES,
} from "./uiEventTypes";
import type {
  AssistantConfirmationActionType,
  AssistantConfirmationEvent,
  AssistantConfirmationStatus,
  AssistantMessageEvent,
  AssistantMessageRendering,
  AssistantMessageRole,
  BrainContextReadyEvent,
  BrainSpecialistChangedEvent,
  BrainSpecialistRecruitedEvent,
  BrainZoneChangedEvent,
  ClarificationOptionPayload,
  ClarificationQuestionPayload,
  ClarificationRequestedEvent,
  ClarificationResolvedEvent,
  ExternalCodingChangedEvent,
  ExternalCodingEventChangeType,
  ExternalCodingEventOwnerType,
  ExternalCodingEventPhase,
  ExternalCodingEventStatus,
  ExternalCodingEventTool,
  ImprovementProposalChangedEvent,
  MeetingChangeType,
  MeetingChangedEvent,
  RecordingProgressEvent,
  ResyncRequiredEvent,
  ScheduledTaskChangedEvent,
  ScheduledTaskChangeType,
  ScheduledTaskCompletedEvent,
  ScheduledTaskCompletedOutcome,
  ScheduledTaskNeedsTakeoverEvent,
  ScheduledTaskNeedsTakeoverReason,
  SchedulingConfirmationDraftPayload,
  SchedulingConfirmationRequestedEvent,
  SchedulingConfirmationResolvedEvent,
  SchedulingDraftKind,
  SchedulingDraftSource,
  SkillChangedCallerType,
  SkillChangedEvent,
  SkillChangedReason,
  SkillEquipmentChangedEvent,
  SkillEquipmentChangeType,
  SkillEquipmentEntityType,
  TaskBoardChangedEvent,
  TaskBoardChangeType,
  TaskGraphChangedEvent,
  TaskGraphChangeType,
  TaskGraphDisplayPhase,
  TaskGraphStatus,
  TaskGraphSuspendReason,
  TaskGraphWaitingOn,
  TaskQuestionChangedEvent,
  TaskQuestionChangeType,
  TaskQuestionKind,
  TaskQuestionStatus,
  TeachingStageChangedEvent,
  TeachingProgressEvent,
  TodoChangeType,
  TodoChangedEvent,
  TodoStatus,
  UserTaskChangeType,
  UserTaskChangedEvent,
  TrialPreviewRequestedEvent,
  TrialPreviewResolvedEvent,
  TrialProgressEvent,
  UiEvent,
  UiEventEnvelope,
  UiEventHandlerDomain,
  UiEventType,
} from "./uiEventTypes";
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
const TASK_GRAPH_WAITING_ON_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_graph.changed"].waitingOn);
const TASK_QUESTION_KIND_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_question.changed"].kind);
const TASK_QUESTION_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_question.changed"].status);
const TASK_QUESTION_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_question.changed"].changeType);
const TASK_BOARD_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.task_board.changed"].changeType);
const MEETING_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.meeting.changed"].changeType);
const TODO_CHANGE_TYPE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.todo.changed"].changeType);
const TODO_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["assistant.todo.changed"].status);
const EXTERNAL_CODING_OWNER_TYPE_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["assistant.external_coding.changed"].ownerType,
);
const EXTERNAL_CODING_TOOL_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["assistant.external_coding.changed"].tool,
);
const EXTERNAL_CODING_STATUS_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["assistant.external_coding.changed"].status,
);
const EXTERNAL_CODING_PHASE_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["assistant.external_coding.changed"].phase,
);
const EXTERNAL_CODING_CHANGE_TYPE_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["assistant.external_coding.changed"].changeType,
);
const IMPROVEMENT_PROPOSAL_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["improvement_proposal.changed"].status);
const IMPROVEMENT_PROPOSAL_CHANGE_TYPE_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["improvement_proposal.changed"].changeType,
);
const SCHEDULED_TASK_COMPLETED_OUTCOME_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["scheduled_task.completed"].outcome,
);
const SCHEDULED_TASK_NEEDS_TAKEOVER_REASON_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["scheduled_task.needs_takeover"].reason,
);
const SCHEDULED_TASK_CHANGE_TYPE_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["scheduled_task.changed"].changeType,
);
const SCHEDULING_CONFIRMATION_RESOLVED_STATUS_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["scheduling.confirmation_resolved"].status,
);
const SCHEDULING_DRAFT_KIND_SET = new Set<string>(["one_shot", "recurring"]);
const SCHEDULING_DRAFT_SOURCE_SET = new Set<string>(["direct", "todo"]);

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
const isExternalCodingOwnerType = makeEnumGuard<ExternalCodingEventOwnerType>(EXTERNAL_CODING_OWNER_TYPE_SET);
const isExternalCodingTool = makeEnumGuard<ExternalCodingEventTool>(EXTERNAL_CODING_TOOL_SET);
const isExternalCodingStatus = makeEnumGuard<ExternalCodingEventStatus>(EXTERNAL_CODING_STATUS_SET);
const isExternalCodingPhase = makeEnumGuard<ExternalCodingEventPhase>(EXTERNAL_CODING_PHASE_SET);
const isExternalCodingChangeType = makeEnumGuard<ExternalCodingEventChangeType>(EXTERNAL_CODING_CHANGE_TYPE_SET);
const isOptionalTaskGraphStatus = (v: unknown): v is TaskGraphStatus | null | undefined =>
  isOptionalNullableEnumMember<TaskGraphStatus>(TASK_GRAPH_STATUS_SET, v);
const isOptionalTaskGraphDisplayPhase = (v: unknown): v is TaskGraphDisplayPhase | null | undefined =>
  isOptionalNullableEnumMember<TaskGraphDisplayPhase>(TASK_GRAPH_DISPLAY_PHASE_SET, v);
const isOptionalTaskGraphSuspendReason = (v: unknown): v is TaskGraphSuspendReason | null | undefined =>
  isOptionalNullableEnumMember<TaskGraphSuspendReason>(TASK_GRAPH_SUSPEND_REASON_SET, v);
const isOptionalTaskGraphWaitingOn = (v: unknown): v is TaskGraphWaitingOn | null | undefined =>
  isOptionalNullableEnumMember<TaskGraphWaitingOn>(TASK_GRAPH_WAITING_ON_SET, v);
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
    !isOptionalTaskGraphWaitingOn(payload.waitingOn) ||
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
    waitingOn: payload.waitingOn ?? null,
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

const USER_TASK_CHANGE_TYPE_SET = new Set<string>(
  UI_EVENT_PAYLOAD_ENUMS["user_task.changed"].changeType,
);
const isUserTaskChangeType = makeEnumGuard<UserTaskChangeType>(USER_TASK_CHANGE_TYPE_SET);

function parseUserTaskChangedPayload(
  payload: Record<string, unknown>,
): UserTaskChangedEvent["payload"] | null {
  if (!hasStringPayloadFields(payload, ["userTaskId"]) || !isUserTaskChangeType(payload.changeType)) {
    return null;
  }
  return {
    userTaskId: payload.userTaskId as string,
    changeType: payload.changeType,
    sessionId: payload.sessionId as string | null | undefined,
  };
}

function parseExternalCodingChangedPayload(
  payload: Record<string, unknown>,
): ExternalCodingChangedEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["codingSessionId", "ownerId"]) ||
    !isExternalCodingOwnerType(payload.ownerType) ||
    !isExternalCodingTool(payload.tool) ||
    !isExternalCodingStatus(payload.status) ||
    !isExternalCodingPhase(payload.phase) ||
    !isExternalCodingChangeType(payload.changeType) ||
    !isOptionalNullableString(payload.sessionId) ||
    !isOptionalNullableString(payload.updatedAt)
  ) {
    return null;
  }
  return {
    codingSessionId: payload.codingSessionId as string,
    sessionId: payload.sessionId ?? null,
    ownerType: payload.ownerType,
    ownerId: payload.ownerId as string,
    tool: payload.tool,
    status: payload.status,
    phase: payload.phase,
    changeType: payload.changeType,
    updatedAt: payload.updatedAt ?? null,
  };
}

type ParsedUiEventCandidate = Omit<UiEventEnvelope<UiEventType, Record<string, unknown>>, "payload"> & {
  payload: Record<string, unknown>;
};

type UiEventMapper = (event: ParsedUiEventCandidate) => UiEvent | null;

function withParsedPayload<TEvent extends UiEvent>(
  event: ParsedUiEventCandidate,
  parsePayload: (payload: Record<string, unknown>) => TEvent["payload"] | null,
): TEvent | null {
  const payload = parsePayload(event.payload);
  if (!payload) return null;
  return { ...event, payload } as TEvent;
}

function parseClarificationResolvedEvent(event: ParsedUiEventCandidate): ClarificationResolvedEvent | null {
  if (
    !hasStringPayloadFields(event.payload, ["requestId", "sessionId"]) ||
    !CLARIFICATION_RESOLVED_STATUS_SET.has(String(event.payload.status))
  ) {
    return null;
  }
  return event as ClarificationResolvedEvent;
}

function parseTeachingStageChangedEvent(event: ParsedUiEventCandidate): TeachingStageChangedEvent | null {
  if (!hasWorkflowScope(event) || !TEACHING_STAGE_SET.has(String(event.payload.stage))) return null;
  return event as TeachingStageChangedEvent;
}

function parseProgressEvent(
  event: ParsedUiEventCandidate,
): RecordingProgressEvent | TeachingProgressEvent | TrialProgressEvent | null {
  if (!hasWorkflowScope(event)) return null;
  if ((event.type === "teaching.progress" || event.type === "trial.progress") && typeof event.payload.status !== "string") {
    return null;
  }
  return event as RecordingProgressEvent | TeachingProgressEvent | TrialProgressEvent;
}

function parseTrialPreviewRequestedEvent(event: ParsedUiEventCandidate): TrialPreviewRequestedEvent | null {
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

function parseTrialPreviewResolvedEvent(event: ParsedUiEventCandidate): TrialPreviewResolvedEvent | null {
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

function parseResyncRequiredEvent(event: ParsedUiEventCandidate): ResyncRequiredEvent | null {
  if (
    typeof event.payload.reason !== "string" ||
    (event.payload.domains !== undefined && !isStringArray(event.payload.domains))
  ) {
    return null;
  }
  return event as ResyncRequiredEvent;
}

function parseBrainZoneChangedEvent(event: ParsedUiEventCandidate): BrainZoneChangedEvent | null {
  if (!hasStringPayloadFields(event.payload, ["zone", "changeType"])) return null;
  return event as BrainZoneChangedEvent;
}

function parseBrainSpecialistRecruitedEvent(event: ParsedUiEventCandidate): BrainSpecialistRecruitedEvent | null {
  if (!hasStringPayloadFields(event.payload, ["specialistId", "name", "reason"])) return null;
  return event as BrainSpecialistRecruitedEvent;
}

function parseBrainSpecialistChangedEvent(event: ParsedUiEventCandidate): BrainSpecialistChangedEvent | null {
  if (!hasStringPayloadFields(event.payload, ["specialistId", "changeType"])) return null;
  return event as BrainSpecialistChangedEvent;
}

function parseBrainContextReadyEvent(event: ParsedUiEventCandidate): BrainContextReadyEvent | null {
  if (!hasStringPayloadFields(event.payload, ["sessionId"])) return null;
  return event as BrainContextReadyEvent;
}

function parseImprovementProposalChangedEvent(
  event: ParsedUiEventCandidate,
): ImprovementProposalChangedEvent | null {
  if (
    !hasStringPayloadFields(event.payload, ["proposalId", "sourceReviewId", "status", "changeType"]) ||
    !IMPROVEMENT_PROPOSAL_STATUS_SET.has(String(event.payload.status)) ||
    !IMPROVEMENT_PROPOSAL_CHANGE_TYPE_SET.has(String(event.payload.changeType)) ||
    !isOptionalNullableString(event.payload.severity)
  ) {
    return null;
  }
  const status = String(event.payload.status);
  const changeType = String(event.payload.changeType);
  if (!(changeType === "created" && status === "pending_review") && changeType !== status) {
    return null;
  }
  return event as ImprovementProposalChangedEvent;
}

function requireSessionScopedEvent<TEvent extends UiEvent>(
  event: ParsedUiEventCandidate,
  parsePayload: (payload: Record<string, unknown>) => TEvent["payload"] | null,
): TEvent | null {
  if (typeof event.scope.sessionId !== "string") return null;
  return withParsedPayload<TEvent>(event, parsePayload);
}

const isScheduledTaskCompletedOutcome = makeEnumGuard<ScheduledTaskCompletedOutcome>(
  SCHEDULED_TASK_COMPLETED_OUTCOME_SET,
);
const isScheduledTaskNeedsTakeoverReason = makeEnumGuard<ScheduledTaskNeedsTakeoverReason>(
  SCHEDULED_TASK_NEEDS_TAKEOVER_REASON_SET,
);
const isScheduledTaskChangeType = makeEnumGuard<ScheduledTaskChangeType>(SCHEDULED_TASK_CHANGE_TYPE_SET);
const isSchedulingDraftKind = makeEnumGuard<SchedulingDraftKind>(SCHEDULING_DRAFT_KIND_SET);
const isSchedulingDraftSource = makeEnumGuard<SchedulingDraftSource>(SCHEDULING_DRAFT_SOURCE_SET);

function parseScheduledTaskCompletedPayload(
  payload: Record<string, unknown>,
): ScheduledTaskCompletedEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["taskId", "runId", "sessionId", "outcome"]) ||
    !isScheduledTaskCompletedOutcome(payload.outcome) ||
    !isOptionalNullableString(payload.taskTitle) ||
    !isOptionalNullableString(payload.summary) ||
    !isOptionalNullableString(payload.failureReason)
  ) {
    return null;
  }
  return {
    taskId: payload.taskId as string,
    taskTitle: payload.taskTitle ?? null,
    runId: payload.runId as string,
    sessionId: payload.sessionId as string,
    outcome: payload.outcome,
    summary: payload.summary ?? null,
    failureReason: payload.failureReason ?? null,
  };
}

function parseScheduledTaskNeedsTakeoverPayload(
  payload: Record<string, unknown>,
): ScheduledTaskNeedsTakeoverEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["taskId", "runId", "sessionId", "reason"]) ||
    !isScheduledTaskNeedsTakeoverReason(payload.reason) ||
    !isOptionalNullableString(payload.taskTitle)
  ) {
    return null;
  }
  return {
    taskId: payload.taskId as string,
    taskTitle: payload.taskTitle ?? null,
    runId: payload.runId as string,
    sessionId: payload.sessionId as string,
    reason: payload.reason,
  };
}

function parseScheduledTaskChangedPayload(
  payload: Record<string, unknown>,
): ScheduledTaskChangedEvent["payload"] | null {
  if (!hasStringPayloadFields(payload, ["taskId"]) || !isScheduledTaskChangeType(payload.changeType)) {
    return null;
  }
  return {
    taskId: payload.taskId as string,
    changeType: payload.changeType,
  };
}

function parseSchedulingConfirmationDraft(value: unknown): SchedulingConfirmationDraftPayload | null {
  if (!isRecord(value)) return null;
  if (
    !hasStringPayloadFields(value, ["title", "scheduleDescription", "instruction"]) ||
    !isSchedulingDraftKind(value.scheduleKind) ||
    !isSchedulingDraftSource(value.sourceType)
  ) {
    return null;
  }
  return {
    title: value.title as string,
    scheduleDescription: value.scheduleDescription as string,
    instruction: value.instruction as string,
    scheduleKind: value.scheduleKind,
    sourceType: value.sourceType,
  };
}

function parseSchedulingConfirmationRequestedPayload(
  payload: Record<string, unknown>,
): SchedulingConfirmationRequestedEvent["payload"] | null {
  if (
    !hasStringPayloadFields(payload, ["requestId", "sessionId", "expiresAt"]) ||
    !isValidDateString(payload.expiresAt)
  ) {
    return null;
  }
  // status 默认 "pending"（contract 允许缺省；非 pending 一律拒绝）。
  if (payload.status !== undefined && payload.status !== "pending") return null;
  const draft = parseSchedulingConfirmationDraft(payload.draft);
  if (!draft) return null;
  if (payload.unattendedAutoApprove !== undefined && typeof payload.unattendedAutoApprove !== "boolean") {
    return null;
  }
  return {
    requestId: payload.requestId as string,
    sessionId: payload.sessionId as string,
    draft,
    unattendedAutoApprove: typeof payload.unattendedAutoApprove === "boolean" ? payload.unattendedAutoApprove : false,
    expiresAt: payload.expiresAt as string,
    status: "pending",
  };
}

function parseSchedulingConfirmationResolvedEvent(
  event: ParsedUiEventCandidate,
): SchedulingConfirmationResolvedEvent | null {
  if (
    !hasStringPayloadFields(event.payload, ["requestId", "sessionId"]) ||
    !SCHEDULING_CONFIRMATION_RESOLVED_STATUS_SET.has(String(event.payload.status))
  ) {
    return null;
  }
  return event as SchedulingConfirmationResolvedEvent;
}

const UI_EVENT_MAPPERS: Partial<Record<UiEventType, UiEventMapper>> = {
  "assistant.message": (event) => withParsedPayload<AssistantMessageEvent>(event, parseAssistantMessagePayload),
  "assistant.confirmation": (event) =>
    withParsedPayload<AssistantConfirmationEvent>(event, parseAssistantConfirmationPayload),
  "assistant.clarification_requested": (event) =>
    withParsedPayload<ClarificationRequestedEvent>(event, parseClarificationRequestedPayload),
  "assistant.clarification_resolved": parseClarificationResolvedEvent,
  "teaching.stage_changed": parseTeachingStageChangedEvent,
  "recording.progress": parseProgressEvent,
  "teaching.progress": parseProgressEvent,
  "trial.progress": parseProgressEvent,
  "trial.preview_requested": parseTrialPreviewRequestedEvent,
  "trial.preview_resolved": parseTrialPreviewResolvedEvent,
  "backend.resync_required": parseResyncRequiredEvent,
  "brain_zone_changed": parseBrainZoneChangedEvent,
  "brain_specialist_recruited": parseBrainSpecialistRecruitedEvent,
  "brain_specialist_changed": parseBrainSpecialistChangedEvent,
  "brain_context_ready": parseBrainContextReadyEvent,
  "improvement_proposal.changed": parseImprovementProposalChangedEvent,
  "skill.changed": (event) => withParsedPayload<SkillChangedEvent>(event, parseSkillChangedPayload),
  "skill.equipment.changed": (event) =>
    withParsedPayload<SkillEquipmentChangedEvent>(event, parseSkillEquipmentChangedPayload),
  "assistant.task_graph.changed": (event) =>
    requireSessionScopedEvent<TaskGraphChangedEvent>(event, parseTaskGraphChangedPayload),
  "assistant.task_board.changed": (event) =>
    requireSessionScopedEvent<TaskBoardChangedEvent>(event, parseTaskBoardChangedPayload),
  "assistant.task_question.changed": (event) =>
    requireSessionScopedEvent<TaskQuestionChangedEvent>(event, parseTaskQuestionChangedPayload),
  "assistant.meeting.changed": (event) =>
    requireSessionScopedEvent<MeetingChangedEvent>(event, parseMeetingChangedPayload),
  "assistant.todo.changed": (event) => requireSessionScopedEvent<TodoChangedEvent>(event, parseTodoChangedPayload),
  "user_task.changed": (event) => requireSessionScopedEvent<UserTaskChangedEvent>(event, parseUserTaskChangedPayload),
  "assistant.external_coding.changed": (event) =>
    requireSessionScopedEvent<ExternalCodingChangedEvent>(event, parseExternalCodingChangedPayload),
  "scheduled_task.completed": (event) =>
    withParsedPayload<ScheduledTaskCompletedEvent>(event, parseScheduledTaskCompletedPayload),
  "scheduled_task.needs_takeover": (event) =>
    withParsedPayload<ScheduledTaskNeedsTakeoverEvent>(event, parseScheduledTaskNeedsTakeoverPayload),
  "scheduled_task.changed": (event) =>
    withParsedPayload<ScheduledTaskChangedEvent>(event, parseScheduledTaskChangedPayload),
  "scheduling.confirmation_requested": (event) =>
    requireSessionScopedEvent<SchedulingConfirmationRequestedEvent>(
      event,
      parseSchedulingConfirmationRequestedPayload,
    ),
  "scheduling.confirmation_resolved": parseSchedulingConfirmationResolvedEvent,
};

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
  } satisfies ParsedUiEventCandidate;
  const mapper = UI_EVENT_MAPPERS[event.type];
  if (mapper) return mapper(event);
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

export type ScheduledUiEvent =
  | ScheduledTaskCompletedEvent
  | ScheduledTaskNeedsTakeoverEvent
  | ScheduledTaskChangedEvent
  | SchedulingConfirmationRequestedEvent
  | SchedulingConfirmationResolvedEvent;

export function isScheduledUiEvent(event: UiEvent): event is ScheduledUiEvent {
  return getUiEventHandlerDomain(event) === "scheduled";
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
