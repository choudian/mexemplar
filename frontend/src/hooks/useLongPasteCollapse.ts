import { useCallback, useEffect, useState } from "react";

const LINE_THRESHOLD = 6;
const CHAR_THRESHOLD = 1200;
const PREVIEW_LINE_LIMIT = 6;

function countLogicalLines(text: string): number {
  if (text.length === 0) return 1;
  return text.split(/\r\n|\n|\r/).length;
}

export interface UseLongPasteCollapseOptions {
  draft: string;
  onDraftChange: (draft: string) => void;
  lineThreshold?: number;
  charThreshold?: number;
  resetWhenEmpty?: boolean;
}

export interface UseLongPasteCollapseReturn {
  isCollapsed: boolean;
  isQualified: boolean;
  previewLineLimit: number;
  handlePaste: (e: React.ClipboardEvent<HTMLTextAreaElement>) => void;
  expand: () => void;
  collapse: () => void;
  clear: () => void;
  resetOnSend: () => void;
}

export function useLongPasteCollapse({
  draft,
  onDraftChange,
  lineThreshold = LINE_THRESHOLD,
  charThreshold = CHAR_THRESHOLD,
  resetWhenEmpty = true,
}: UseLongPasteCollapseOptions): UseLongPasteCollapseReturn {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isQualified, setIsQualified] = useState(false);

  useEffect(() => {
    if (draft === "" && resetWhenEmpty) {
      setIsCollapsed(false);
      setIsQualified(false);
    }
  }, [draft, resetWhenEmpty]);

  function checkQualifies(text: string): boolean {
    return (
      countLogicalLines(text) > lineThreshold || text.length > charThreshold
    );
  }

  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const pasteText = e.clipboardData.getData("text/plain");
      if (!pasteText) return;

      const target = e.currentTarget ?? e.target;
      const start = target.selectionStart ?? 0;
      const end = target.selectionEnd ?? 0;
      const nextDraft =
        draft.slice(0, start) + pasteText + draft.slice(end);

      if (checkQualifies(nextDraft)) {
        e.preventDefault();
        onDraftChange(nextDraft);
        setIsCollapsed(true);
        setIsQualified(true);
      }
      // Non-qualifying paste: let default browser behavior handle it
    },
    [draft, onDraftChange, lineThreshold, charThreshold],
  );

  const expand = useCallback(() => {
    setIsCollapsed(false);
  }, []);

  const collapse = useCallback(() => {
    if (isQualified) {
      setIsCollapsed(true);
    }
  }, [isQualified]);

  const clear = useCallback(() => {
    onDraftChange("");
    setIsCollapsed(false);
    setIsQualified(false);
  }, [onDraftChange]);

  const resetOnSend = useCallback(() => {
    setIsCollapsed(false);
    setIsQualified(false);
  }, []);

  return {
    isCollapsed,
    isQualified,
    previewLineLimit: PREVIEW_LINE_LIMIT,
    handlePaste,
    expand,
    collapse,
    clear,
    resetOnSend,
  };
}
