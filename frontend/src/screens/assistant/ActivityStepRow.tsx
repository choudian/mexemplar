import { Lock } from "lucide-react";
import { useState } from "react";

import { StepIcon } from "./StepIcon";
import type { ActivityStepKind } from "../../state/assistantTypes";

type StepRowProps = {
  kind: ActivityStepKind;
  seq: number;
  toolName?: string | null;
  text: string;
  redacted?: boolean;
};

/**
 * 排版美化（保留原文，不改语义）：能解析的 JSON 缩进展示；否则把字面转义的换行/制表符还原成真排版。
 * 不解析工具语义、不丢字段——只让原始参数/结果看起来整齐。
 */
function prettyStepText(text: string): string {
  const trimmed = text.trim();
  if (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch {
      // 不是合法 JSON，按普通文本处理
    }
  }
  return text.replace(/\\r\\n/g, "\n").replace(/\\n/g, "\n").replace(/\\t/g, "\t");
}

/** 单条活动步骤行——共享于 ActivityTimeline（div）与 SubagentDetailDrawer（li）。
 * `seq` 是步骤排序键，由父列表用于 React key，行本身不渲染它。 */
export function ActivityStepRow({ kind, toolName, text, redacted = false }: StepRowProps): JSX.Element {
  const [revealed, setRevealed] = useState(false);
  const formatted = prettyStepText(text);
  const multiline = formatted.includes("\n");
  const hidden = redacted && !revealed;
  return (
    <>
      <span className="assistant-step-icon">
        {redacted ? <Lock size={13} /> : <StepIcon kind={kind} />}
      </span>
      <div className="assistant-step-text">
        {toolName ? <code>{toolName}</code> : null}
        {hidden ? (
          <span
            className="assistant-step-redacted"
            role="button"
            tabIndex={0}
            title="内容含敏感信息（命令/代码/密钥等），默认隐藏。双击或按回车查看原文。"
            onDoubleClick={() => setRevealed(true)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                setRevealed(true);
              }
            }}
          >
            内容已隐藏 · 双击查看
          </span>
        ) : multiline ? (
          <pre className="assistant-step-pre me-scroll">{formatted}</pre>
        ) : (
          <span className="assistant-step-inline">{formatted}</span>
        )}
      </div>
    </>
  );
}

/** 三态内容区：加载中 / 错误+重试 / 空状态。共享于 ActivityTimeline 与 SubagentDetailDrawer。 */
export function LoadableContent({
  loading,
  error,
  onRetry,
}: {
  loading: boolean;
  error: string | null;
  emptyLabel: string;
  onRetry: () => void;
}): JSX.Element | null {
  if (loading) {
    return <div className="assistant-drawer-empty">正在加载…</div>;
  }
  if (error) {
    return (
      <div className="assistant-drawer-empty" role="alert">
        <span>{error}</span>
        <button type="button" className="me-link-button" onClick={onRetry}>
          重试
        </button>
      </div>
    );
  }
  return null;
}
