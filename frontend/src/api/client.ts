import { invoke } from "@tauri-apps/api/core";
import { parseEventFrame } from "./uiEvents";
import type { UiEvent } from "./uiEvents";

export type BackendStatus = "starting" | "ready" | "degraded" | "failed" | "shutting_down";
type UiTheme = "light" | "dark" | "system" | "sage";
type UiDensity = "compact" | "comfy";

interface HealthCheck {
  name: string;
  status: "ok" | "degraded" | "failed";
  message: string;
}

export interface BackendConnectionState {
  status: BackendStatus;
  message: string;
  checks: HealthCheck[];
  serverTime: string;
}

export interface BootstrapResponse {
  connection: BackendConnectionState;
  user: {
    displayName: string;
    statusLabel: string;
  };
  navigation: {
    pendingSkillCount: number;
    publishedSkillCount: number;
    failureCount: number;
    compositionCount: number;
  };
  settingsSummary: {
    theme: UiTheme;
    dark: boolean;
    density: UiDensity;
  };
  brain: {
    segmentIdleThresholdSeconds: number;
  };
}

export type { UiEvent } from "./uiEvents";

export type EventStreamCursor = { sequence: number; sessionId: string };

interface SidecarRuntimeConfig {
  baseUrl: string;
  port: number;
  sessionToken: string;
}

export class DesktopApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "DesktopApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let baseUrl = (import.meta.env.VITE_MEXEMPLAR_API_BASE_URL as string | undefined) ?? "";
let sessionToken = (import.meta.env.VITE_MEXEMPLAR_SESSION_TOKEN as string | undefined) ?? "";

export function configureDesktopApi(config: { baseUrl?: string; sessionToken?: string }): void {
  if (config.baseUrl !== undefined) {
    baseUrl = config.baseUrl.replace(/\/$/, "");
  }
  if (config.sessionToken !== undefined) {
    sessionToken = config.sessionToken;
  }
}

export async function configureDesktopApiFromTauri(): Promise<void> {
  try {
    const config = await invoke<SidecarRuntimeConfig>("get_sidecar_config");
    if (config?.baseUrl && config.sessionToken) {
      configureDesktopApi({
        baseUrl: config.baseUrl,
        sessionToken: config.sessionToken,
      });
    }
  } catch {
    // Browser dev and unit tests use Vite env/default fetch paths instead.
  }
}

export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(sessionToken ? { "X-Mexemplar-Session": sessionToken } : {}),
      ...init.headers,
    },
  });

  if (!response.ok) {
    let code = "desktop_api_error";
    let message = `Desktop API request failed with ${response.status}`;
    let details: Record<string, unknown> = {};
    try {
      const payload = (await response.json()) as {
        error?: { code?: string; message?: string; details?: Record<string, unknown> };
        detail?: string | Record<string, unknown>;
      };
      if (payload.error) {
        code = payload.error.code ?? code;
        message = payload.error.message ?? message;
        details = payload.error.details ?? details;
      } else if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (payload.detail && typeof payload.detail === "object") {
        const detail = payload.detail;
        code = typeof detail.error === "string"
          ? detail.error
          : typeof detail.code === "string"
            ? detail.code
            : code;
        message = typeof detail.message === "string" ? detail.message : message;
        details = { ...detail };
      }
    } catch {
      // Keep normalized fallback above.
    }
    throw new DesktopApiError(response.status, code, message, details);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new DesktopApiError(response.status, "parse_error", "响应内容解析失败");
  }
}

export function getBootstrap(): Promise<BootstrapResponse> {
  return requestJson<BootstrapResponse>("/api/bootstrap");
}

const SSE_RETRY_DELAYS = [1000, 2000, 4000, 8000];
const SSE_MAX_RETRIES = 20;
const SSE_MAX_GRACEFUL_RECONNECTS = 50;
const SSE_GRACEFUL_RECONNECT_DELAY_MS = 50;

export async function connectEvents(
  onEvent: (event: UiEvent) => void,
  { signal, cursor: initialCursor, onCursor }: {
    signal?: AbortSignal;
    cursor?: EventStreamCursor;
    onCursor?: (cursor: EventStreamCursor) => void;
  } = {},
): Promise<void> {
  let cursor = initialCursor;
  let retryIndex = 0;
  let gracefulReconnects = 0;
  let lastStreamError: unknown;

  while (!signal?.aborted) {
    try {
      const params = new URLSearchParams();
      if (cursor) {
        params.set("lastSeenSequence", String(cursor.sequence));
        params.set("eventSessionId", cursor.sessionId);
      }
      const query = params.toString();
      const suffix = query ? `?${query}` : "";
      const response = await fetch(`${baseUrl}/api/events${suffix}`, {
        headers: {
          ...(sessionToken ? { "X-Mexemplar-Session": sessionToken } : {}),
        },
        signal,
      });

      if (!response.ok || !response.body) {
        throw new DesktopApiError(response.status, "event_stream_failed", "Desktop event stream failed.");
      }

      retryIndex = 0;
      gracefulReconnects++;

      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      while (!signal?.aborted) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const event = parseEventFrame(chunk);
          if (!event) {
            const hasDataLine = chunk.split("\n").some((line) => line.startsWith("data:"));
            if (hasDataLine) {
              throw new DesktopApiError(
                0,
                "event_stream_parse_failed",
                "Desktop event stream delivered an invalid event.",
              );
            }
            continue;
          }
          cursor = { sequence: event.sequence, sessionId: event.sessionId };
          onCursor?.(cursor);
          onEvent(event);
        }
      }

      if (signal?.aborted) return;
      if (gracefulReconnects >= SSE_MAX_GRACEFUL_RECONNECTS) return;
      await new Promise((resolve) => setTimeout(resolve, SSE_GRACEFUL_RECONNECT_DELAY_MS));
    } catch (err) {
      if (signal?.aborted) return;
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (err instanceof DesktopApiError && err.code === "event_stream_parse_failed") {
        throw err;
      }
      lastStreamError = err;

      const delay = SSE_RETRY_DELAYS[Math.min(retryIndex, SSE_RETRY_DELAYS.length - 1)];
      retryIndex++;
      if (retryIndex >= SSE_MAX_RETRIES) {
        throw new DesktopApiError(0, "event_stream_retry_exhausted", "Desktop event stream retry limit reached.", {
          lastError: lastStreamError instanceof Error ? lastStreamError.name : typeof lastStreamError,
        });
      }
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
}
