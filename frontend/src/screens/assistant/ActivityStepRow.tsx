import { StepIcon } from "./StepIcon";
import type { ActivityStepKind } from "../../state/assistantTypes";

type StepRowProps = {
  kind: ActivityStepKind;
  seq: number;
  toolName?: string | null;
  text: string;
};

/** 单条活动步骤行——共享于 ActivityTimeline（div）与 SubagentDetailDrawer（li）。
 * `seq` 是步骤排序键，由父列表用于 React key，行本身不渲染它。 */
export function ActivityStepRow({ kind, toolName, text }: StepRowProps): JSX.Element {
  return (
    <>
      <span className="assistant-step-icon">
        <StepIcon kind={kind} />
      </span>
      <span className="assistant-step-text">
        {toolName ? <code>{toolName}</code> : null}
        {text}
      </span>
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
