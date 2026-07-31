import { Loader2, Square, Play } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getSubagentTranscript } from "../../api/assistant";
import type { AssistantActivityStep } from "../../api/assistant";
import type {
  AssistantTaskGraphSnapshot,
  AssistantTodoItem,
  TaskAdjudicationDecision,
} from "../../api/assistantTasks";
import { canContinueTask } from "../../api/assistantTasks";
import type { ActivityStep, Subagent } from "../../state/assistantStore";
import { ActivityStepRow, LoadableContent } from "./ActivityStepRow";
import SubagentCard from "./SubagentCard";
import TaskNodeCard from "./TaskNodeCard";

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
 * 025: DAG 调度节点也以 TaskNodeCard 形式出现在时间线内，与 SubagentCard 交错排列。
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
  taskGraph,
  todosByTaskId,
  onLoadTodos,
  onDecide,
  onStopGraph,
  onContinueGraph,
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
  /** 025: 当前回合关联的 task graph 快照 */
  taskGraph?: AssistantTaskGraphSnapshot | null;
  /** 025: 按 taskId 索引的 todo 列表 */
  todosByTaskId?: Record<string, AssistantTodoItem[]>;
  /** 025: 点击节点展开时触发加载该节点 todo 的回调 */
  onLoadTodos?: (taskId: string) => void;
  /** 025: 审核裁定回调 */
  onDecide?: (
    adjudicationId: string,
    decision: TaskAdjudicationDecision,
    instruction?: string,
  ) => void;
  /** 025: 停止任务图回调 */
  onStopGraph?: (graphId: string) => void;
  /** 025: 继续任务图回调 */
  onContinueGraph?: (graphId: string) => void;
}): JSX.Element | null {
  const mainLive = liveSteps.filter((step) => step.subagentId == null);
  const hasLive = mainLive.length > 0 || running;

  // 提取非根节点（根节点是 DAG 容器，不渲染为卡片）
  const taskNodes = (taskGraph?.tasks ?? []).filter(
    (task) => task.parentTaskId != null,
  );

  // 有暂停/失败子任务或需要关注的 DAG 节点时默认展开
  const needsAttention =
    subagents.some(
      (item) => item.status === "suspended" || item.status === "failed",
    ) ||
    taskNodes.some(
      (t) =>
        t.displayPhase === "needs_attention" ||
        t.displayPhase === "reviewing" ||
        canContinueTask(t),
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
  const totalCount = steps.length + subagents.length + taskNodes.length;
  const summary = running ? "正在处理" : "查看这一回合的思考过程";

  // 任务图锚点：用 userMessageSequence 定位，不可用时落到末尾
  const graphAnchorSeq = taskGraph?.userMessageSequence ?? Number.MAX_SAFE_INTEGER;

  // 步骤、子卡片、DAG 节点按 seq 交错
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
            onContinueSubagent
              ? (note) => onContinueSubagent(subagent.subagentId, note)
              : undefined
          }
        />
      ),
    })),
    ...taskNodes.map((task) => ({
      sortSeq: graphAnchorSeq,
      tie: 2,
      node: (
        <TaskNodeCard
          key={`task_${task.taskId}`}
          task={task}
          todos={todosByTaskId?.[task.taskId]}
          onLoadTodos={onLoadTodos}
          onDecide={onDecide}
          onContinueGraph={onContinueGraph}
        />
      ),
    })),
  ].sort((a, b) => a.sortSeq - b.sortSeq || a.tie - b.tie);

  // 任务图全局操作按钮条件
  const canStopGraph = taskNodes.some((t) => t.displayPhase === "running");
  const canContinueGraph = taskNodes.some(canContinueTask);
  const hasGraphActions = canStopGraph || canContinueGraph;

  return (
    <details className="assistant-activity" data-turn-id={turnId} open={open} onToggle={handleToggle}>
      <summary>
        {running ? <Loader2 size={13} className="assistant-spin" /> : null}
        <span>{summary}</span>
        {totalCount > 0 ? (
          <span className="assistant-activity-count">{totalCount} 项</span>
        ) : null}
        {hasGraphActions ? (
          <span className="assistant-activity-graph-actions">
            {canStopGraph && onStopGraph && taskGraph ? (
              <button
                type="button"
                className="assistant-activity-graph-btn assistant-activity-graph-stop"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onStopGraph(taskGraph.graphId);
                }}
                title="停止任务"
              >
                <Square size={12} />
                停止任务
              </button>
            ) : null}
            {canContinueGraph && onContinueGraph && taskGraph ? (
              <button
                type="button"
                className="assistant-activity-graph-btn assistant-activity-graph-continue"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onContinueGraph(taskGraph.graphId);
                }}
                title="继续任务"
              >
                <Play size={12} />
                继续任务
              </button>
            ) : null}
          </span>
        ) : null}
      </summary>
      <div className="assistant-activity-body me-scroll">
        {compressed ? (
          <p className="assistant-activity-compressed">
            较早的过程已折叠为概要，详细步骤可能不完整。
          </p>
        ) : null}
        {loading || error ? (
          <LoadableContent
            loading={loading}
            error={error}
            emptyLabel=""
            onRetry={loadHistory}
          />
        ) : steps.length === 0 && subagents.length === 0 && taskNodes.length === 0 ? (
          <div className="assistant-drawer-empty">还没有可展开的过程。</div>
        ) : null}
        {timelineEntries.map((entry) => entry.node)}
      </div>
    </details>
  );
}

export default ActivityTimeline;
