export const UI_EVENT_TYPES = [
  "assistant.message",
  "assistant.progress",
  "assistant.error",
  "assistant.confirmation",
  "recording.progress",
  "teaching.stage_changed",
  "teaching.progress",
  "trial.progress",
  "trial.preview_requested",
  "trial.preview_resolved",
  "skills.changed",
  "compositions.changed",
  "settings.changed",
  "brain_zone_changed",
  "brain_specialist_recruited",
  "brain_context_ready",
  "backend.resync_required",
] as const;

export type UiEventType = (typeof UI_EVENT_TYPES)[number];

export const UI_EVENT_EXAMPLES = {
  "assistant.message": { "sequence": 1, "role": "assistant", "content": "Ready.", "rendering": "safe_markdown" },
  "assistant.progress": { "status": "running", "headline": "Assistant is working" },
  "assistant.error": { "message": "Assistant failed to complete the request.", "type": "RuntimeError" },
  "assistant.confirmation": {
    "requestId": "req_1",
    "actionType": "exec",
    "sanitizedSummary": "命令首行: npm test",
    "status": "active",
  },
  "recording.progress": { "status": "recording", "message": "Recording started.", "recordingMode": "desktop" },
  "teaching.stage_changed": { "stage": "learning", "message": "Skill learning started." },
  "teaching.progress": { "status": "running", "headline": "Skill learning started" },
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
  "skills.changed": { "reason": "catalog_invalidated" },
  "compositions.changed": { "reason": "catalog_invalidated" },
  "settings.changed": { "reason": "settings_invalidated", "keys": [] },
  "brain_zone_changed": { "zone": "hot", "entryId": "entry_1", "changeType": "create" },
  "brain_specialist_recruited": {
    "specialistId": "spec_1",
    "name": "报表专员",
    "reason": "检测到持续报表委托",
    "managementUrl": "/brain/specialists",
  },
  "brain_context_ready": { "sessionId": "sess_1" },
  "backend.resync_required": { "reason": "replay_gap", "domains": ["teaching", "skills", "brain"] },
} as const satisfies Record<UiEventType, Record<string, unknown>>;

export const UI_EVENT_PAYLOAD_ENUMS = {
  "assistant.message": {
    "role": ["assistant", "user"],
    "rendering": ["plain_text", "safe_markdown"],
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
} as const satisfies Partial<Record<UiEventType, Record<string, readonly string[]>>>;

export type UiEventHandlerDomain =
  | "assistant"
  | "teaching"
  | "skills"
  | "compositions"
  | "settings"
  | "brain"
  | "resync";

export const UI_EVENT_HANDLER_DOMAINS = {
  "assistant.message": "assistant",
  "assistant.progress": "assistant",
  "assistant.error": "assistant",
  "assistant.confirmation": "assistant",
  "recording.progress": "teaching",
  "teaching.stage_changed": "teaching",
  "teaching.progress": "teaching",
  "trial.progress": "teaching",
  "trial.preview_requested": "teaching",
  "trial.preview_resolved": "teaching",
  "skills.changed": "skills",
  "compositions.changed": "compositions",
  "settings.changed": "settings",
  "brain_zone_changed": "brain",
  "brain_specialist_recruited": "brain",
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

export type BrainContextReadyEvent = UiEventEnvelope<
  "brain_context_ready",
  {
    sessionId: string;
  }
>;

export type UiEvent =
  | TeachingStageChangedEvent
  | RecordingProgressEvent
  | TeachingProgressEvent
  | TrialProgressEvent
  | TrialPreviewRequestedEvent
  | TrialPreviewResolvedEvent
  | ResyncRequiredEvent
  | BrainZoneChangedEvent
  | BrainSpecialistRecruitedEvent
  | BrainContextReadyEvent
  | UiEventEnvelope<
      Exclude<
        UiEventType,
        | "recording.progress"
        | "teaching.stage_changed"
        | "teaching.progress"
        | "trial.progress"
        | "trial.preview_requested"
        | "trial.preview_resolved"
        | "backend.resync_required"
        | "brain_zone_changed"
        | "brain_specialist_recruited"
        | "brain_context_ready"
      >
    >;

const UI_EVENT_TYPE_SET = new Set<string>(UI_EVENT_TYPES);
const TEACHING_STAGE_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["teaching.stage_changed"].stage);
const TRIAL_PREVIEW_REQUEST_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["trial.preview_requested"].status);
const TRIAL_PREVIEW_DECISION_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["trial.preview_resolved"].decision);
const TRIAL_PREVIEW_RESOLUTION_STATUS_SET = new Set<string>(UI_EVENT_PAYLOAD_ENUMS["trial.preview_resolved"].status);

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
  if (event.type === "brain_context_ready") {
    if (!hasStringPayloadFields(event.payload, ["sessionId"])) return null;
    return event as BrainContextReadyEvent;
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
