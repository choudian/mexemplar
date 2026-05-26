import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import MessageComposer from "../../src/screens/assistant/MessageComposer";
import {
  CHARS_1201,
  EXACTLY_1200_CHARS,
  SEVEN_LINE_TEXT,
  SIX_LINE_TEXT,
} from "../fixtures/longPasteFixtures";

function renderMessageComposer({
  draft = "",
  sending = false,
  autoApprove = false,
  onDraftChange = vi.fn(),
  onSend = vi.fn(),
  onToggleAutoApprove = vi.fn(),
} = {}) {
  const result = render(
    <MessageComposer
      draft={draft}
      sending={sending}
      autoApprove={autoApprove}
      onDraftChange={onDraftChange}
      onSend={onSend}
      onToggleAutoApprove={onToggleAutoApprove}
    />,
  );

  const textarea = screen.getByLabelText("输入消息") as HTMLTextAreaElement;
  return { ...result, textarea, onDraftChange, onSend };
}

function pasteText(textarea: HTMLTextAreaElement, text: string) {
  // Simulate a paste event with clipboard data
  const pasteEvent = new Event("paste", { bubbles: true });
  Object.defineProperty(pasteEvent, "clipboardData", {
    value: { getData: (type: string) => (type === "text/plain" ? text : "") },
  });
  fireEvent(textarea, pasteEvent);
}

function StatefulMessageComposer({ acceptSend = false }: { acceptSend?: boolean }): JSX.Element {
  const [draft, setDraft] = useState("");
  return (
    <MessageComposer
      draft={draft}
      sending={false}
      autoApprove={false}
      onDraftChange={setDraft}
      onSend={() => {
        if (acceptSend) setDraft("");
      }}
      onToggleAutoApprove={vi.fn()}
    />
  );
}

describe("Assistant MessageComposer — long paste", () => {
  test("qualifying 7-line paste shows collapsed preview", () => {
    const onDraftChange = vi.fn();
    const { textarea, container } = renderMessageComposer({ onDraftChange });

    pasteText(textarea, SEVEN_LINE_TEXT);

    // Should show a preview element indicating collapsed state
    const preview = container.querySelector("[data-long-paste-preview]");
    expect(preview).toBeTruthy();
  });

  test("non-qualifying 6-line paste stays as normal textarea", () => {
    const { textarea, container } = renderMessageComposer();

    pasteText(textarea, SIX_LINE_TEXT);

    const preview = container.querySelector("[data-long-paste-preview]");
    expect(preview).toBeNull();
  });

  test("qualifying 1201-char single-line paste shows collapsed preview", () => {
    render(<StatefulMessageComposer />);
    const textarea = screen.getByLabelText("输入消息") as HTMLTextAreaElement;

    pasteText(textarea, CHARS_1201);

    expect(screen.getByText(/内容已省略（共 1 行，1201 字符）/)).toBeInTheDocument();
  });

  test("exactly 1200 chars does not collapse", () => {
    const { textarea, container } = renderMessageComposer();

    pasteText(textarea, EXACTLY_1200_CHARS);

    const preview = container.querySelector("[data-long-paste-preview]");
    expect(preview).toBeNull();
  });

  test("send button sends the full draft, not the preview", () => {
    const onSend = vi.fn();
    const onDraftChange = vi.fn();
    renderMessageComposer({
      draft: SEVEN_LINE_TEXT,
      onSend,
      onDraftChange,
    });

    // Since draft is already the long text, we trigger send
    const sendButton = screen.getByRole("button", { name: /发送/ });
    fireEvent.click(sendButton);

    expect(onSend).toHaveBeenCalled();
  });

  test("expand restores an editable full textarea", () => {
    render(<StatefulMessageComposer />);
    pasteText(screen.getByLabelText("输入消息") as HTMLTextAreaElement, SEVEN_LINE_TEXT);
    fireEvent.click(screen.getByRole("button", { name: "展开全部" }));

    const expanded = screen.getByLabelText("完整文本内容");
    expect(expanded).toHaveValue(SEVEN_LINE_TEXT);
    fireEvent.change(expanded, { target: { value: `${SEVEN_LINE_TEXT}\n追加内容` } });
    expect(expanded).toHaveValue(`${SEVEN_LINE_TEXT}\n追加内容`);
  });

  test("clear resets draft and exits preview", () => {
    render(<StatefulMessageComposer />);
    pasteText(screen.getByLabelText("输入消息") as HTMLTextAreaElement, SEVEN_LINE_TEXT);
    fireEvent.click(screen.getByRole("button", { name: "清除内容" }));

    expect(screen.getByLabelText("输入消息")).toHaveValue("");
    expect(screen.queryByLabelText("长文本预览，完整内容已保留")).not.toBeInTheDocument();
  });

  test("keyboard Tab reaches send and clear in collapsed preview", () => {
    render(<StatefulMessageComposer />);
    pasteText(screen.getByLabelText("输入消息") as HTMLTextAreaElement, SEVEN_LINE_TEXT);

    const clear = screen.getByRole("button", { name: "清除内容" });
    const send = screen.getByRole("button", { name: "发送" });
    clear.focus();
    expect(clear).toHaveFocus();
    send.focus();
    expect(send).toHaveFocus();
  });

  test("retains collapsed interaction state when a send is not accepted", () => {
    render(<StatefulMessageComposer />);
    pasteText(screen.getByLabelText("输入消息") as HTMLTextAreaElement, SEVEN_LINE_TEXT);
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(screen.getByLabelText("长文本预览，完整内容已保留")).toBeInTheDocument();
  });

  test("clears collapsed state after an accepted send clears the draft", () => {
    render(<StatefulMessageComposer acceptSend />);
    pasteText(screen.getByLabelText("输入消息") as HTMLTextAreaElement, SEVEN_LINE_TEXT);
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(screen.getByLabelText("输入消息")).toHaveValue("");
    expect(screen.queryByLabelText("长文本预览，完整内容已保留")).not.toBeInTheDocument();
  });
});
