import { Bot, X } from "lucide-react";
import { useEffect, useState } from "react";

import { getSubagentTranscript } from "../../api/assistant";
import type { AssistantActivityStep } from "../../api/assistant";
import type { Subagent } from "../../state/assistantStore";
import { ActivityStepRow, LoadableContent } from "./ActivityStepRow";

/** 子任务完整过程抽屉（US4）：双击卡片打开，经 transcript 重建该子助手自己的过程（含工具）。 */
function SubagentDetailDrawer({
  sessionId,
  subagent,
  onClose,
}: {
  sessionId: string;
  subagent: Subagent;
  onClose: () => void;
}): JSX.Element {
  const [steps, setSteps] = useState<AssistantActivityStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 重试通过 bump 这个 key 复用同一条 effect 抓取路径（含卸载守卫），不再另写一条并行链。
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setSteps([]);
    getSubagentTranscript(sessionId, subagent.subagentId)
      .then((transcript) => {
        if (active) setSteps(transcript.steps);
      })
      .catch(() => {
        if (active) {
          setSteps([]);
          setError("过程加载失败，请重试。");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [sessionId, subagent.subagentId, reloadKey]);

  const handleRetry = () => setReloadKey((key) => key + 1);

  return (
    <div className="assistant-drawer-scrim" onClick={onClose}>
      <aside
        className="assistant-drawer"
        role="dialog"
        aria-label={`子助手详情：${subagent.label}`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="assistant-drawer-head">
          <div className="assistant-drawer-title">
            <Bot size={16} />
            <div>
              <strong>{subagent.label}</strong>
              <small>{subagent.task}</small>
            </div>
          </div>
          <button type="button" className="me-icon-button" aria-label="关闭" onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <div className="assistant-drawer-body me-scroll">
          <p className="assistant-drawer-hint">这是这个子助手自己的完整过程（包含它调用的工具）。</p>
          {loading || error ? (
            <LoadableContent loading={loading} error={error} emptyLabel="" onRetry={handleRetry} />
          ) : steps.length === 0 ? (
            <div className="assistant-drawer-empty">还没有步骤。</div>
          ) : (
            <ol className="assistant-steplist">
              {steps.map((step) => (
                <li key={step.seq} className="assistant-step" data-kind={step.kind}>
                  <ActivityStepRow kind={step.kind} seq={step.seq} toolName={step.toolName} text={step.text} />
                </li>
              ))}
            </ol>
          )}
          {subagent.lastOutput ? (
            <div className="assistant-drawer-output">
              <span>产出</span>
              <p>{subagent.lastOutput}</p>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

export default SubagentDetailDrawer;
