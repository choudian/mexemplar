import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { BrainScreen } from "../../src/screens/BrainScreen/BrainScreen";
import { useBrainStore } from "../../src/state/brainStore";
import { useSettingsStore } from "../../src/state/settingsStore";

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    json: async () => payload,
  } as Response;
}

beforeEach(() => {
  configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
  useBrainStore.setState({
    zones: [],
    entries: [],
    entriesTotal: 0,
    activeZone: null,
    segments: [],
    segmentsTotal: 0,
    executionReviews: [],
    loadingZones: false,
    loadingEntries: false,
    loadingSegments: false,
    loadingExecutionReviews: false,
    lastError: null,
  });
  useSettingsStore.setState({
    values: { "self_improvement.execution_review.enabled": true },
    draftValues: { "self_improvement.execution_review.enabled": true },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders execution review verdict", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/brain/zones")) return jsonResponse({ zones: [] });
    if (url.includes("/api/brain/zones/hot/entries")) {
      return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
    }
    if (url.includes("/api/brain/segments")) {
      return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 });
    }
    if (url.includes("/api/execution-reviews")) {
      return jsonResponse({
        reviews: [
          {
            id: "exr_1",
            turnSessionId: "ast_x",
            verdict: "重复抓取",
            findings: [
              {
                type: "效率",
                what: "同一 URL 两次抓取",
                evidence: "step0,step2",
                severity: "med",
                suggestion: "复用首次结果",
                worth_changing: true,
              },
            ],
            advisory: true,
            modelUsed: "review-model",
            createdAt: "2026-06-28T00:00:00Z",
            reviewedAt: "2026-06-28T00:01:00Z",
          },
        ],
      });
    }
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<BrainScreen />);
  fireEvent.click(await screen.findByRole("button", { name: /执行复盘/ }));

  expect((await screen.findAllByText(/重复抓取/)).length).toBeGreaterThan(0);
  expect(screen.getByText(/复用首次结果/)).toBeInTheDocument();
});

test("hides execution review section when setting is disabled", async () => {
  useSettingsStore.setState({
    values: { "self_improvement.execution_review.enabled": false },
    draftValues: { "self_improvement.execution_review.enabled": false },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) return jsonResponse({ zones: [] });
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
      }
      if (url.includes("/api/brain/segments")) {
        return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 });
      }
      return jsonResponse({});
    }),
  );

  render(<BrainScreen />);

  await waitFor(() => expect(screen.queryByRole("button", { name: /执行复盘/ })).not.toBeInTheDocument());
});
