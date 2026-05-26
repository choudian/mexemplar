/**
 * Typed debug control/data REST client.
 *
 * All raw response data is kept in component memory state only.
 * Raw debug endpoints use Cache-Control: no-store.
 */

import { DesktopApiError, requestJson } from "./client";

export const DEBUG_RAW_STATE_PURGE_EVENT = "mexemplar:debug-raw-state-purge";
export const DEBUG_CONTROL_STATUS_EVENT = "mexemplar:debug-control-status";

export function dispatchDebugRawStatePurge(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(DEBUG_RAW_STATE_PURGE_EVENT));
}

export function dispatchDebugControlStatus(status: DebugControlStatus): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(DEBUG_CONTROL_STATUS_EVENT, { detail: status }));
}

async function debugFetch<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await requestJson<T>(path, init);
  } catch (error) {
    if (error instanceof DesktopApiError) {
      throw new DebugApiError(error.status, error.code, error.message);
    }
    throw error;
  }
}

export class DebugApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "DebugApiError";
  }
}

export interface DebugControlStatus {
  enabled: boolean;
  armedAt: string | null;
  retentionEpoch: string | null;
  warning: string;
  limits: {
    maxRecords: number;
    maxRecordBytes: number;
    maxTotalBytes: number;
  };
}

export interface TraceListItem {
  traceId: string;
  method: string;
  source: string;
  agentType: string | null;
  sessionId: string | null;
  workflowId: string | null;
  workUnitId: string | null;
  iteration: number | null;
  outcome: string;
  detailAvailability: string;
  retainedBytes: number;
  createdAt: string;
  completedAt: string | null;
  summary: string | null;
  linkedTransitionIds: string[];
}

export interface TraceListResponse {
  items: TraceListItem[];
  retainedBytes: number;
  omittedCount: number;
  warning: string;
}

export interface TraceDetail {
  traceId: string;
  method: string;
  source: string;
  agentType: string | null;
  sessionId: string | null;
  workflowId: string | null;
  workUnitId: string | null;
  iteration: number | null;
  inputMessages: unknown;
  inputMedia: unknown;
  inputTools: unknown;
  outputContent: string | null;
  outputToolCalls: unknown;
  outcome: string;
  errorSummary: string | null;
  detailAvailability: string;
  retainedBytes: number;
  linkedTransitionIds: string[];
  createdAt: string;
  completedAt: string | null;
}

export interface FlowListItem {
  workflowId: string;
  transitionCount: number;
  lastEventType: string;
  lastCreatedAt: string;
  linkedTraceCount: number;
}

export interface FlowListResponse {
  items: FlowListItem[];
}

export interface FlowTransitionView {
  transitionId: string;
  eventType: string;
  status: string;
  fromSession: { sessionId: string; agentType: string } | null;
  toSession: { sessionId: string; agentType: string } | null;
  reason: string | null;
  detail: unknown;
  detailProvenance: string;
  detailAvailability: string;
  traceIds: string[];
  linkStatus: string;
  createdAt: string;
}

export interface FlowDetailResponse {
  workflowId: string;
  transitions: FlowTransitionView[];
}

export interface ReferenceResponse {
  referenceId: string;
  content: string | null;
  available: boolean;
  truncated: boolean;
  nextChunk: string | null;
}

export interface DebugControlRequest {
  enabled: boolean;
  warningAcknowledged?: boolean;
}

export interface TraceListParams {
  source?: string;
  agentType?: string;
  sessionId?: string;
  workflowId?: string;
  limit?: number;
}

export interface FlowListParams {
  workflowId?: string;
  sessionId?: string;
  limit?: number;
}

export async function getControlStatus(): Promise<DebugControlStatus> {
  return debugFetch<DebugControlStatus>("/api/debug/control");
}

export async function updateControl(request: DebugControlRequest): Promise<DebugControlStatus> {
  return debugFetch<DebugControlStatus>("/api/debug/control", {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export async function listTraces(params?: TraceListParams): Promise<TraceListResponse> {
  const query = new URLSearchParams();
  if (params?.source) query.set("source", params.source);
  if (params?.agentType) query.set("agentType", params.agentType);
  if (params?.sessionId) query.set("sessionId", params.sessionId);
  if (params?.workflowId) query.set("workflowId", params.workflowId);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return debugFetch<TraceListResponse>(`/api/debug/traces${qs ? `?${qs}` : ""}`);
}

export async function getTraceDetail(traceId: string): Promise<TraceDetail> {
  return debugFetch<TraceDetail>(`/api/debug/traces/${encodeURIComponent(traceId)}`);
}

export async function clearTraces(): Promise<void> {
  await debugFetch<void>("/api/debug/traces", { method: "DELETE" });
}

export async function listFlows(params?: FlowListParams): Promise<FlowListResponse> {
  const query = new URLSearchParams();
  if (params?.workflowId) query.set("workflowId", params.workflowId);
  if (params?.sessionId) query.set("sessionId", params.sessionId);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return debugFetch<FlowListResponse>(`/api/debug/flows${qs ? `?${qs}` : ""}`);
}

export async function getFlowDetail(workflowId: string): Promise<FlowDetailResponse> {
  return debugFetch<FlowDetailResponse>(`/api/debug/flows/${encodeURIComponent(workflowId)}`);
}

export async function expandReference(referenceId: string): Promise<ReferenceResponse> {
  return debugFetch<ReferenceResponse>(`/api/debug/references/${encodeURIComponent(referenceId)}`);
}
