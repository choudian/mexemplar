import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

import { ErrorToastHost } from "../../src/app/ErrorToastHost";
import { useAssistantStore } from "../../src/state/assistantStore";
import { useSettingsStore } from "../../src/state/settingsStore";
import { useToastStore } from "../../src/state/toastStore";

describe("ErrorToastHost", () => {
  beforeEach(() => {
    useToastStore.getState().clear();
    useAssistantStore.setState({ lastError: null });
    useSettingsStore.setState({ lastError: null });
  });

  afterEach(() => {
    useToastStore.getState().clear();
  });

  test("surfaces a store error as a toast", () => {
    render(<ErrorToastHost />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    act(() => {
      useAssistantStore.setState({ lastError: "无法加载对话列表。" });
    });

    expect(screen.getByText("无法加载对话列表。")).toBeInTheDocument();
  });

  test("collects errors from different stores into one stack", () => {
    render(<ErrorToastHost />);

    act(() => {
      useAssistantStore.setState({ lastError: "消息发送失败。" });
      useSettingsStore.setState({ lastError: "无法保存设置。" });
    });

    expect(screen.getByText("消息发送失败。")).toBeInTheDocument();
    expect(screen.getByText("无法保存设置。")).toBeInTheDocument();
  });

  test("dismisses a toast when the close button is clicked", () => {
    render(<ErrorToastHost />);
    act(() => {
      useSettingsStore.setState({ lastError: "无法加载设置。" });
    });
    expect(screen.getByText("无法加载设置。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭提示" }));
    expect(screen.queryByText("无法加载设置。")).not.toBeInTheDocument();
  });

  test("does not duplicate an identical consecutive error", () => {
    render(<ErrorToastHost />);
    act(() => {
      useAssistantStore.setState({ lastError: "消息发送失败。" });
    });
    act(() => {
      // 同一动作再次失败：清空再设回同一条，应去重为一条
      useAssistantStore.setState({ lastError: null });
      useAssistantStore.setState({ lastError: "消息发送失败。" });
    });

    expect(screen.getAllByText("消息发送失败。")).toHaveLength(1);
  });
});
