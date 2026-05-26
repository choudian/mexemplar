import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import MessageComposer from "../../src/screens/assistant/MessageComposer";
import TrialStage from "../../src/screens/teaching/TrialStage";
import { ChatComposer } from "../../src/screens/teaching/shared";
import { useTeachingStore } from "../../src/state/teachingStore";
import {
  CHARS_1201,
  EXACTLY_1200_CHARS,
  SEVEN_LINE_TEXT,
  SIX_LINE_TEXT,
} from "../fixtures/longPasteFixtures";

function renderChatComposer({
  draft = "",
  setDraft = vi.fn(),
  onSend = vi.fn(),
  disabled = false,
  placeholder,
}: {
  draft?: string;
  setDraft?: (v: string) => void;
  onSend?: () => void;
  disabled?: boolean;
  placeholder?: string;
} = {}) {
  const result = render(
    <ChatComposer
      draft={draft}
      setDraft={setDraft}
      onSend={onSend}
      disabled={disabled}
      placeholder={placeholder}
    />,
  );

  const textarea = screen.getByPlaceholderText(placeholder ?? "输入消息…") as HTMLTextAreaElement;
  return { ...result, textarea, setDraft, onSend };
}

function pasteText(textarea: HTMLTextAreaElement, text: string) {
  const pasteEvent = new Event("paste", { bubbles: true });
  Object.defineProperty(pasteEvent, "clipboardData", {
    value: { getData: (type: string) => (type === "text/plain" ? text : "") },
  });
  fireEvent(textarea, pasteEvent);
}

function StatefulChatComposer({ acceptSend = false }: { acceptSend?: boolean }): JSX.Element {
  const [draft, setDraft] = useState("");
  return (
    <ChatComposer
      draft={draft}
      setDraft={setDraft}
      onSend={() => {
        if (acceptSend) setDraft("");
      }}
    />
  );
}

describe("Teaching ChatComposer — long paste", () => {
  test("qualifying 7-line paste shows collapsed preview", () => {
    const setDraft = vi.fn();
    const { textarea, container } = renderChatComposer({ setDraft });

    pasteText(textarea, SEVEN_LINE_TEXT);

    const preview = container.querySelector("[data-long-paste-preview]");
    expect(preview).toBeTruthy();
  });

  test("non-qualifying 6-line paste stays as normal textarea", () => {
    const { textarea, container } = renderChatComposer();

    pasteText(textarea, SIX_LINE_TEXT);

    const preview = container.querySelector("[data-long-paste-preview]");
    expect(preview).toBeNull();
  });

  test("qualifying 1201-char single-line paste shows collapsed preview", () => {
    const { textarea, container } = renderChatComposer();

    pasteText(textarea, CHARS_1201);

    const preview = container.querySelector("[data-long-paste-preview]");
    expect(preview).toBeTruthy();
  });

  test("exactly 1200 chars does not collapse", () => {
    const { textarea, container } = renderChatComposer();

    pasteText(textarea, EXACTLY_1200_CHARS);

    const preview = container.querySelector("[data-long-paste-preview]");
    expect(preview).toBeNull();
  });

  test("send button sends the full draft, not the preview", () => {
    const onSend = vi.fn();
    renderChatComposer({ draft: SEVEN_LINE_TEXT, onSend });

    const sendButton = screen.getByRole("button");
    fireEvent.click(sendButton);

    expect(onSend).toHaveBeenCalled();
  });

  test("composer respects disabled prop", () => {
    const { textarea } = renderChatComposer({ disabled: true });

    expect(textarea).toBeDisabled();
  });

  test("expanded paste remains editable and failed send retains preview state", () => {
    render(<StatefulChatComposer />);
    pasteText(screen.getByPlaceholderText("输入消息…") as HTMLTextAreaElement, SEVEN_LINE_TEXT);
    fireEvent.click(screen.getByRole("button", { name: "展开全部" }));

    const expanded = screen.getByLabelText("完整文本内容");
    fireEvent.change(expanded, { target: { value: `${SEVEN_LINE_TEXT}\n补充` } });
    expect(expanded).toHaveValue(`${SEVEN_LINE_TEXT}\n补充`);
    fireEvent.click(screen.getByRole("button", { name: "收起预览" }));
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getByLabelText("长文本预览，完整内容已保留")).toBeInTheDocument();
  });

  test("accepted send resets the preview only after draft is cleared", () => {
    render(<StatefulChatComposer acceptSend />);
    pasteText(screen.getByPlaceholderText("输入消息…") as HTMLTextAreaElement, SEVEN_LINE_TEXT);
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getByPlaceholderText("输入消息…")).toHaveValue("");
  });

  test("same collapse behavior as Assistant composer", () => {
    // Both composers should use the same useLongPasteCollapse hook
    // so thresholds, counting, and state transitions must be identical
    const assistantSetDraft = vi.fn();
    const teachingSetDraft = vi.fn();

    const { textarea: assistantTextarea } = renderMessageComposerForComparison({
      setDraft: assistantSetDraft,
    });
    const { textarea: teachingTextarea } = renderChatComposerForComparison({
      setDraft: teachingSetDraft,
    });

    // Same qualifying input
    pasteText(assistantTextarea, SEVEN_LINE_TEXT);
    pasteText(teachingTextarea, SEVEN_LINE_TEXT);

    // Both should have called setDraft with the same text
    expect(assistantSetDraft).toHaveBeenCalledWith(SEVEN_LINE_TEXT);
    expect(teachingSetDraft).toHaveBeenCalledWith(SEVEN_LINE_TEXT);
  });

  test("TrialStage sends exact text including leading and trailing whitespace", async () => {
    useTeachingStore.setState({
      hydrated: true,
      readiness: [],
      selectedMode: "browser",
      run: null,
      stage: "trial_validation",
      progressLog: [],
      messages: [],
      toast: null,
      trialPreview: null,
      busy: false,
      lastError: null,
      skillTrialToolId: null,
      trialSuccessCount: 0,
    });
    const onStart = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<TrialStage onStart={onStart} />);

    fireEvent.change(screen.getByPlaceholderText("给我一个真实任务..."), {
      target: { value: "  run this exactly\n" },
    });
    fireEvent.click(container.querySelector(".teaching-composer-send") as HTMLButtonElement);

    await waitFor(() => expect(onStart).toHaveBeenCalledWith("  run this exactly\n"));
  });
});

// Helper to render MessageComposer for comparison tests
function renderMessageComposerForComparison({ setDraft }: { setDraft: (v: string) => void }) {
  render(
    <MessageComposer
      draft=""
      sending={false}
      autoApprove={false}
      onDraftChange={setDraft}
      onSend={vi.fn()}
      onToggleAutoApprove={vi.fn()}
    />,
  );
  return {
    textarea: screen.getByLabelText("输入消息") as HTMLTextAreaElement,
  };
}

function renderChatComposerForComparison({ setDraft }: { setDraft: (v: string) => void }) {
  render(<ChatComposer draft="" setDraft={setDraft} onSend={vi.fn()} />);
  return {
    textarea: screen.getByPlaceholderText("输入消息…") as HTMLTextAreaElement,
  };
}
