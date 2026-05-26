import { useCallback, useRef } from "react";

import type { UseLongPasteCollapseReturn } from "../hooks/useLongPasteCollapse";

interface LongPastePreviewProps {
  draft: string;
  collapseState: UseLongPasteCollapseReturn;
  onDraftChange: (draft: string) => void;
  onSend: () => void;
  sendDisabled?: boolean;
  editingDisabled?: boolean;
}

function getPreviewLines(text: string, limit: number): string {
  const lines = text.split(/\r\n|\n|\r/);
  return lines.slice(0, limit).join("\n");
}

function getLineCount(text: string): number {
  if (text.length === 0) return 1;
  return text.split(/\r\n|\n|\r/).length;
}

function getCharCount(text: string): number {
  return text.length;
}

export function LongPastePreview({
  draft,
  collapseState,
  onDraftChange,
  onSend,
  sendDisabled = false,
  editingDisabled = false,
}: LongPastePreviewProps): JSX.Element {
  const { isCollapsed, isQualified, previewLineLimit, expand, collapse, clear } = collapseState;
  const expandRef = useRef<HTMLButtonElement>(null);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        if (isCollapsed) {
          expand();
        }
      }
    },
    [isCollapsed, expand],
  );

  if (!isQualified) return <></>;

  const lines = getLineCount(draft);
  const chars = getCharCount(draft);
  const omittedLines = isCollapsed ? Math.max(0, lines - previewLineLimit) : 0;

  return (
    <div
      className="long-paste-preview"
      data-long-paste-preview=""
      onKeyDown={handleKeyDown}
    >
      {isCollapsed ? (
        <div
          className="long-paste-preview-collapsed"
          role="region"
          aria-label="长文本预览，完整内容已保留"
          aria-expanded="false"
        >
          <pre className="long-paste-preview-text">
            {getPreviewLines(draft, previewLineLimit)}
          </pre>
          <div className="long-paste-preview-omitted">
            {omittedLines > 0
              ? `...还有 ${omittedLines} 行未显示（共 ${lines} 行，${chars} 字符）`
              : `...内容已省略（共 ${lines} 行，${chars} 字符）`}
          </div>
          <div className="long-paste-preview-actions">
            <button
              ref={expandRef}
              className="long-paste-expand-btn"
              onClick={expand}
              aria-expanded="false"
              aria-controls="long-paste-preview-content"
              type="button"
            >
              展开全部
            </button>
            <button
              className="long-paste-clear-btn"
              onClick={clear}
              type="button"
            >
              清除内容
            </button>
            <button
              className="long-paste-send-btn"
              onClick={onSend}
              disabled={sendDisabled}
              type="button"
            >
              发送
            </button>
          </div>
        </div>
      ) : (
        <div
          className="long-paste-preview-expanded"
          id="long-paste-preview-content"
          role="region"
          aria-label="长文本完整内容"
          aria-expanded="true"
        >
          <div className="long-paste-expanded-header">
            长文本（{lines} 行，{chars} 字符）
          </div>
          <textarea
            className="long-paste-expanded-textarea"
            disabled={editingDisabled}
            onChange={(event) => onDraftChange(event.currentTarget.value)}
            rows={Math.min(lines, 12)}
            value={draft}
            aria-label="完整文本内容"
          />
          <div className="long-paste-preview-actions">
            <button
              className="long-paste-collapse-btn"
              onClick={collapse}
              aria-expanded="true"
              aria-controls="long-paste-preview-content"
              type="button"
            >
              收起预览
            </button>
            <button
              className="long-paste-clear-btn"
              onClick={clear}
              type="button"
            >
              清除内容
            </button>
            <button
              className="long-paste-send-btn"
              onClick={onSend}
              disabled={sendDisabled}
              type="button"
            >
              发送
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
