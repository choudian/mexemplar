import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import CompositionEditor from "../../src/screens/compositions/CompositionEditor";
import { CompositionListScreen } from "../../src/screens/compositions/CompositionListScreen";
import { SkillListScreen } from "../../src/screens/skills/SkillListScreen";
import { useCompositionsStore } from "../../src/state/compositionsStore";
import { useSkillsStore } from "../../src/state/skillsStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

const publishedSkill = {
  toolId: "tool_a",
  name: "Published Skill",
  description: "Ready to reuse",
  status: "published",
  source: "assistant",
  trialSuccessCount: 2,
};

describe("skills and compositions screens", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useSkillsStore.setState({
      hydrated: false,
      activeCategory: "pending",
      categories: { pending: [], published: [], failed: [] },
      counts: { pending: 0, published: 0, failed: 0 },
      busy: false,
      lastError: null,
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

  test("switches skill categories with keyboard activation and runs category actions", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/skills?category=pending")) {
        return jsonResponse({
          category: "pending",
          count: 1,
          items: [
            {
              toolId: "tool_pending",
              name: "Pending Skill",
              description: "Needs validation",
              status: "pending",
              source: "teaching",
              trialSuccessCount: 0,
            },
          ],
        });
      }
      if (url.endsWith("/api/skills?category=published")) {
        return jsonResponse({ category: "published", count: 1, items: [publishedSkill] });
      }
      if (url.endsWith("/api/skills?category=failed")) {
        return jsonResponse({
          category: "failed",
          count: 1,
          items: [
            {
              toolId: "tool_failed",
              name: "Failed Skill",
              description: "Retryable failure",
              status: "failed",
              source: "teaching",
              trialSuccessCount: 0,
              workflowId: "wf_fail",
              failureStage: "trial",
              errorSummary: "Timed out",
            },
          ],
        });
      }
      if (url.endsWith("/api/skills/tool_a/trial")) {
        return jsonResponse({ accepted: true, workflowId: "wf_trial" });
      }
      if (url.endsWith("/api/skills/failures/wf_fail/dismiss")) {
        return jsonResponse({ accepted: true });
      }
      return jsonResponse({ accepted: true });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SkillListScreen />);

    await waitFor(() => expect(screen.getByText("Pending Skill")).toBeInTheDocument());

    const publishedTab = screen.getByRole("tab", { name: /已掌握/ });
    publishedTab.focus();
    fireEvent.keyDown(publishedTab, { key: "Enter" });
    fireEvent.click(publishedTab);
    await waitFor(() => expect(screen.getByText("Published Skill")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "试用" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/skills/tool_a/trial",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    fireEvent.click(screen.getByRole("tab", { name: /失败记录/ }));
    await waitFor(() => expect(screen.getByText("Failed Skill")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "忽略失败" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/skills/failures/wf_fail/dismiss",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  test("keeps failed count non-negative when dismiss races with a refresh", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ accepted: true }));
    vi.stubGlobal("fetch", fetchMock);
    useSkillsStore.setState({
      categories: {
        pending: [],
        published: [],
        failed: [
          {
            toolId: "tool_failed",
            name: "Failed Skill",
            description: "Retryable failure",
            status: "failed",
            source: "teaching",
            trialSuccessCount: 0,
            workflowId: "wf_fail",
          },
        ],
      },
      counts: { pending: 0, published: 0, failed: 0 },
    });

    await useSkillsStore.getState().dismissFailure("wf_fail");

    expect(useSkillsStore.getState().counts.failed).toBe(0);
    expect(useSkillsStore.getState().categories.failed).toEqual([]);
  });

  test("blocks saving a single-member composition and shows a min-two hint", () => {
    const editorProps = {
      skills: [],
      busy: false,
      canPublish: false,
      onField: () => {},
      onMode: () => {},
      onAddMember: () => {},
      onMoveMember: () => {},
      onRemoveMember: () => {},
      onGenerateApplicability: () => {},
      onRecommendOrder: () => {},
      onSave: () => {},
      onPublish: () => {},
      onTrial: () => {},
    };

    const { rerender } = render(
      <CompositionEditor
        {...editorProps}
        draft={{
          name: "Solo",
          description: "",
          mode: "range",
          applicability: "When only one skill is picked",
          members: [{ toolId: "tool_a", name: "Only Skill", description: "", selectedOrder: 1 }],
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "保存草稿" })).toBeDisabled();
    expect(screen.getByText("技能组合至少要添加 2 个技能")).toBeInTheDocument();

    rerender(
      <CompositionEditor
        {...editorProps}
        draft={{
          name: "Pair",
          description: "",
          mode: "range",
          applicability: "When two skills cooperate",
          members: [
            { toolId: "tool_a", name: "First Skill", description: "", selectedOrder: 1 },
            { toolId: "tool_b", name: "Second Skill", description: "", selectedOrder: 2 },
          ],
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "保存草稿" })).toBeEnabled();
    expect(screen.queryByText("技能组合至少要添加 2 个技能")).not.toBeInTheDocument();
  });

  test("shows built-in compositions as read-only and disables trial", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/compositions")) {
          return jsonResponse({
            items: [
              {
                compositionId: "comp_builtin_external_coding",
                name: "外部 Coding",
                description: "专员正式任务中的外部 Coding 能力范围",
                mode: "range",
                status: "published",
                displayStatus: "published",
                needsReview: false,
                assistantEnabled: true,
                applicability: "正式编码任务",
                isBuiltin: true,
                readOnly: true,
                trialSupported: false,
                members: [
                  {
                    toolId: "start_external_coding_session",
                    name: "启动外部 Coding 会话",
                    selectedOrder: 1,
                  },
                ],
              },
            ],
          });
        }
        if (url.endsWith("/api/skills?category=published")) {
          return jsonResponse({ category: "published", count: 0, items: [] });
        }
        return jsonResponse({});
      }),
    );

    render(<CompositionListScreen />);

    await waitFor(() => expect(screen.getByText("外部 Coding")).toBeInTheDocument());
    expect(screen.getByText("系统内置")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "试用" })).toBeDisabled();
  });

  test("creates an ordered composition, reorders members, tries it, and publishes it", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/compositions")) {
        if (init?.method === "POST") {
          return jsonResponse({
            compositionId: "comp_1",
            name: "Morning Flow",
            description: "Automates the morning task",
            mode: "ordered",
            status: "draft",
            displayStatus: "draft",
            needsReview: false,
            assistantEnabled: true,
            applicability: "When opening daily workspace",
            members: [
              {
                memberId: "m_1",
                toolId: "tool_a",
                name: "Published Skill",
                description: "Ready to reuse",
                selectedOrder: 1,
                executionOrder: 1,
              },
              {
                memberId: "m_2",
                toolId: "tool_b",
                name: "Second Skill",
                description: "Runs after the first skill",
                selectedOrder: 2,
                executionOrder: 2,
              },
            ],
          });
        }
        return jsonResponse({
          items: [
            {
              compositionId: "comp_review",
              name: "Review Needed Flow",
              description: "Needs recheck",
              mode: "range",
              status: "published",
              displayStatus: "needs_review",
              needsReview: true,
              assistantEnabled: true,
              applicability: "When a member skill changed",
              members: [],
            },
          ],
        });
      }
      if (url.endsWith("/api/skills?category=published")) {
        return jsonResponse({
          category: "published",
          count: 2,
          items: [
            publishedSkill,
            {
              ...publishedSkill,
              toolId: "tool_b",
              name: "Second Skill",
              description: "Runs after the first skill",
            },
          ],
        });
      }
      if (url.endsWith("/api/compositions/comp_1/trial")) {
        return jsonResponse({ accepted: true, sessionId: "trial_1" });
      }
      if (url.endsWith("/api/compositions/comp_1/publish")) {
        return jsonResponse({
          compositionId: "comp_1",
          name: "Morning Flow",
          description: "Automates the morning task",
          mode: "ordered",
          status: "published",
          displayStatus: "published",
          needsReview: false,
          assistantEnabled: true,
          applicability: "When opening daily workspace",
          members: [
            {
              memberId: "m_1",
              toolId: "tool_a",
              name: "Published Skill",
              description: "Ready to reuse",
              selectedOrder: 1,
              executionOrder: 1,
            },
            {
              memberId: "m_2",
              toolId: "tool_b",
              name: "Second Skill",
              description: "Runs after the first skill",
              selectedOrder: 2,
              executionOrder: 2,
            },
          ],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CompositionListScreen />);

    await waitFor(() => expect(screen.getByText("待复核")).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: /新建组合/ })[0]);
    await waitFor(() => expect(screen.getByText("Published Skill")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Morning Flow" } });
    fireEvent.change(screen.getByLabelText("描述"), { target: { value: "Automates the morning task" } });
    fireEvent.change(screen.getByLabelText("模式"), { target: { value: "ordered" } });
    fireEvent.change(screen.getByLabelText("适用场景"), { target: { value: "When opening daily workspace" } });
    fireEvent.click(screen.getByRole("button", { name: /Published Skill/ }));
    fireEvent.click(screen.getByRole("button", { name: /Second Skill/ }));

    const firstMember =
      screen
        .getAllByText("Published Skill")
        .map((element) => element.closest(".composition-member-row"))
        .find(Boolean) ?? null;
    expect(firstMember).not.toBeNull();
    fireEvent.click(within(firstMember as HTMLElement).getByRole("button", { name: "下移成员" }));
    expect(screen.getByRole("button", { name: /AI 推荐顺序/ })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/compositions",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    await waitFor(() => expect(screen.getByRole("button", { name: "试用" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "试用" }));
    fireEvent.click(screen.getByRole("button", { name: "发布" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/compositions/comp_1/trial",
        expect.objectContaining({ method: "POST" }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/compositions/comp_1/publish",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
