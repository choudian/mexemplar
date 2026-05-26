import { act, renderHook } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import {
  CHARS_1201,
  countLogicalLines,
  EXACTLY_1200_CHARS,
  MIXED_NEWLINE_TEXT,
  qualifiesForCollapse,
  SEVEN_LINE_TEXT,
  SIX_LINE_TEXT,
  WITH_EMPTY_LINES,
} from "../fixtures/longPasteFixtures";

// We test the hook's expected behavior based on contract thresholds.
// The hook module will be created at frontend/src/hooks/useLongPasteCollapse.ts

describe("useLongPasteCollapse — threshold boundaries", () => {
  test("7 logical lines qualifies for collapse", () => {
    expect(countLogicalLines(SEVEN_LINE_TEXT)).toBe(7);
    expect(qualifiesForCollapse(SEVEN_LINE_TEXT)).toBe(true);
  });

  test("6 logical lines does NOT qualify by line count alone", () => {
    expect(countLogicalLines(SIX_LINE_TEXT)).toBe(6);
    expect(qualifiesForCollapse(SIX_LINE_TEXT)).toBe(false);
  });

  test("1201 code units single line qualifies by character threshold", () => {
    expect(CHARS_1201.length).toBe(1201);
    expect(qualifiesForCollapse(CHARS_1201)).toBe(true);
  });

  test("exactly 1200 code units does NOT qualify by character threshold alone", () => {
    expect(EXACTLY_1200_CHARS.length).toBe(1200);
    expect(qualifiesForCollapse(EXACTLY_1200_CHARS)).toBe(false);
  });

  test("6 lines + 1201 chars qualifies (character threshold met)", () => {
    const sixLinesLong = SIX_LINE_TEXT + "\n" + "a".repeat(1201);
    expect(qualifiesForCollapse(sixLinesLong)).toBe(true);
  });

  test("mixed newlines (\\r\\n and \\n) counted correctly as 7 lines", () => {
    expect(countLogicalLines(MIXED_NEWLINE_TEXT)).toBe(7);
    expect(qualifiesForCollapse(MIXED_NEWLINE_TEXT)).toBe(true);
  });

  test("empty lines are counted — 7 logical lines including blanks", () => {
    expect(countLogicalLines(WITH_EMPTY_LINES)).toBe(7);
    expect(qualifiesForCollapse(WITH_EMPTY_LINES)).toBe(true);
  });

  test("empty string is 1 line and does not qualify", () => {
    expect(countLogicalLines("")).toBe(1);
    expect(qualifiesForCollapse("")).toBe(false);
  });

  test("single short line does not qualify", () => {
    expect(qualifiesForCollapse("hello")).toBe(false);
  });
});

describe("useLongPasteCollapse — selection preservation", () => {
  function makePasteEvent(text: string, start: number, end: number) {
    return {
      clipboardData: {
        getData: (type: string) => (type === "text/plain" ? text : ""),
      },
      preventDefault: vi.fn(),
      target: { selectionStart: start, selectionEnd: end },
    } as unknown as React.ClipboardEvent<HTMLTextAreaElement>;
  }

  test("middle-selection paste preserves before and after text", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "Hello world goodbye",
        onDraftChange,
      }),
    );

    // Paste qualifying text replacing selection "world" (pos 6..11)
    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT, 6, 11));
    });

    expect(onDraftChange).toHaveBeenCalledWith(`Hello ${SEVEN_LINE_TEXT} goodbye`);
  });

  test("paste at end of existing draft appends", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "existing",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT, 8, 8));
    });

    expect(onDraftChange).toHaveBeenCalledWith("existing" + SEVEN_LINE_TEXT);
  });

  test("paste at start of existing draft prepends", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "suffix",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT, 0, 0));
    });

    expect(onDraftChange).toHaveBeenCalledWith(SEVEN_LINE_TEXT + "suffix");
  });
});

describe("useLongPasteCollapse — state transitions", () => {
  function makePasteEvent(text: string) {
    return {
      clipboardData: {
        getData: (type: string) => (type === "text/plain" ? text : ""),
      },
      preventDefault: vi.fn(),
      target: { selectionStart: 0, selectionEnd: 0 },
    } as unknown as React.ClipboardEvent<HTMLTextAreaElement>;
  }

  test("qualifying paste enters collapsed state", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "",
        onDraftChange,
      }),
    );

    expect(result.current.isCollapsed).toBe(false);

    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT));
    });

    expect(result.current.isCollapsed).toBe(true);
    expect(result.current.isQualified).toBe(true);
  });

  test("non-qualifying paste does NOT collapse", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(SIX_LINE_TEXT));
    });

    expect(result.current.isCollapsed).toBe(false);
    expect(result.current.isQualified).toBe(false);
  });

  test("expand from collapsed", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT));
    });
    expect(result.current.isCollapsed).toBe(true);

    act(() => {
      result.current.expand();
    });
    expect(result.current.isCollapsed).toBe(false);
    expect(result.current.isQualified).toBe(true);
  });

  test("collapse from expanded", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT));
    });
    act(() => {
      result.current.expand();
    });

    act(() => {
      result.current.collapse();
    });
    expect(result.current.isCollapsed).toBe(true);
  });

  test("clear resets to normal state", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT));
    });
    expect(result.current.isCollapsed).toBe(true);

    act(() => {
      result.current.clear();
    });
    expect(result.current.isCollapsed).toBe(false);
    expect(result.current.isQualified).toBe(false);
    expect(onDraftChange).toHaveBeenCalledWith("");
  });

  test("resetOnSend returns to normal state", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT));
    });

    act(() => {
      result.current.resetOnSend();
    });
    expect(result.current.isCollapsed).toBe(false);
    expect(result.current.isQualified).toBe(false);
  });

  test("manual typing does NOT trigger collapse", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const longManual = "a".repeat(1300);
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: longManual,
        onDraftChange,
      }),
    );

    // Even with long draft, if not triggered by paste, should not collapse
    expect(result.current.isCollapsed).toBe(false);
    expect(result.current.isQualified).toBe(false);
  });

  test("draft change resets qualified state when not in collapsed/expanded", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(
      ({ draft }) => useLongPasteCollapse({ draft, onDraftChange }),
      { initialProps: { draft: "" } },
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(SEVEN_LINE_TEXT));
    });
    expect(result.current.isQualified).toBe(true);

    // Reset (simulating send)
    act(() => {
      result.current.resetOnSend();
    });

    // After reset, qualified should be false even though draft is still long
    expect(result.current.isQualified).toBe(false);
  });
});

describe("useLongPasteCollapse — newline edge cases", () => {
  function makePasteEvent(text: string) {
    return {
      clipboardData: {
        getData: (type: string) => (type === "text/plain" ? text : ""),
      },
      preventDefault: vi.fn(),
      target: { selectionStart: 0, selectionEnd: 0 },
    } as unknown as React.ClipboardEvent<HTMLTextAreaElement>;
  }

  test("\\r only newlines counted correctly", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const carriageReturnText = "a\rb\rc\rd\re\rf\rg";
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(carriageReturnText));
    });

    expect(result.current.isCollapsed).toBe(true);
    expect(countLogicalLines(carriageReturnText)).toBe(7);
  });

  test("trailing newline still counts as part of last line", async () => {
    // "line1\nline2\n" splits to ["line1", "line2", ""] = 3 lines
    const text = "a\nb\n";
    expect(countLogicalLines(text)).toBe(3);
  });

  test("paste preserves mixed \\r\\n exactly in draft", async () => {
    const { useLongPasteCollapse } = await import("../../src/hooks/useLongPasteCollapse");
    const onDraftChange = vi.fn();
    const { result } = renderHook(() =>
      useLongPasteCollapse({
        draft: "",
        onDraftChange,
      }),
    );

    act(() => {
      result.current.handlePaste(makePasteEvent(MIXED_NEWLINE_TEXT));
    });

    expect(onDraftChange).toHaveBeenCalledWith(MIXED_NEWLINE_TEXT);
  });
});
