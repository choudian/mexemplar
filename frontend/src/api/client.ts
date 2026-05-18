import { invoke } from "@tauri-apps/api/core";

export type BackendStatus = "starting" | "ready" | "degraded" | "failed" | "shutting_down";
export type UiTheme = "light" | "dark" | "system" | "sage";
export type UiDensity = "compact" | "comfy";

export interface HealthCheck {
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
}

export interface UiEvent {
  eventId: string;
  type: string;
  scope: Record<string, string>;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface SidecarRuntimeConfig {
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
      };
      code = payload.error?.code ?? code;
      message = payload.error?.message ?? message;
      details = payload.error?.details ?? details;
    } catch {
      // Keep normalized fallback above.
    }
    throw new DesktopApiError(response.status, code, message, details);
  }

  return (await response.json()) as T;
}

export function getBootstrap(): Promise<BootstrapResponse> {
  return requestJson<BootstrapResponse>("/api/bootstrap");
}

const SSE_RETRY_DELAYS = [1000, 2000, 4000, 8000];
const SSE_MAX_RETRIES = 20;
const SSE_MAX_GRACEFUL_RECONNECTS = 50;

export async function connectEvents(
  onEvent: (event: UiEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let retryIndex = 0;
  let gracefulReconnects = 0;

  while (!signal?.aborted) {
    try {
      const response = await fetch(`${baseUrl}/api/events`, {
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
          const data = chunk
            .split("\n")
            .find((line) => line.startsWith("data: "))
            ?.slice(6);
          if (data) {
            onEvent(JSON.parse(data) as UiEvent);
          }
        }
      }

      if (signal?.aborted) return;
      if (gracefulReconnects >= SSE_MAX_GRACEFUL_RECONNECTS) return;
      await new Promise((resolve) => setTimeout(resolve, 500));
    } catch (err) {
      if (signal?.aborted) return;
      if (err instanceof DOMException && err.name === "AbortError") return;

      const delay = SSE_RETRY_DELAYS[Math.min(retryIndex, SSE_RETRY_DELAYS.length - 1)];
      retryIndex++;
      if (retryIndex >= SSE_MAX_RETRIES) return;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
}

