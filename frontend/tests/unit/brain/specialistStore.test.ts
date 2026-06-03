import { waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../../src/api/client";
import { useBrainStore } from "../../../src/state/brainStore";
import { useSpecialistStore } from "../../../src/state/specialistStore";

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

const specialist = {
  specialist_id: "spec-1",
  name: "报表专员",
  description: "处理周期报表",
  role_definition: "你负责处理报表。",
  tool_whitelist: ["tool-1"],
  origin: "auto_recruitment",
  reason: "检测到持续报表委托",
  current_version: 1,
  is_active: true,
  created_at: null,
  updated_at: null,
};

describe("specialistStore", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useSpecialistStore.setState({
      items: [],
      total: 0,
      selectedId: null,
      draft: {
        specialist_id: null,
        name: "",
        description: "",
        role_definition: "",
        tool_whitelist: [],
        change_reason: "",
      },
      versions: [],
      loading: false,
      loadingVersions: false,
      saving: false,
      lastError: null,
      recruitmentToast: null,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("loads specialists, selects a draft, and toggles whitelist tools", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/brain/specialists?limit=50&offset=0&active_only=true")) {
          return jsonResponse({ items: [specialist], total: 1, limit: 50, offset: 0 });
        }
        if (url.endsWith("/api/brain/skill-pool")) {
          return jsonResponse({ skills: [{ tool_id: "tool-2", name: "图表生成", description: "生成图表" }] });
        }
        if (url.endsWith("/api/brain/specialists/spec-1/versions?limit=20&offset=0")) {
          return jsonResponse({ items: [{ version_id: "v1", specialist_id: "spec-1", version: 1, name: "报表专员" }] });
        }
        return jsonResponse({});
      }),
    );

    await useSpecialistStore.getState().load();
    await useBrainStore.getState().loadSkillPool();
    useSpecialistStore.getState().select("spec-1");

    await waitFor(() => expect(useSpecialistStore.getState().versions[0].version).toBe(1));
    expect(useSpecialistStore.getState().draft.name).toBe("报表专员");

    useSpecialistStore.getState().toggleWhitelist("tool-2");
    expect(useSpecialistStore.getState().draft.tool_whitelist).toContain("tool-2");
  });

  test("creates, updates, deletes, and displays recruitment toast from events", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/brain/specialists?limit=50&offset=0&active_only=true")) {
        return jsonResponse({ items: [specialist], total: 1, limit: 50, offset: 0 });
      }
      if (url.endsWith("/api/brain/specialists/spec-1/versions?limit=20&offset=0")) {
        return jsonResponse({ items: [] });
      }
      if (url.endsWith("/api/brain/specialists") && init?.method === "POST") {
        return jsonResponse(specialist);
      }
      return jsonResponse(specialist);
    });
    vi.stubGlobal("fetch", fetchMock);

    useSpecialistStore.getState().setDraftField("name", "报表专员");
    useSpecialistStore.getState().setDraftField("description", "处理周期报表");
    useSpecialistStore.getState().setDraftField("role_definition", "你负责处理报表。");
    await useSpecialistStore.getState().saveDraft();
    await useSpecialistStore.getState().saveDraft();
    await useSpecialistStore.getState().deleteById("spec-1");

    useSpecialistStore.getState().applyEvent({
      eventId: "evt-1",
      sequence: 1,
      sessionId: "ui-1",
      type: "brain_specialist_recruited",
      scope: {},
      payload: {
        specialistId: "spec-2",
        name: "研究专员",
        reason: "检测到持续研究委托",
        managementUrl: "/brain/specialists",
      },
      createdAt: new Date().toISOString(),
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/specialists",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/specialists/spec-1",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/specialists/spec-1",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(useSpecialistStore.getState().recruitmentToast?.name).toBe("研究专员");
  });

  test("refreshes specialists on specialist changed events without recruitment toast", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/specialists?limit=50&offset=0&active_only=true")) {
        return jsonResponse({ items: [specialist], total: 1, limit: 50, offset: 0 });
      }
      if (url.endsWith("/api/brain/specialists/spec-1/versions?limit=20&offset=0")) {
        return jsonResponse({ items: [{ version_id: "v1", specialist_id: "spec-1", version: 1, name: "报表专员" }] });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    useSpecialistStore.setState({ selectedId: "spec-1" });

    useSpecialistStore.getState().applyEvent({
      eventId: "evt-2",
      sequence: 2,
      sessionId: "ui-1",
      type: "brain_specialist_changed",
      scope: {},
      payload: {
        specialistId: "spec-1",
        changeType: "update",
      },
      createdAt: new Date().toISOString(),
    });

    await waitFor(() => expect(useSpecialistStore.getState().items).toHaveLength(1));
    expect(useSpecialistStore.getState().versions[0].version).toBe(1);
    expect(useSpecialistStore.getState().recruitmentToast).toBeNull();
  });

  test("clears deleted selected specialist before loading versions from change events", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/specialists?limit=50&offset=0&active_only=true")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
      }
      if (url.endsWith("/api/brain/specialists/spec-1/versions?limit=20&offset=0")) {
        throw new Error("stale version load should not run");
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    useSpecialistStore.setState({
      selectedId: "spec-1",
      draft: {
        specialist_id: "spec-1",
        name: "报表专员",
        description: "处理周期报表",
        role_definition: "你负责处理报表。",
        tool_whitelist: ["tool-1"],
        change_reason: "",
      },
      versions: [{ version_id: "v1", specialist_id: "spec-1", version: 1, name: "报表专员" }],
    });

    useSpecialistStore.getState().applyEvent({
      eventId: "evt-3",
      sequence: 3,
      sessionId: "ui-1",
      type: "brain_specialist_changed",
      scope: {},
      payload: {
        specialistId: "spec-1",
        changeType: "delete",
      },
      createdAt: new Date().toISOString(),
    });

    await waitFor(() => expect(useSpecialistStore.getState().selectedId).toBeNull());

    expect(useSpecialistStore.getState().versions).toEqual([]);
    expect(useSpecialistStore.getState().lastError).toBeNull();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith("/api/brain/specialists/spec-1/versions?limit=20&offset=0"),
      ),
    ).toBe(false);
  });
});
