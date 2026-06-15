import { Bug, Pencil, RotateCcw, Send, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { AssistantMessageFailure } from "../../api/assistant";

interface AssistantFailureCardProps {
  failure: AssistantMessageFailure;
  originalContent: string;
  loading: boolean;
  onRetry: (content?: string) => void;
  onDebug: () => void;
}

export default function AssistantFailureCard({
  failure,
  originalContent,
  loading,
  onRetry,
  onDebug,
}: AssistantFailureCardProps): JSX.Element {
  const [editing, setEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(originalContent);

  useEffect(() => {
    if (!editing) setEditedContent(originalContent);
  }, [editing, originalContent]);

  const submitEdited = () => {
    if (!editedContent.trim() || loading) return;
    onRetry(editedContent);
  };

  return (
    <section className="assistant-failure-card" aria-label="消息恢复操作">
      <div className="assistant-failure-card-heading">
        <span className="assistant-failure-pulse" aria-hidden="true" />
        <strong>{loading ? "正在重新处理" : "这条消息没有完成"}</strong>
        <span>第 {failure.attemptCount} 次尝试</span>
      </div>
      <p>{failure.message}</p>
      <small>{failure.suggestion}</small>

      {editing ? (
        <div className="assistant-failure-editor">
          <label htmlFor={`failure-edit-${failure.failedAt}`}>编辑后重试</label>
          <textarea
            id={`failure-edit-${failure.failedAt}`}
            value={editedContent}
            disabled={loading}
            onChange={(event) => setEditedContent(event.currentTarget.value)}
            rows={3}
          />
          <div className="assistant-failure-actions">
            <button
              type="button"
              className="assistant-failure-action assistant-failure-action-primary"
              disabled={loading || !editedContent.trim()}
              onClick={submitEdited}
            >
              <Send size={13} />
              {loading ? "处理中" : "提交重试"}
            </button>
            <button
              type="button"
              className="assistant-failure-action"
              disabled={loading}
              onClick={() => setEditing(false)}
            >
              <X size={13} />
              取消
            </button>
          </div>
        </div>
      ) : (
        <div className="assistant-failure-actions">
          <button
            type="button"
            className="assistant-failure-action assistant-failure-action-primary"
            disabled={loading}
            onClick={() => onRetry()}
          >
            <RotateCcw size={13} />
            {loading ? "处理中" : "重试"}
          </button>
          <button
            type="button"
            className="assistant-failure-action"
            disabled={loading}
            onClick={() => setEditing(true)}
          >
            <Pencil size={13} />
            编辑后重试
          </button>
          <button
            type="button"
            className="assistant-failure-action"
            disabled={loading}
            onClick={onDebug}
          >
            <Bug size={13} />
            查看调试信息
          </button>
        </div>
      )}
    </section>
  );
}
