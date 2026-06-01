import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../../src/api/client";
import BrainScreen from "../../../src/screens/BrainScreen";
import { useBrainStore } from "../../../src/state/brainStore";

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

async function settleAsyncUpdates(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

const entry = {
  entry_id: "entry-1",
  zone: "hot",
  entry_type: "insight",
  content: "用户偏好简洁回复",
  status: "active",
  origin: "distillation",
  reason: "用户多次要求直接给结论",
  scope: "沟通",
  loaded_count: 2,
  referenced_count: 1,
  superseded_by: null,
  verification_checkpoint: null,
  verification_status: null,
  verification_rationale: null,
  created_at: null,
  updated_at: null,
};

describe("BrainScreen", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useBrainStore.setState({
      zones: [],
      entries: [],
      entriesTotal: 0,
      activeZone: null,
      segments: [],
      segmentsTotal: 0,
      skillPool: [],
      evolutionChain: [],
      loadingZones: false,
      loadingEntries: false,
      loadingSegments: false,
      loadingSkillPool: false,
      loadingEvolution: false,
      lastError: null,
      pendingSkillRemoval: null,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("browses zones, edits and deletes entries, shows reasons and evolution", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) {
        return jsonResponse({ zones: [{ zone: "hot", label: "热区", entry_count: 1, fading_count: 0 }] });
      }
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [entry], total: 1, limit: 50, offset: 0 });
      }
      if (url.includes("/api/brain/segments")) {
        return jsonResponse({
          items: [{ segment_id: "seg-1", session_id: "sess-1", status: "failed", retry_count: 1, boundary_reason: "idle" }],
          total: 1,
        });
      }
      if (url.endsWith("/api/brain/skill-pool")) {
        return jsonResponse({ skills: [{ tool_id: "tool-1", name: "报表分析", description: "分析报表" }] });
      }
      if (url.endsWith("/api/brain/entries/entry-1/evolution")) {
        return jsonResponse({ chain: [entry, { ...entry, entry_id: "entry-2", content: "用户偏好先给结论" }] });
      }
      return jsonResponse(entry);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<BrainScreen />);
    await settleAsyncUpdates();

    await waitFor(() => expect(screen.getAllByText("用户偏好简洁回复").length).toBeGreaterThan(0));
    expect(screen.getAllByText("用户多次要求直接给结论").length).toBeGreaterThan(0);
    expect(screen.getByText("用户偏好先给结论")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("编辑条目内容"), { target: { value: "用户偏好先给结论" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await settleAsyncUpdates();
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    await settleAsyncUpdates();

    const segmentPanel = screen.getByRole("region", { name: "Segment 列表" });
    fireEvent.click(within(segmentPanel).getByRole("button", { name: "重试 Segment" }));
    await settleAsyncUpdates();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/entries/entry-1",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/entries/entry-1",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/segments/seg-1/retry",
      expect.objectContaining({ method: "POST" }),
    );
  });

});
