import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../../src/api/client";
import SpecialistScreen from "../../../src/screens/SpecialistScreen";
import { useBrainStore } from "../../../src/state/brainStore";
import { useCompositionsStore } from "../../../src/state/compositionsStore";
import { useSpecialistStore } from "../../../src/state/specialistStore";

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

const specialist = {
  specialist_id: "spec-1",
  name: "报表专员",
  description: "处理周期报表",
  role_definition: "你负责处理报表。",
  tool_whitelist: ["tool-1"],
  composition_ids: [],
  origin: "auto_recruitment",
  reason: "检测到持续报表委托",
  current_version: 1,
  is_active: true,
  created_at: null,
  updated_at: null,
};

describe("SpecialistScreen", () => {
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
        composition_ids: [],
        change_reason: "",
      },
      versions: [],
      loading: false,
      loadingVersions: false,
      saving: false,
      lastError: null,
      recruitmentToast: null,
    });
    useBrainStore.setState({
      skillPool: [{ tool_id: "tool-1", name: "报表分析", description: "分析报表" }],
      loadingSkillPool: false,
    });
    useCompositionsStore.setState({
      hydrated: false,
      items: [],
      selectedId: null,
      draft: { name: "", description: "", mode: "range", applicability: "", members: [] },
      busy: false,
      lastError: null,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("edits, saves, deletes, and toggles specialist whitelist", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/brain/specialists?limit=50&offset=0&active_only=true")) {
        return jsonResponse({ items: [specialist], total: 1, limit: 50, offset: 0 });
      }
      if (url.endsWith("/api/brain/skill-pool")) {
        return jsonResponse({ skills: [{ tool_id: "tool-1", name: "报表分析", description: "分析报表" }] });
      }
      if (url.endsWith("/api/compositions")) {
        return jsonResponse({
          items: [
            {
              compositionId: "comp_builtin_external_coding",
              name: "外部 Coding",
              description: "把外部 Coding 会话能力作为范围授权",
              mode: "range",
              status: "published",
              needsReview: false,
              assistantEnabled: true,
              applicability: "正式编码任务",
              isBuiltin: true,
              readOnly: true,
              trialSupported: false,
              members: [],
            },
            {
              compositionId: "comp_disabled",
              name: "已禁用组合",
              description: "不允许分配给助理或专员",
              mode: "range",
              status: "published",
              needsReview: false,
              assistantEnabled: false,
              applicability: "不应显示",
              members: [],
            },
          ],
        });
      }
      if (url.endsWith("/api/brain/specialists/spec-1/versions?limit=20&offset=0")) {
        return jsonResponse({
          items: [{ version_id: "v1", specialist_id: "spec-1", version: 1, name: "报表专员", change_reason: "初始创建" }],
        });
      }
      if (url.endsWith("/api/brain/specialists/spec-1") && init?.method === "PUT") {
        return jsonResponse({ ...specialist, description: "更新后的描述", current_version: 2 });
      }
      return jsonResponse(specialist);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SpecialistScreen />);
    await settleAsyncUpdates();

    await waitFor(() => expect(screen.getByText("报表专员")).toBeInTheDocument());
    fireEvent.click(screen.getByText("报表专员"));
    await settleAsyncUpdates();
    await waitFor(() => expect(screen.getByText("初始创建")).toBeInTheDocument());
    expect(screen.queryByLabelText("技能组合 已禁用组合")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("专员描述"), { target: { value: "更新后的描述" } });
    fireEvent.click(screen.getByLabelText(/报表分析/));
    fireEvent.click(screen.getByLabelText("技能组合 外部 Coding"));
    fireEvent.click(screen.getByRole("button", { name: "保存专员" }));
    await settleAsyncUpdates();
    fireEvent.click(screen.getByRole("button", { name: "删除专员" }));
    await settleAsyncUpdates();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/specialists/spec-1",
      expect.objectContaining({ method: "PUT" }),
    );
    const updateCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/api/brain/specialists/spec-1") && init?.method === "PUT",
    );
    expect(JSON.parse(String(updateCall?.[1]?.body))).toEqual(
      expect.objectContaining({ composition_ids: ["comp_builtin_external_coding"] }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/brain/specialists/spec-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  test("creates a specialist from an empty draft", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/brain/specialists?limit=50&offset=0&active_only=true")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
      }
      if (url.endsWith("/api/brain/skill-pool")) return jsonResponse({ skills: [] });
      if (url.endsWith("/api/compositions")) return jsonResponse({ items: [] });
      if (url.endsWith("/api/brain/specialists") && init?.method === "POST") {
        return jsonResponse(specialist);
      }
      return jsonResponse({ items: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SpecialistScreen />);
    await settleAsyncUpdates();

    fireEvent.change(screen.getByLabelText("专员名称"), { target: { value: "报表专员" } });
    fireEvent.change(screen.getByLabelText("专员描述"), { target: { value: "处理周期报表" } });
    fireEvent.change(screen.getByLabelText("专员角色定义"), { target: { value: "你负责处理报表。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存专员" }));
    await settleAsyncUpdates();

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/brain/specialists",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
