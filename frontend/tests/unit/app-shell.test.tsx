import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { invoke } from "@tauri-apps/api/core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AppShell } from "../../src/app/AppShell";
import { useAssistantStore } from "../../src/state/assistantStore";
import { useSkillsStore } from "../../src/state/skillsStore";
import { useShellStore } from "../../src/state/shellStore";
import { useTeachingStore } from "../../src/state/teachingStore";

const bootstrapPayload = {
  connection: {
    status: "ready",
    message: "Desktop backend is ready.",
    checks: [],
    serverTime: "2026-05-10T00:00:00Z",
  },
  user: {
    displayName: "本地用户",
    statusLabel: "本地版 · 已就绪",
  },
  navigation: {
    pendingSkillCount: 1,
    publishedSkillCount: 2,
    failureCount: 0,
    compositionCount: 3,
  },
  settingsSummary: {
    theme: "sage",
    dark: false,
    density: "comfy",
  },
  brain: {
    segmentIdleThresholdSeconds: 123,
  },
};

const PRIMARY_ROUTE_EXPECTATIONS = [
  { label: "技能教学", namePattern: /技能教学/ },
  { label: "技能列表", namePattern: /技能列表/ },
  { label: "技能组合", namePattern: /技能组合/ },
  { label: "大脑管理", namePattern: /大脑管理/ },
  { label: "专员管理", namePattern: /专员管理/ },
  { label: "应用设置", namePattern: /应用设置/ },
] as const;

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    json: async () => payload,
  } as Response;
}

function eventFrame(event: Record<string, unknown>): string {
  return `id: ${event.sessionId}:${event.sequence}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

function eventStreamResponse(frames: string[] = [], options?: { close?: boolean }): Response {
  const encoder = new TextEncoder();
  return {
    ok: true,
    body: new ReadableStream({
      start(controller) {
        if (frames.length > 0) {
          controller.enqueue(encoder.encode(frames.join("")));
        }
        if (options?.close) {
          controller.close();
        }
      },
    }),
  } as Response;
}

describe("AppShell", () => {
  beforeEach(() => {
    useShellStore.setState({
      activeRoute: "assistant",
      backend: null,
      userDisplayName: "本地用户",
      userStatusLabel: "本地版 · 启动中",
      navigation: {
        pendingSkillCount: 0,
        publishedSkillCount: 0,
        failureCount: 0,
        compositionCount: 0,
      },
    });
    useAssistantStore.getState().clearIdleTimer();
    useAssistantStore.setState({
      hydrated: false,
      sessions: [],
      activeSessionId: null,
      messages: [],
      query: "",
      draft: "",
      loadingSessions: false,
      loadingMessages: false,
      sending: false,
      hasMoreBefore: false,
      nextBeforeSequence: null,
      progress: { status: "idle", headline: "" },
      confirmations: [],
      lastError: null,
      idleThresholdMs: null,
    });
    useTeachingStore.setState({
      hydrated: false,
      readiness: [],
      selectedMode: null,
      run: null,
      stage: "selecting",
      progressLog: [],
      messages: [],
      toast: null,
      trialPreview: null,
      busy: false,
      lastError: null,
      skillTrialToolId: null,
      trialSuccessCount: 0,
    });
    useSkillsStore.setState({
      hydrated: false,
      activeCategory: "pending",
      query: "",
      categories: { pending: [], published: [], failed: [] },
      counts: { pending: 0, published: 0, failed: 0 },
      busy: false,
      lastError: null,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/events")) {
          return eventStreamResponse();
        }
        if (url.endsWith("/api/settings/schema")) {
          return jsonResponse({
            sections: [
              {
                id: "ai",
                label: "AI",
                items: [],
                actions: [],
              },
            ],
          });
        }
        if (url.endsWith("/api/settings/values")) {
          return jsonResponse({ values: {}, secrets: {}, status: {} });
        }
        if (url.endsWith("/api/brain/zones")) {
          return jsonResponse({ zones: [{ zone: "hot", label: "热区", entry_count: 1, fading_count: 0 }] });
        }
        if (url.includes("/api/brain/zones/hot/entries")) {
          return jsonResponse({
            items: [
              {
                entry_id: "entry-1",
                zone: "hot",
                entry_type: "insight",
                content: "用户偏好简洁回复",
                status: "active",
                origin: "distillation",
                reason: "对话沉淀",
                scope: "沟通",
                loaded_count: 1,
                referenced_count: 0,
                superseded_by: null,
                verification_checkpoint: null,
                verification_status: null,
                verification_rationale: null,
                created_at: null,
                updated_at: null,
              },
            ],
            total: 1,
            limit: 50,
            offset: 0,
          });
        }
        if (url.includes("/api/brain/segments")) {
          return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 });
        }
        if (url.endsWith("/api/brain/skill-pool")) {
          return jsonResponse({ skills: [{ tool_id: "tool-1", name: "报表分析", description: "分析报表" }] });
        }
        if (url.includes("/api/brain/entries/entry-1/evolution")) {
          return jsonResponse({ chain: [] });
        }
        if (url.includes("/api/brain/specialists")) {
          return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
        }
        return jsonResponse(bootstrapPayload);
      }),
    );
    vi.mocked(invoke).mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("hydrates backend status and navigates five primary routes", async () => {
    render(<AppShell />);

    await waitFor(() => expect(screen.getByText("已就绪")).toBeInTheDocument());
    const navigation = screen.getByRole("navigation", { name: "主导航" });
    expect(navigation).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI 助手" })).toBeInTheDocument();

    for (const route of PRIMARY_ROUTE_EXPECTATIONS) {
      fireEvent.click(within(navigation).getByRole("button", { name: route.namePattern }));
      expect(screen.getByRole("heading", { name: route.label })).toBeInTheDocument();
    }
    await waitFor(() => expect(screen.getByRole("tab", { name: "AI" })).toBeInTheDocument());
  });

  test("retries bootstrap while the sidecar is still starting", async () => {
    let bootstrapAttempts = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/events")) {
        return eventStreamResponse();
      }
      if (url.endsWith("/api/bootstrap")) {
        bootstrapAttempts += 1;
        if (bootstrapAttempts === 1) {
          throw new TypeError("sidecar not ready");
        }
        return jsonResponse(bootstrapPayload);
      }
      return jsonResponse(bootstrapPayload);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AppShell />);

    await waitFor(() => expect(screen.getByText("已就绪")).toBeInTheDocument());
    expect(bootstrapAttempts).toBe(2);
  });

  test("exposes branded custom window controls with accessible names", async () => {
    render(<AppShell />);

    await waitFor(() => expect(screen.getByText("已就绪")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "关闭窗口" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "最小化窗口" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "最大化或还原窗口" })).toBeInTheDocument();
  });

  test("close control seals the active assistant segment before closing the window", async () => {
    useAssistantStore.setState({ activeSessionId: "ast_active" });
    const fetchMock = vi.mocked(fetch);

    render(<AppShell />);

    await waitFor(() => expect(screen.getByText("已就绪")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "关闭窗口" }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input, init]) => {
        const url = String(input);
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
        return (
          url.endsWith("/api/assistant/segment-boundary")
          && body.session_id === "ast_active"
          && body.reason === "window_close"
        );
      })).toBe(true),
    );
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("close"));
  });

  test("dispatches teaching stage and trial preview events from the event stream", async () => {
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "desktop", stage: "learning", summary: {} },
      selectedMode: "desktop",
      stage: "learning",
    });
    const streamFrames = [
      eventFrame({
        eventId: "evt_stage",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: "rec_1",
        type: "teaching.stage_changed",
        scope: { workflowId: "rec_1" },
        payload: { stage: "trial_validation", headline: "Skill learning completed" },
        createdAt: "2026-05-10T00:00:00Z",
      }),
      eventFrame({
        eventId: "evt_preview",
        sequence: 2,
        sessionId: "ui_sess_test",
        causationId: "rec_1",
        type: "trial.preview_requested",
        scope: { workflowId: "rec_1" },
        payload: {
          requestId: "preview_1",
          workflowId: "rec_1",
          trialId: "trial_1",
          summary: "桌面试用需要确认。",
          codePreview: "print('safe preview')",
          riskSummary: "将控制本机桌面。",
          expires_at: "2099-05-10T00:00:00Z",
          status: "pending",
        },
        createdAt: "2026-05-10T00:00:01Z",
      }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/events")) {
          return eventStreamResponse(streamFrames);
        }
        return jsonResponse(bootstrapPayload);
      }),
    );

    render(<AppShell />);

    await waitFor(() => expect(useTeachingStore.getState().stage).toBe("trial_validation"));
    await waitFor(() => expect(screen.getByText("技能学习完成")).toBeInTheDocument());
    expect(screen.getByText("可以开始试用验证，确认它能按预期执行。")).toBeInTheDocument();
    await waitFor(() => expect(useTeachingStore.getState().trialPreview?.requestId).toBe("preview_1"));
  });

  test("ignores duplicate event ids before they create duplicate display entries", async () => {
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "desktop", stage: "learning", summary: {} },
      selectedMode: "desktop",
      stage: "learning",
      progressLog: [],
    });
    const duplicateEvent = {
      eventId: "evt_duplicate_progress",
      sequence: 1,
      sessionId: "ui_sess_test",
      causationId: "rec_1",
      type: "teaching.progress",
      scope: { workflowId: "rec_1" },
      payload: { status: "running", headline: "Skill learning update" },
      createdAt: "2026-05-10T00:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/events")) {
          return eventStreamResponse([
            eventFrame(duplicateEvent),
            eventFrame({ ...duplicateEvent, sequence: 2 }),
          ]);
        }
        return jsonResponse(bootstrapPayload);
      }),
    );

    render(<AppShell />);

    await waitFor(() => expect(useTeachingStore.getState().progressLog).toEqual(["Skill learning update"]));
  });

  test("applies events that arrive after resync only after authoritative refresh completes", async () => {
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "browser", stage: "recording", summary: {} },
      selectedMode: "browser",
      stage: "recording",
    });
    let resolveRun: () => void = () => {};
    const runRefresh = new Promise<Response>((resolve) => {
      resolveRun = () =>
        resolve(
          jsonResponse({
            workflowId: "rec_1",
            mode: "browser",
            stage: "learning",
            summary: {},
          }),
        );
    });
    const streamFrames = [
      eventFrame({
        eventId: "evt_resync",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: null,
        type: "backend.resync_required",
        scope: {},
        payload: { reason: "replay_gap", domains: ["teaching"], eventSessionId: "ui_sess_test" },
        createdAt: "2026-05-10T00:00:00Z",
      }),
      eventFrame({
        eventId: "evt_stage",
        sequence: 2,
        sessionId: "ui_sess_test",
        causationId: "rec_1",
        type: "teaching.stage_changed",
        scope: { workflowId: "rec_1" },
        payload: { stage: "published", headline: "Skill published" },
        createdAt: "2026-05-10T00:00:01Z",
      }),
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/events")) return eventStreamResponse(streamFrames);
      if (url.endsWith("/api/teaching/runs/rec_1")) return runRefresh;
      if (url.endsWith("/api/skills?category=pending")) return jsonResponse({ category: "pending", count: 0, items: [] });
      if (url.endsWith("/api/skills?category=published")) return jsonResponse({ category: "published", count: 0, items: [] });
      if (url.endsWith("/api/skills?category=failed")) return jsonResponse({ category: "failed", count: 0, items: [] });
      if (url.endsWith("/api/compositions")) return jsonResponse({ items: [] });
      if (url.endsWith("/api/settings/schema")) return jsonResponse({ sections: [] });
      if (url.endsWith("/api/settings/values")) return jsonResponse({ values: {}, secrets: {}, status: {} });
      return jsonResponse(bootstrapPayload);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AppShell />);

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/teaching/runs/rec_1"))).toBe(true),
    );
    expect(useTeachingStore.getState().stage).toBe("recording");

    resolveRun();

    await waitFor(() => expect(useTeachingStore.getState().stage).toBe("published"));
  });

  test("does not apply incremental events after a failed authoritative resync", async () => {
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "browser", stage: "recording", summary: {} },
      selectedMode: "browser",
      stage: "recording",
    });
    const streamFrames = [
      eventFrame({
        eventId: "evt_resync_failed",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: null,
        type: "backend.resync_required",
        scope: {},
        payload: { reason: "replay_gap", domains: ["teaching"], eventSessionId: "ui_sess_test" },
        createdAt: "2026-05-10T00:00:00Z",
      }),
      eventFrame({
        eventId: "evt_stage_after_failed_resync",
        sequence: 2,
        sessionId: "ui_sess_test",
        causationId: "rec_1",
        type: "teaching.stage_changed",
        scope: { workflowId: "rec_1" },
        payload: { stage: "published", headline: "Skill published" },
        createdAt: "2026-05-10T00:00:01Z",
      }),
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/events")) return eventStreamResponse(streamFrames);
      if (url.endsWith("/api/teaching/runs/rec_1")) throw new Error("refresh failed");
      if (url.endsWith("/api/skills?category=pending")) return jsonResponse({ category: "pending", count: 0, items: [] });
      if (url.endsWith("/api/skills?category=published")) return jsonResponse({ category: "published", count: 0, items: [] });
      if (url.endsWith("/api/skills?category=failed")) return jsonResponse({ category: "failed", count: 0, items: [] });
      if (url.endsWith("/api/compositions")) return jsonResponse({ items: [] });
      if (url.endsWith("/api/settings/schema")) return jsonResponse({ sections: [] });
      if (url.endsWith("/api/settings/values")) return jsonResponse({ values: {}, secrets: {}, status: {} });
      return jsonResponse(bootstrapPayload);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AppShell />);

    await waitFor(() => expect(useShellStore.getState().backend?.status).toBe("degraded"));
    expect(useTeachingStore.getState().stage).toBe("recording");
  });

  test("reconnects event stream with the last seen cursor", async () => {
    const eventUrls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/events")) {
        eventUrls.push(url);
        if (eventUrls.length === 1) {
          return eventStreamResponse([
            eventFrame({
              eventId: "evt_settings",
              sequence: 1,
              sessionId: "ui_sess_test",
              causationId: null,
              type: "settings.changed",
              scope: {},
              payload: { reason: "settings_invalidated", keys: ["theme"] },
              createdAt: "2026-05-10T00:00:00Z",
            }),
          ], { close: true });
        }
        return eventStreamResponse();
      }
      return jsonResponse(bootstrapPayload);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AppShell />);

    await waitFor(() => expect(eventUrls.length).toBeGreaterThanOrEqual(2));
    expect(eventUrls[1]).toContain("lastSeenSequence=1");
    expect(eventUrls[1]).toContain("eventSessionId=ui_sess_test");
  });

  test("preserves authoritative stage and trial success count across ten resync cycles", async () => {
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "browser", stage: "recording", summary: {} },
      selectedMode: "browser",
      stage: "recording",
    });
    let eventStreamsServed = 0;
    let runRefreshes = 0;
    let skillRefreshes = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/events")) {
        eventStreamsServed += 1;
        if (eventStreamsServed <= 10) {
          return eventStreamResponse([
            eventFrame({
              eventId: `evt_resync_${eventStreamsServed}`,
              sequence: eventStreamsServed,
              sessionId: "ui_sess_test",
              causationId: null,
              type: "backend.resync_required",
              scope: {},
              payload: {
                reason: "replay_gap",
                domains: ["teaching", "skills"],
                eventSessionId: "ui_sess_test",
              },
              createdAt: "2026-05-10T00:00:00Z",
            }),
          ], { close: true });
        }
        return eventStreamResponse();
      }
      if (url.endsWith("/api/teaching/runs/rec_1")) {
        runRefreshes += 1;
        return jsonResponse({
          workflowId: "rec_1",
          mode: "browser",
          stage: "published",
          summary: { trialSuccessCount: runRefreshes },
        });
      }
      if (url.endsWith("/api/skills?category=pending")) {
        skillRefreshes += 1;
        return jsonResponse({
          category: "pending",
          count: 1,
          items: [
            {
              toolId: "tool_1",
              name: "稳定技能",
              description: "由权威技能列表刷新。",
              status: "pending",
              source: "teaching",
              trialSuccessCount: skillRefreshes,
              workflowId: "rec_1",
            },
          ],
        });
      }
      if (url.endsWith("/api/skills?category=published")) return jsonResponse({ category: "published", count: 0, items: [] });
      if (url.endsWith("/api/skills?category=failed")) return jsonResponse({ category: "failed", count: 0, items: [] });
      if (url.endsWith("/api/compositions")) return jsonResponse({ items: [] });
      if (url.endsWith("/api/settings/schema")) return jsonResponse({ sections: [] });
      if (url.endsWith("/api/settings/values")) return jsonResponse({ values: {}, secrets: {}, status: {} });
      return jsonResponse(bootstrapPayload);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AppShell />);

    await waitFor(() => expect(runRefreshes).toBe(10));
    await waitFor(() => expect(skillRefreshes).toBe(10));
    expect(eventStreamsServed).toBeGreaterThanOrEqual(10);
    expect(useTeachingStore.getState().stage).toBe("published");
    expect(useSkillsStore.getState().categories.pending[0]?.trialSuccessCount).toBe(10);
  });
});
