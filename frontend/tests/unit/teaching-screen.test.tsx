import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { invoke } from "@tauri-apps/api/core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { TeachingScreen } from "../../src/screens/teaching/TeachingScreen";
import { TrialStage } from "../../src/screens/teaching/TrialStage";
import { useTeachingStore } from "../../src/state/teachingStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

describe("TeachingScreen", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
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
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  test("loads readiness and advances through recording, intent, and trial controls", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/teaching/readiness")) {
        return jsonResponse({
          modes: [
            { mode: "browser", status: "ready", message: "可录制浏览器操作。", actions: [] },
            { mode: "extension", status: "ready", message: "可通过浏览器扩展触发录制。", actions: [] },
            { mode: "desktop", status: "ready", message: "可录制桌面操作。", actions: [] },
          ],
        });
      }
      if (url.endsWith("/api/teaching/runs")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "selecting", summary: {} });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/recording/start")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "recording", summary: {} });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/recording/stop")) {
        return jsonResponse({
          workflowId: "rec_1",
          mode: "browser",
          stage: "intent_confirmation",
          summary: {},
        });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/intent/reply")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "intent_confirmation", summary: {} });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/intent/confirm")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "learning", summary: {} });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/trial/start")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "trial_validation", summary: {} });
      }
      if (url.endsWith("/api/teaching/trial-preview/preview_1/decision")) {
        return jsonResponse({ requestId: "preview_1", decision: "approve", accepted: true, status: "approved" });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<TeachingScreen />);

    await waitFor(() => expect(screen.getByText("浏览器")).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "开始" })[0]);
    await waitFor(() => expect(screen.getByText("开始录制")).toBeEnabled());

    fireEvent.click(screen.getByText("开始录制"));
    await waitFor(() => expect(screen.getByText("停止录制")).toBeInTheDocument());

    fireEvent.click(screen.getByText("停止录制"));
    const intentInput = await screen.findByPlaceholderText("回复需求分析师…");
    fireEvent.change(intentInput, { target: { value: "确认并学习" } });
    fireEvent.keyDown(intentInput, { key: "Enter", code: "Enter" });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/teaching/runs/rec_1/intent/reply",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ content: "确认并学习" }),
        }),
      ),
    );
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/teaching/runs/rec_1/intent/confirm")),
    ).toBe(false);
    await waitFor(() => expect(screen.getByPlaceholderText("回复需求分析师…")).toBeEnabled());

    act(() => {
      useTeachingStore.getState().applyEvent({
        eventId: "evt_requirements_confirmed",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: "rec_1",
        type: "teaching.stage_changed",
        scope: { workflowId: "rec_1" },
        payload: { stage: "learning", headline: "Requirements confirmed." },
        createdAt: "2026-05-10T00:00:00Z",
      });
    });
    await waitFor(() => expect(screen.getByRole("heading", { name: "正在学习技能…" })).toBeInTheDocument());

    act(() => {
      useTeachingStore.getState().applyEvent({
        eventId: "evt_learning_done",
        sequence: 2,
        sessionId: "ui_sess_test",
        causationId: "rec_1",
        type: "teaching.stage_changed",
        scope: { workflowId: "rec_1" },
        payload: { stage: "trial_validation", headline: "Skill learning completed" },
        createdAt: "2026-05-10T00:00:01Z",
      });
    });
    await waitFor(() => expect(screen.getByRole("heading", { name: "试用验证" })).toBeInTheDocument());

    const trialInput = screen.getByPlaceholderText("给我一个真实任务...");
    fireEvent.change(trialInput, { target: { value: "整理上周的客户反馈邮件" } });
    fireEvent.keyDown(trialInput, { key: "Enter", code: "Enter" });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/teaching/runs/rec_1/trial/start",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    act(() => {
      useTeachingStore.getState().applyEvent({
        eventId: "evt_preview",
        sequence: 3,
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
      });
    });
    await waitFor(() => expect(screen.getByText("桌面试用确认")).toBeInTheDocument());
    fireEvent.click(screen.getByText("批准"));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/teaching/trial-preview/preview_1/decision",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ decision: "approve" }) }),
      ),
    );
  });

  test("minimizes the Tauri window before starting desktop recording", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/teaching/runs/rec_desktop/recording/start")) {
        return jsonResponse({
          workflowId: "rec_desktop",
          mode: "desktop",
          stage: "recording",
          summary: {},
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(invoke).mockClear();
    useTeachingStore.setState({
      run: {
        workflowId: "rec_desktop",
        mode: "desktop",
        stage: "selecting",
        summary: {},
      },
      selectedMode: "desktop",
      trialPreview: null,
    });

    await useTeachingStore.getState().startRecording();

    expect(invoke).toHaveBeenCalledWith("minimize");
    const fetchCalls = fetchMock.mock.calls as unknown as Array<
      [RequestInfo | URL, RequestInit | undefined]
    >;
    const startCall = fetchCalls.find(([input]) =>
      String(input).endsWith("/api/teaching/runs/rec_desktop/recording/start"),
    );
    expect(startCall).toBeDefined();
    expect(JSON.parse(String((startCall?.[1] as RequestInit).body))).toEqual({
      mode: "desktop",
      windowMinimized: true,
    });
  });

  test("disables trial preview decisions when the backend deadline expires", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-10T00:00:00Z"));
    const onPreviewDecision = vi.fn();

    render(
      <TrialStage
        active
        disabled={false}
        onStart={vi.fn()}
        preview={{
          requestId: "preview_1",
          workflowId: "rec_1",
          trialId: "trial_1",
          summary: "桌面试用需要确认。",
          codePreview: "print('safe preview')",
          riskSummary: "将控制本机桌面。",
          expires_at: "2026-05-10T00:00:01Z",
          status: "pending",
        }}
        onPreviewDecision={onPreviewDecision}
      />,
    );

    expect(screen.getByText("批准")).toBeEnabled();

    await act(async () => {
      vi.advanceTimersByTime(1100);
    });

    expect(screen.getByText("批准")).toBeDisabled();
    fireEvent.click(screen.getByText("批准"));
    expect(onPreviewDecision).not.toHaveBeenCalled();
  });

  test("shows a clear error when a trial preview decision is no longer accepted", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/teaching/trial-preview/preview_1/decision")) {
        return jsonResponse({ requestId: "preview_1", decision: "approve", accepted: false, status: "expired" });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    useTeachingStore.setState({
      trialPreview: {
        requestId: "preview_1",
        workflowId: "rec_1",
        trialId: "trial_1",
        summary: "桌面试用需要确认。",
        codePreview: "print('safe preview')",
        riskSummary: "将控制本机桌面。",
        expires_at: "2026-05-10T00:00:01Z",
        status: "pending",
      },
      lastError: null,
    });

    await useTeachingStore.getState().decideTrialPreview("preview_1", "approve");

    expect(useTeachingStore.getState().lastError).toBe("该试用确认已过期。");
    expect(useTeachingStore.getState().trialPreview).toBeNull();
  });

  test("ignores teaching events that do not match the current workflow scope", () => {
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "browser", stage: "learning", summary: {} },
      stage: "learning",
      trialPreview: null,
    });

    act(() => {
      useTeachingStore.getState().applyEvent({
        eventId: "evt_preview",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: "rec_2",
        type: "trial.preview_requested",
        scope: { workflowId: "rec_2" },
        payload: {
          requestId: "preview_1",
          workflowId: "rec_2",
          trialId: "trial_1",
          summary: "桌面试用需要确认。",
          codePreview: "print('safe preview')",
          riskSummary: "将控制本机桌面。",
          expires_at: "2099-05-10T00:00:00Z",
          status: "pending",
        },
        createdAt: "2026-05-10T00:00:01Z",
      });
    });

    expect(useTeachingStore.getState().trialPreview).toBeNull();
  });

  test("keeps trial assistant replies visible once when headline and detail match", () => {
    const reply =
      "搜索成功！ 工具已将 **20 条搜索结果** 导出到文件 `E:\\code\\Exemplar\\python.txt`。\n\n请问这个结果符合你的预期吗？";
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "browser", stage: "trial_validation", summary: {} },
      stage: "trial_validation",
      messages: [],
      progressLog: [],
    });

    act(() => {
      useTeachingStore.getState().applyEvent({
        eventId: "evt_trial_reply",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: "rec_1",
        type: "trial.progress",
        scope: { workflowId: "rec_1" },
        payload: { status: "waiting_for_user", headline: reply, message: reply },
        createdAt: "2026-05-10T00:00:01Z",
      });
    });

    expect(useTeachingStore.getState().messages).toEqual([
      {
        from: "ai",
        agent: "trial",
        headline: reply,
        detail: undefined,
        error: false,
      },
    ]);
  });

  test("renders the full trial assistant reply including the final question", () => {
    const reply =
      "搜索成功！ 工具已将 **19 条搜索结果** 导出到文件 `E:\\code\\Exemplar\\北京天气.txt`。\n\n" +
      "以下是部分搜索结果预览：\n\n" +
      "| # | 标题 |\n|---|------|\n| 1 | 北京天气预报15天 - 中国天气网 |\n| 8 | 北京天气预报40天查询 |\n\n" +
      "共导出 **19 条**结果，包含标题和链接，已保存到 txt 文件中。\n\n" +
      "请问这个结果符合你的预期吗？";
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "browser", stage: "trial_validation", summary: {} },
      stage: "trial_validation",
      messages: [{ from: "ai", agent: "trial", headline: reply }],
      progressLog: [],
      busy: false,
    });

    render(<TrialStage />);

    expect(screen.getByText(/共导出/)).toBeInTheDocument();
    expect(screen.getByText("请问这个结果符合你的预期吗？")).toBeInTheDocument();
  });

  test("uses trial success progress for counts without showing raw succeeded status", () => {
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "browser", stage: "trial_validation", summary: {} },
      stage: "trial_validation",
      messages: [],
      progressLog: [],
      trialSuccessCount: 0,
    });

    act(() => {
      useTeachingStore.getState().applyEvent({
        eventId: "evt_trial_success",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: "rec_1",
        type: "trial.progress",
        scope: { workflowId: "rec_1" },
        payload: { status: "succeeded", published: false, successCount: 1 },
        createdAt: "2026-05-10T00:00:01Z",
      });
    });

    expect(useTeachingStore.getState().trialSuccessCount).toBe(1);
    expect(useTeachingStore.getState().messages).toEqual([]);
    expect(useTeachingStore.getState().progressLog).toEqual([]);
  });

  test("does not treat unrelated skill catalog events as the current teaching run", () => {
    useTeachingStore.setState({
      run: { workflowId: "rec_1", mode: "browser", stage: "trial_validation", summary: {} },
      stage: "trial_validation",
    });

    act(() => {
      useTeachingStore.getState().applyEvent({
        eventId: "evt_skill",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: "tool_2",
        type: "skills.changed",
        scope: { toolId: "tool_2" },
        payload: { reason: "catalog_invalidated", status: "published", toolId: "tool_2" },
        createdAt: "2026-05-10T00:00:01Z",
      });
    });

    expect(useTeachingStore.getState().stage).toBe("trial_validation");
  });
});
