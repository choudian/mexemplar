import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { waitFor } from "@testing-library/react";

import { configureDesktopApi } from "../../../src/api/client";
import { useBrainStore } from "../../../src/state/brainStore";

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

function errorResponse(status: number, payload: unknown): Response {
  return { ok: false, status, json: async () => payload } as Response;
}

const entry = {
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
};

describe("brainStore", () => {
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

  test("loads zones, entries, segments, evolution chain, and skill pool", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/brain/zones")) {
          return jsonResponse({ zones: [{ zone: "hot", label: "热区", entry_count: 1, fading_count: 0 }] });
        }
        if (url.includes("/api/brain/zones/hot/entries")) {
          return jsonResponse({ items: [entry], total: 1, limit: 50, offset: 0 });
        }
        if (url.includes("/api/brain/segments")) {
          return jsonResponse({ items: [{ segment_id: "seg-1", status: "failed", retry_count: 1 }], total: 1 });
        }
        if (url.endsWith("/api/brain/entries/entry-1/evolution")) {
          return jsonResponse({ chain: [entry] });
        }
        if (url.endsWith("/api/brain/skill-pool")) {
          return jsonResponse({ skills: [{ tool_id: "tool-1", name: "报表分析", description: "分析报表" }] });
        }
        return jsonResponse({});
      }),
    );

    await useBrainStore.getState().loadZones();
    await useBrainStore.getState().loadEntries("hot");
    await useBrainStore.getState().loadSegments();
    await useBrainStore.getState().loadEvolution("entry-1");
    await useBrainStore.getState().loadSkillPool();

    const state = useBrainStore.getState();
    expect(state.zones[0].zone).toBe("hot");
    expect(state.entries[0].content).toBe("用户偏好简洁回复");
    expect(state.activeZone).toBe("hot");
    expect(state.segments[0].segment_id).toBe("seg-1");
    expect(state.evolutionChain).toHaveLength(1);
    expect(state.skillPool[0].tool_id).toBe("tool-1");
  });

  test("applies zone events by refreshing active entries", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) return jsonResponse({ zones: [] });
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [{ ...entry, content: "刷新后的条目" }], total: 1, limit: 50, offset: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    useBrainStore.setState({ activeZone: "hot" });

    useBrainStore.getState().applyEvent({
      eventId: "evt-1",
      sequence: 1,
      sessionId: "ui-1",
      type: "brain_zone_changed",
      scope: {},
      payload: { zone: "hot", changeType: "create" },
      createdAt: new Date().toISOString(),
    });

    await waitFor(() => expect(useBrainStore.getState().entries[0].content).toBe("刷新后的条目"));
  });

  test("routes edit, delete, retry, and skill removal through the API", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [entry], total: 1, limit: 50, offset: 0 });
      }
      if (url.endsWith("/api/brain/segments")) return jsonResponse({ items: [], total: 0 });
      if (url.endsWith("/api/brain/skill-pool")) return jsonResponse({ skills: [] });
      return jsonResponse(entry);
    });
    vi.stubGlobal("fetch", fetchMock);
    useBrainStore.setState({ activeZone: "hot" });

    await useBrainStore.getState().editEntry("entry-1", "新内容", "新范围");
    await useBrainStore.getState().deleteEntry("entry-1");
    await useBrainStore.getState().retrySegment("seg-1");
    await useBrainStore.getState().removeSkill("tool-1", true);

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
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/skill-pool/tool-1?force=true",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  test("captures affected specialists when skill removal is blocked", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/brain/skill-pool/tool-1?force=false")) {
          return errorResponse(409, {
            detail: {
              error: "skill_in_use",
              affected_specialists: [{ specialist_id: "spec-1", name: "财务专员" }],
            },
          });
        }
        return jsonResponse({});
      }),
    );

    await useBrainStore.getState().removeSkill("tool-1");

    expect(useBrainStore.getState().pendingSkillRemoval).toEqual({
      toolId: "tool-1",
      affectedSpecialists: [{ specialist_id: "spec-1", name: "财务专员" }],
    });
    expect(useBrainStore.getState().lastError).toBeNull();
  });
});
