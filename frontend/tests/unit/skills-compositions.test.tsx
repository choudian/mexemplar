import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
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

    expect(screen.queryByRole("button", { name: "试用" })).toBeNull();

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
