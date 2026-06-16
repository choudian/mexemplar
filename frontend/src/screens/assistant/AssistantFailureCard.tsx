import { Loader2, Pencil, RotateCcw, X } from "lucide-react";

import type { AssistantMessageFailure } from "../../api/assistant";

interface AssistantFailureCardProps {
  failure: AssistantMessageFailure;
  loading: boolean;
  onRetry: () => void;
  editing: boolean;
  onStartEdit: () => void;
  onSubmitEdit: () => void;
  onCancelEdit: () => void;
}

export default function AssistantFailureCard({
  failure,
  loading,
  onRetry,
  editing,
  onStartEdit,
  onSubmitEdit,
  onCancelEdit,
}: AssistantFailureCardProps): JSX.Element {
  // 编辑态：可编辑框已就地渲染在用户气泡里（见 AssistantScreen），
  // 失败卡这里只放提交 / 取消，贴在气泡下方。
  if (editing) {
    return (
      <section className="assistant-failure-card assistant-failure-card-editing" aria-label="消息恢复操作">
        <div className="assistant-failure-actions">
          <button
            type="button"
            className="assistant-failure-action assistant-failure-action-primary"
            disabled={loading}
            onClick={onSubmitEdit}
          >
            {loading ? "处理中" : "提交重试"}
          </button>
          <button
            type="button"
            className="assistant-failure-action"
            disabled={loading}
            onClick={onCancelEdit}
          >
            <X size={13} aria-hidden="true" />
            取消
          </button>
        </div>
      </section>
    );
  }

  // 默认态：单行紧凑状态条——状态点 + 一句话 + icon 动作。
  // 文案节点与 aria-label 是既有单测/e2e 的断言依据，改动时必须保留。
  const retryLabel = loading ? "处理中" : "重试";

  return (
    <section className="assistant-failure-card" aria-label="消息恢复操作">
      <div className="assistant-failure-row">
        <div
          className="assistant-failure-status"
          title={`${failure.message}${failure.suggestion ? ` ${failure.suggestion}` : ""}`}
        >
          <span className="assistant-failure-pulse" aria-hidden="true" />
          <strong>{loading ? "正在重新处理" : "这条消息没有完成"}</strong>
          <span className="assistant-failure-attempt">第 {failure.attemptCount} 次尝试</span>
        </div>
        <div className="assistant-failure-actions">
          <button
            type="button"
            className="assistant-failure-action assistant-failure-action-icon assistant-failure-action-primary"
            disabled={loading}
            onClick={onRetry}
            aria-label={retryLabel}
            title={retryLabel}
          >
            {loading ? (
              <Loader2 size={14} aria-hidden="true" className="assistant-spin" />
            ) : (
              <RotateCcw size={14} aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            className="assistant-failure-action assistant-failure-action-icon"
            disabled={loading}
            onClick={onStartEdit}
            aria-label="编辑后重试"
            title="编辑后重试"
          >
            <Pencil size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
    </section>
  );
}
