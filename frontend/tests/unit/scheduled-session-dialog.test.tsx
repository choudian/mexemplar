/**
 * 调度中心「查看这一轮」弹窗。
 *
 * 守三件容易回退的事：
 * - 调度投的那条 prompt 脚手架不能伪装成用户说过的话；
 * - waiting_user 的 run 发消息前必须先接管，否则它一直占着该任务的 active 槽位，
 *   下一次到点会被判成上轮没跑完而静默跳过；
 * - 弹窗有独立会话状态，别的会话的事件不许串进来。
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ScheduledSessionDialog from "../../src/screens/ScheduledScreen/ScheduledSessionDialog";
import { useScheduledSessionStore } from "../../src/state/scheduledSessionStore";
import type { ScheduledTaskItem, ScheduledTaskRunItem } from "../../src/api/scheduledTasks";
import type { UiEvent } from "../../src/api/client";

const listAssistantMessages = vi.fn();
const sendAssistantMessage = vi.fn();
const takeoverScheduledRun = vi.fn();

vi.mock("../../src/api/assistant", () => ({
  listAssistantMessages: (...args: unknown[]) => listAssistantMessages(...args),
  sendAssistantMessage: (...args: unknown[]) => sendAssistantMessage(...args),
}));

vi.mock("../../src/api/scheduledTasks", () => ({
  takeoverScheduledRun: (...args: unknown[]) => takeoverScheduledRun(...args),
}));

const TASK = {
  scheduledTaskId: "sch_1",
  title: "GitHub Trending 日/周/月榜单每日推送",
  status: "active",
} as unknown as ScheduledTaskItem;

function run(status: ScheduledTaskRunItem["status"]): ScheduledTaskRunItem {
  return {
    runId: "schr_1",
    scheduledTaskId: "sch_1",
    sessionId: "ast_sched",
    startedAt: "2026-08-11T07:50:00Z",
    finishedAt: null,
    summary: null,
    failureReason: null,
    status,
  } as ScheduledTaskRunItem;
}

const TRIGGER_MESSAGE = {
  sequence: 2,
  role: "user" as const,
  content:
    "[系统调度触发：立即执行]\n\n这是已存在定时任务的一次到点执行…\n<scheduled-task-instruction>\n查询 GitHub Trending 榜单\n</scheduled-task-instruction>",
  createdAt: "2026-08-11T07:50:00Z",
  rendering: "plain_text" as const,
};

const REPLY_MESSAGE = {
  sequence: 3,
  role: "assistant" as const,
  content: "# GitHub Trending 热门项目榜单",
  createdAt: "2026-08-11T07:55:17Z",
  rendering: "safe_markdown" as const,
};

beforeEach(() => {
  vi.clearAllMocks();
  useScheduledSessionStore.getState().close();
  listAssistantMessages.mockResolvedValue({
    items: [TRIGGER_MESSAGE, REPLY_MESSAGE],
    hasMoreBefore: false,
    nextBeforeSequence: null,
  });
  sendAssistantMessage.mockResolvedValue({ accepted: true, sessionId: "ast_sched" });
  takeoverScheduledRun.mockResolvedValue({ sessionId: "ast_sched", recoveryDraft: null });
});

async function openDialog(status: ScheduledTaskRunItem["status"] = "succeeded") {
  render(<ScheduledSessionDialog onOpenInAssistant={() => undefined} />);
  await act(async () => {
    await useScheduledSessionStore.getState().openRun(TASK, run(status));
  });
}

describe("调度中心会话弹窗", () => {
  it("调度投的触发消息标成自动触发，不伪装成用户说的话", async () => {
    await openDialog();

    await waitFor(() => expect(screen.getByText(/自动触发/)).toBeTruthy());
    // 内部 prompt 脚手架不该出现在界面上
    expect(screen.queryByText(/scheduled-task-instruction/)).toBeNull();
    expect(screen.queryByText(/系统调度触发/)).toBeNull();
    // 助理回复正常渲染
    expect(screen.getByText(/GitHub Trending 热门项目榜单/)).toBeTruthy();
    // 这一轮没有「你」说过的话，所以不该出现用户气泡署名
    expect(screen.queryByText("你")).toBeNull();
  });

  it("waiting_user 的 run 发消息前先接管，避免继续占住 active 槽位", async () => {
    await openDialog("waiting_user");
    await waitFor(() => expect(screen.getByText(/自动触发/)).toBeTruthy());

    act(() => useScheduledSessionStore.getState().setDraft("那就按周榜发我"));
    await act(async () => {
      await useScheduledSessionStore.getState().send();
    });

    expect(takeoverScheduledRun).toHaveBeenCalledWith("sch_1", "schr_1");
    expect(sendAssistantMessage).toHaveBeenCalledWith("ast_sched", "那就按周榜发我");
    // 接管后本地状态跟着回到运行中，输入框不再停留在等待态
    expect(useScheduledSessionStore.getState().run?.status).toBe("running");
  });

  it("已成功的 run 直接发消息，不做多余接管", async () => {
    await openDialog("succeeded");
    await waitFor(() => expect(screen.getByText(/自动触发/)).toBeTruthy());

    act(() => useScheduledSessionStore.getState().setDraft("再补一份月榜"));
    await act(async () => {
      await useScheduledSessionStore.getState().send();
    });

    expect(takeoverScheduledRun).not.toHaveBeenCalled();
    expect(sendAssistantMessage).toHaveBeenCalledWith("ast_sched", "再补一份月榜");
    expect(useScheduledSessionStore.getState().draft).toBe("");
  });

  it("别的会话的事件不串进这个弹窗", async () => {
    await openDialog();
    await waitFor(() => expect(screen.getByText(/自动触发/)).toBeTruthy());

    const foreign = {
      type: "assistant.message",
      scope: { sessionId: "ast_other" },
      payload: { sequence: 9, role: "assistant", content: "别的会话的回复", rendering: "plain_text" },
    } as unknown as UiEvent;
    act(() => useScheduledSessionStore.getState().applyEvent(foreign));

    expect(screen.queryByText("别的会话的回复")).toBeNull();
    expect(useScheduledSessionStore.getState().messages).toHaveLength(2);
  });

  it("本会话的新消息实时追加", async () => {
    await openDialog();
    await waitFor(() => expect(screen.getByText(/自动触发/)).toBeTruthy());

    const own = {
      type: "assistant.message",
      scope: { sessionId: "ast_sched" },
      payload: { sequence: 4, role: "assistant", content: "月榜也整理好了", rendering: "plain_text" },
    } as unknown as UiEvent;
    act(() => useScheduledSessionStore.getState().applyEvent(own));

    await waitFor(() => expect(screen.getByText("月榜也整理好了")).toBeTruthy());
  });

  it("需要接管的结局给出去主助理的出口，已成功的不给", async () => {
    const onOpen = vi.fn();
    render(<ScheduledSessionDialog onOpenInAssistant={onOpen} />);
    await act(async () => {
      await useScheduledSessionStore.getState().openRun(TASK, run("waiting_user"));
    });
    await waitFor(() => expect(screen.getByText("在主助理里继续")).toBeTruthy());
    fireEvent.click(screen.getByText("在主助理里继续"));
    expect(onOpen).toHaveBeenCalledWith("ast_sched");

    await act(async () => {
      await useScheduledSessionStore.getState().openRun(TASK, run("succeeded"));
    });
    expect(screen.queryByText("在主助理里继续")).toBeNull();
  });
});
