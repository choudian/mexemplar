import { afterEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi, connectEvents } from "../../src/api/client";
import {
  isResyncRequiredEvent,
  parseEventFrame,
  parseUiEvent,
  UI_EVENT_EXAMPLES,
  UI_EVENT_HANDLER_DOMAINS,
  UI_EVENT_PAYLOAD_ENUMS,
  UI_EVENT_TYPES,
} from "../../src/api/uiEvents";
import type { UiEventType } from "../../src/api/uiEvents";

function eventStreamResponse(frames: string[] = []): Response {
  const encoder = new TextEncoder();
  return {
    ok: true,
    body: new ReadableStream({
      start(controller) {
        if (frames.length > 0) {
          controller.enqueue(encoder.encode(frames.join("")));
        }
        controller.close();
      },
    }),
  } as Response;
}

const EXAMPLE_SCOPES: Partial<Record<UiEventType, Record<string, string>>> = {
  "assistant.message": { sessionId: "ast_1" },
  "assistant.progress": { sessionId: "ast_1" },
  "assistant.error": { sessionId: "ast_1" },
  "assistant.confirmation": { sessionId: "ast_1" },
  "recording.progress": { workflowId: "rec_1" },
  "teaching.stage_changed": { workflowId: "rec_1" },
  "teaching.progress": { workflowId: "rec_1" },
  "trial.progress": { workflowId: "rec_1" },
  "trial.preview_requested": { workflowId: "rec_1" },
  "trial.preview_resolved": { workflowId: "rec_1" },
};

function enveloped(type: UiEventType, payload: Record<string, unknown>, scope: Record<string, string> = {}) {
  return {
    eventId: `evt_${type}`,
    sequence: 1,
    sessionId: "ui_sess_1",
    type,
    scope,
    payload,
    createdAt: "2026-05-16T00:00:00Z",
  };
}

describe("uiEvents", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    configureDesktopApi({ baseUrl: "", sessionToken: "" });
  });

  test("parses registered enveloped events", () => {
    const event = parseUiEvent({
      eventId: "evt_1",
      sequence: 1,
      sessionId: "ui_sess_1",
      type: "teaching.stage_changed",
      scope: { workflowId: "rec_1" },
      payload: { stage: "learning" },
      createdAt: "2026-05-16T00:00:00Z",
    });

    expect(event?.type).toBe("teaching.stage_changed");
    expect(event?.sequence).toBe(1);
  });

  test("rejects unknown event types and invalid frames", () => {
    expect(parseUiEvent({ eventId: "evt_1", sequence: 1, sessionId: "ui_sess_1", type: "backend.event", payload: {} })).toBeNull();
    expect(parseEventFrame("event: settings.changed\ndata: {broken}\n")).toBeNull();
  });

  test("rejects invalid event sequence values", () => {
    expect(
      parseUiEvent({
        eventId: "evt_fractional",
        sequence: 1.5,
        sessionId: "ui_sess_1",
        type: "settings.changed",
        scope: {},
        payload: { reason: "settings_invalidated" },
        createdAt: "2026-05-16T00:00:00Z",
      }),
    ).toBeNull();
    expect(
      parseUiEvent({
        eventId: "evt_negative",
        sequence: -1,
        sessionId: "ui_sess_1",
        type: "settings.changed",
        scope: {},
        payload: { reason: "settings_invalidated" },
        createdAt: "2026-05-16T00:00:00Z",
      }),
    ).toBeNull();
  });

  test("rejects workflow events without a valid workflow scope", () => {
    expect(
      parseUiEvent({
        eventId: "evt_preview",
        sequence: 1,
        sessionId: "ui_sess_1",
        type: "trial.preview_requested",
        scope: {},
        payload: {
          requestId: "preview_1",
          workflowId: "rec_1",
          trialId: "trial_1",
          summary: "桌面试用需要确认。",
          codePreview: "print('safe preview')",
          riskSummary: "将控制本机桌面。",
          expires_at: "2026-05-16T00:00:30Z",
          status: "pending",
        },
        createdAt: "2026-05-16T00:00:00Z",
      }),
    ).toBeNull();
  });

  test("rejects malformed assistant message and confirmation payloads", () => {
    expect(
      parseUiEvent({
        eventId: "evt_bad_message",
        sequence: 1,
        sessionId: "ui_sess_1",
        type: "assistant.message",
        scope: { sessionId: "ast_1" },
        payload: {
          sequence: 1,
          role: "system",
          content: "bad role",
          createdAt: "2026-05-16T00:00:00Z",
          rendering: "safe_markdown",
        },
        createdAt: "2026-05-16T00:00:00Z",
      }),
    ).toBeNull();
    expect(
      parseUiEvent({
        eventId: "evt_bad_confirmation",
        sequence: 2,
        sessionId: "ui_sess_1",
        type: "assistant.confirmation",
        scope: { sessionId: "ast_1" },
        payload: {
          requestId: "req_1",
          actionType: "exec",
          sanitizedSummary: "命令首行: npm test",
          status: "pending",
        },
        createdAt: "2026-05-16T00:00:00Z",
      }),
    ).toBeNull();
  });

  test("connectEvents rejects invalid data frames and keeps session token out of the URL", async () => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "secret-token" });
    const fetchMock = vi.fn(async () => eventStreamResponse(["event: settings.changed\ndata: {broken}\n\n"]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(connectEvents(vi.fn())).rejects.toMatchObject({ code: "event_stream_parse_failed" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit | undefined];
    expect(String(url)).toBe("http://desktop.test/api/events");
    expect(String(url)).not.toContain("secret-token");
    expect((init?.headers as Record<string, string>)["X-Mexemplar-Session"]).toBe("secret-token");
  });

  test("detects resync-required events", () => {
    const event = parseUiEvent({
      eventId: "evt_resync",
      sequence: 2,
      sessionId: "ui_sess_1",
      type: "backend.resync_required",
      scope: {},
      payload: { reason: "replay_gap", domains: ["teaching"] },
      createdAt: "2026-05-16T00:00:01Z",
    });

    expect(event && isResyncRequiredEvent(event)).toBe(true);
  });

  test("frontend contract includes trial preview events", () => {
    expect(UI_EVENT_TYPES).toContain("trial.preview_requested");
    expect(UI_EVENT_TYPES).toContain("trial.preview_resolved");
  });

  test("parses skill.changed and rejects malformed methodology payloads", () => {
    const event = parseUiEvent(enveloped(
      "skill.changed",
      {
        reason: "supersede",
        skillId: "sk_1",
        chainRootId: "sk_root",
        newSkillId: "sk_2",
        callerType: "assistant",
        callerId: "ast_1",
      },
      { skillId: "sk_1" },
    ));

    if (event?.type !== "skill.changed") {
      throw new Error("Expected skill.changed event");
    }
    expect(event.payload.skillId).toBe("sk_1");
    expect(parseUiEvent(enveloped("skill.changed", { reason: "rename", skillId: "sk_1", chainRootId: "sk_root" }))).toBeNull();
    expect(parseUiEvent(enveloped("skill.changed", { reason: "create", skillId: "sk_1" }))).toBeNull();
    expect(parseUiEvent(enveloped("skill.changed", {
      reason: "create",
      skillId: "sk_1",
      chainRootId: "sk_root",
      callerType: "operator",
    }))).toBeNull();
  });

  test("parses skill.equipment.changed and rejects malformed equipment payloads", () => {
    const event = parseUiEvent(enveloped(
      "skill.equipment.changed",
      {
        changeType: "equipped",
        entityType: "specialist",
        entityId: "spec_1",
        skillId: "sk_1",
      },
      { entityId: "spec_1", skillId: "sk_1" },
    ));

    if (event?.type !== "skill.equipment.changed") {
      throw new Error("Expected skill.equipment.changed event");
    }
    expect(event.payload.entityId).toBe("spec_1");
    expect(parseUiEvent(enveloped("skill.equipment.changed", {
      changeType: "attached",
      entityType: "specialist",
      entityId: "spec_1",
      skillId: "sk_1",
    }))).toBeNull();
    expect(parseUiEvent(enveloped("skill.equipment.changed", {
      changeType: "equipped",
      entityType: "assistant",
      skillId: "sk_1",
    }))).toBeNull();
  });

  test("parses exported registry payload examples", () => {
    for (const [index, [type, payload]] of (Object.entries(UI_EVENT_EXAMPLES) as [UiEventType, Record<string, unknown>][]).entries()) {
      const event = parseUiEvent({
        eventId: `evt_example_${index}`,
        sequence: index + 1,
        sessionId: "ui_sess_1",
        type,
        scope: EXAMPLE_SCOPES[type] ?? {},
        payload,
        createdAt: "2026-05-16T00:00:00Z",
      });

      expect(event?.type).toBe(type);
    }
  });

  test("declares handler domains and enum values for every synced contract type", () => {
    expect(new Set(Object.keys(UI_EVENT_HANDLER_DOMAINS))).toEqual(new Set(UI_EVENT_TYPES));
    expect(UI_EVENT_PAYLOAD_ENUMS["teaching.stage_changed"].stage).toContain("trial_validation");
    expect(UI_EVENT_PAYLOAD_ENUMS["trial.preview_resolved"].status).toContain("timeout");
  });
});
