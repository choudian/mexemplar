import { useState } from "react";

import type {
  AssistantTaskGraphSnapshot,
  TaskAdjudicationDecision,
} from "../../api/assistantTasks";

const DISPLAY_PHASE_LABELS: Record<string, string> = {
  running: "执行中",
  reviewing: "待审核",
  needs_attention: "需要关注",
  paused: "已暂停",
  done: "已完成",
};

interface TaskGraphPanelProps {
  graph: AssistantTaskGraphSnapshot | null;
  loading?: boolean;
  onStop?: (graphId: string) => void;
  onContinue?: (graphId: string) => void;
  onDecide?: (
    adjudicationId: string,
    decision: TaskAdjudicationDecision,
    instruction?: string,
  ) => void;
}

export function TaskGraphPanel({
  graph,
  loading = false,
  onStop,
  onContinue,
  onDecide,
}: TaskGraphPanelProps) {
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return (
      <section className="assistant-collab-panel assistant-task-graph" aria-label="任务进度">
        <div role="status">正在加载任务进度</div>
      </section>
    );
  }

  if (!graph || graph.tasks.length === 0) {
    return (
      <section className="assistant-collab-panel assistant-task-graph" aria-label="任务进度">
        <div>暂无任务进度</div>
      </section>
    );
  }
  const canStop = graph.tasks.some(
    (task) => task.displayPhase === "running",
  );
  const canContinue = graph.tasks.some(
    (task) => task.displayPhase === "paused" && task.suspendReason === "user_stop",
  );

  return (
    <section className="assistant-collab-panel assistant-task-graph" aria-label="任务进度">
      <div className="assistant-task-graph-actions">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "收起任务详情" : "展开任务详情"}
        </button>
        {canStop ? (
          <button type="button" onClick={() => onStop?.(graph.graphId)}>
            停止任务
          </button>
        ) : null}
        {canContinue ? (
          <button type="button" onClick={() => onContinue?.(graph.graphId)}>
            继续任务
          </button>
        ) : null}
      </div>
      <ul>
        {graph.tasks.map((task) => (
          <li key={task.taskId}>
            <span>{task.title}</span>
            <span>{DISPLAY_PHASE_LABELS[task.displayPhase] ?? "进行中"}</span>
            {expanded ? (
              <div>
                <p>{task.descriptionPreview}</p>
                {task.safeExplanation ? <p>{task.safeExplanation}</p> : null}
                {task.requiresReview && task.adjudicationId ? (
                  <div aria-label={`${task.title} 审核`}>
                    <button
                      type="button"
                      onClick={() => onDecide?.(task.adjudicationId!, "accepted")}
                    >
                      认可
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        onDecide?.(task.adjudicationId!, "returned", "请根据反馈返工。")
                      }
                    >
                      打回
                    </button>
                    <button
                      type="button"
                      onClick={() => onDecide?.(task.adjudicationId!, "abandoned")}
                    >
                      放弃
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
