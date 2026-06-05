import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getSubagentTranscript } from "../../api/assistant";
import type { AssistantActivityStep } from "../../api/assistant";
import type { ActivityStep } from "../../state/assistantStore";
import { ActivityStepRow, LoadableContent } from "./ActivityStepRow";

type DisplayStep = { seq: number; kind: ActivityStep["kind"]; toolName?: string | null; text: string };

/**
 * 主助理过程时间线（US3）：默认折叠、限高内滚；运行中头部转圈但不自动展开；
 * 最终回复不在此重复。历史会话（无实时步骤）首次展开时经 transcript 重建；
 * 已压缩回合以规整概要提示渲染（FR-020/E1）。
 */
function ActivityTimeline({
  sessionId,
  turnId,
  liveSteps,
  running,
  afterSequence,
  beforeSequence,
}: {
  sessionId: string;
  turnId?: string;
  liveSteps: ActivityStep[];
  running: boolean;
  afterSequence?: number;
  beforeSequence?: number;
}): JSX.Element | null {
  const mainLive = liveSteps.filter((step) => step.subagentId == null);
  const hasLive = mainLive.length > 0 || running;

  const [historySteps, setHistorySteps] = useState<AssistantActivityStep[]>([]);
  const [compressed, setCompressed] = useState(false);
  const [fetched, setFetched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setHistorySteps([]);
    setCompressed(false);
    setFetched(false);
    setLoading(false);
    setError(null);
  }, [sessionId, turnId, afterSequence, beforeSequence]);

  const loadHistory = useCallback(() => {
    setFetched(true);
    setLoading(true);
    setError(null);
    getSubagentTranscript(sessionId, undefined, { afterSequence, beforeSequence })
      .then((transcript) => {
        setHistorySteps(transcript.steps);
        setCompressed(transcript.compressed);
      })
      .catch(() => {
        setHistorySteps([]);
        setCompressed(false);
        setFetched(false);
        setError("过程加载失败，请重试。");
      })
      .finally(() => setLoading(false));
  }, [afterSequence, beforeSequence, sessionId]);

  const handleToggle = (event: React.SyntheticEvent<HTMLDetailsElement>) => {
    if (event.currentTarget.open && !hasLive && !fetched && !loading) {
      loadHistory();
    }
  };

  const steps: DisplayStep[] = hasLive ? mainLive : historySteps;
  const summary = running ? "正在处理 · 点开看它在想什么、做什么" : "查看这一回合的思考过程";

  return (
    <details className="assistant-activity" data-turn-id={turnId} onToggle={handleToggle}>
      <summary>
        {running ? <Loader2 size={13} className="assistant-spin" /> : null}
        <span>{summary}</span>
        {steps.length > 0 ? <span className="assistant-activity-count">{steps.length} 项</span> : null}
      </summary>
      <div className="assistant-activity-body me-scroll">
        {compressed ? (
          <p className="assistant-activity-compressed">较早的过程已折叠为概要，详细步骤可能不完整。</p>
        ) : null}
        {loading || error ? (
          <LoadableContent loading={loading} error={error} emptyLabel="" onRetry={loadHistory} />
        ) : steps.length === 0 ? (
          <div className="assistant-drawer-empty">还没有可展开的过程。</div>
        ) : null}
        {steps.map((step) => (
          <div key={step.seq} className="assistant-step" data-kind={step.kind}>
            <ActivityStepRow kind={step.kind} seq={step.seq} toolName={step.toolName} text={step.text} />
          </div>
        ))}
      </div>
    </details>
  );
}

export default ActivityTimeline;
