import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getSubagentTranscript } from "../../api/assistant";
import type { AssistantActivityStep } from "../../api/assistant";
import type { ActivityStep, Subagent } from "../../state/assistantStore";
import { ActivityStepRow, LoadableContent } from "./ActivityStepRow";
import SubagentCard from "./SubagentCard";

type DisplayStep = {
  seq: number;
  kind: ActivityStep["kind"];
  toolName?: string | null;
  text: string;
  redacted?: boolean;
};

/**
 * 主助理过程时间线（US3）：默认折叠、限高内滚；运行中头部转圈但不自动展开；
 * 最终回复不在此重复。历史会话（无实时步骤）首次展开时经 transcript 重建；
 * 已压缩回合以规整概要提示渲染（FR-020/E1）。
 * 子任务卡片（US4/US5）归属本回合，随过程步骤一起收在折叠区内，不再平铺到对话流外层。
 */
function ActivityTimeline({
  sessionId,
  turnId,
  liveSteps,
  running,
  afterSequence,
  beforeSequence,
  subagents = [],
  onOpenSubagent,
  onContinueSubagent,
}: {
  sessionId: string;
  turnId?: string;
  liveSteps: ActivityStep[];
  running: boolean;
  afterSequence?: number;
  beforeSequence?: number;
  subagents?: Subagent[];
  onOpenSubagent?: (subagentId: string) => void;
  onContinueSubagent?: (subagentId: string, supplemental: string) => void;
}): JSX.Element | null {
  const mainLive = liveSteps.filter((step) => step.subagentId == null);
  const hasLive = mainLive.length > 0 || running;
  // 有暂停/失败子任务等待用户处理时默认展开，避免被折叠埋没；running 与正常完成仍折叠（守 FR-021 不自动展开）。
  const needsAttention = subagents.some(
    (item) => item.status === "suspended" || item.status === "failed",
  );

  const [historySteps, setHistorySteps] = useState<AssistantActivityStep[]>([]);
  const [compressed, setCompressed] = useState(false);
  const [fetched, setFetched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(needsAttention);

  useEffect(() => {
    setHistorySteps([]);
    setCompressed(false);
    setFetched(false);
    setLoading(false);
    setError(null);
  }, [sessionId, turnId, afterSequence, beforeSequence]);

  useEffect(() => {
    if (needsAttention) setOpen(true);
  }, [needsAttention]);

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
    const isOpen = event.currentTarget.open;
    setOpen(isOpen);
    if (isOpen && !hasLive && !fetched && !loading) {
      loadHistory();
    }
  };

  const steps: DisplayStep[] = hasLive ? mainLive : historySteps;
  const totalCount = steps.length + subagents.length;
  const summary = running ? "正在处理" : "查看这一回合的思考过程";

  // 步骤与子卡片按 seq 交错：子卡片紧跟其委派步骤、排在最终回复之前（tie=1 让同 seq 时子卡片落在步骤之后）。
  const timelineEntries = [
    ...steps.map((step) => ({
      sortSeq: step.seq,
      tie: 0,
      node: (
        <div key={`step_${step.seq}`} className="assistant-step" data-kind={step.kind}>
          <ActivityStepRow
            kind={step.kind}
            seq={step.seq}
            toolName={step.toolName}
            text={step.text}
            redacted={step.redacted}
          />
        </div>
      ),
    })),
    ...subagents.map((subagent) => ({
      sortSeq: subagent.anchorSeq ?? Number.MAX_SAFE_INTEGER,
      tie: 1,
      node: (
        <SubagentCard
          key={subagent.subagentId}
          subagent={subagent}
          onOpen={() => onOpenSubagent?.(subagent.subagentId)}
          onContinue={
            onContinueSubagent ? (note) => onContinueSubagent(subagent.subagentId, note) : undefined
          }
        />
      ),
    })),
  ].sort((a, b) => a.sortSeq - b.sortSeq || a.tie - b.tie);

  return (
    <details className="assistant-activity" data-turn-id={turnId} open={open} onToggle={handleToggle}>
      <summary>
        {running ? <Loader2 size={13} className="assistant-spin" /> : null}
        <span>{summary}</span>
        {totalCount > 0 ? <span className="assistant-activity-count">{totalCount} 项</span> : null}
      </summary>
      <div className="assistant-activity-body me-scroll">
        {compressed ? (
          <p className="assistant-activity-compressed">较早的过程已折叠为概要，详细步骤可能不完整。</p>
        ) : null}
        {loading || error ? (
          <LoadableContent loading={loading} error={error} emptyLabel="" onRetry={loadHistory} />
        ) : steps.length === 0 && subagents.length === 0 ? (
          <div className="assistant-drawer-empty">还没有可展开的过程。</div>
        ) : null}
        {timelineEntries.map((entry) => entry.node)}
      </div>
    </details>
  );
}

export default ActivityTimeline;
