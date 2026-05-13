import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AppShell } from "../../src/app/AppShell";
import { useShellStore } from "../../src/state/shellStore";

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
};

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    json: async () => payload,
  } as Response;
}

function eventStreamResponse(): Response {
  return {
    ok: true,
    body: new ReadableStream(),
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
        return jsonResponse(bootstrapPayload);
      }),
    );
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

    for (const label of ["技能教学", "技能列表", "技能组合", "应用设置"]) {
      fireEvent.click(within(navigation).getByRole("button", { name: new RegExp(label) }));
      expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
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
});
