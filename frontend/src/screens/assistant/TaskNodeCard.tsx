import {
  Bot,
  CheckCircle2,
  Loader2,
  PauseCircle,
  Play,
  Shield,
  AlertTriangle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";

import type {
  AssistantTaskSnapshot,
  AssistantTodoItem,
  TaskAdjudicationDecision,
  TaskDisplayPhase,
} from "../../api/assistantTasks";

/** displayPhase → 用户可见标签、图标、色调 */
const PHASE_META: Record<
  TaskDisplayPhase,
  { label: string; tone: string; Icon: LucideIcon; spin?: boolean }
> = {
  running: { label: "执行中", tone: "running", Icon: Loader2, spin: true },
  reviewing: { label: "待审核", tone: "reviewing", Icon: Shield },
  needs_attention: {
    label: "需要关注",
    tone: "needs_attention",
    Icon: AlertTriangle,
  },
  paused: { label: "已暂停", tone: "paused", Icon: PauseCircle },
  done: { label: "已完成", tone: "done", Icon: CheckCircle2 },
};

const TODO_STATUS_LABELS: Record<string, string> = {
  todo: "待办",
  doing: "进行中",
  done: "已完成",
  skipped: "已跳过",
};

interface TaskNodeCardProps {
  task: AssistantTaskSnapshot;
  todos?: AssistantTodoItem[];
  onLoadTodos?: (taskId: string) => void;
  onDecide?: (
    adjudicationId: string,
    decision: TaskAdjudicationDecision,
    instruction?: string,
  ) => void;
  onContinueGraph?: (graphId: string) => void;
}

/**
 * DAG 调度节点卡片（025）：交互对齐 SubagentCard——收起看标题+状态，
 * 双击/Enter 就地展开看详情（描述、暂停原因、todo 子步骤、裁定操作）。
 * 暂停（user_stop）时底部显示"继续任务"按钮。
 */
function TaskNodeCard({
  task,
  todos,
  onLoadTodos,
  onDecide,
  onContinueGraph,
}: TaskNodeCardProps): JSX.Element {
  const meta = PHASE_META[task.displayPhase] ?? PHASE_META.running;
  const [expanded, setExpanded] = useState(false);
  const [todoExpanded, setTodoExpanded] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [note, setNote] = useState("");

  const showContinue =
    task.displayPhase === "paused" && task.suspendReason === "user_stop";
  const showAdjudication = task.requiresReview && !!task.adjudicationId;

  const handleToggle = () => {
    setExpanded((prev) => !prev);
  };

  const handleTodoToggle = () => {
    const next = !todoExpanded;
    setTodoExpanded(next);
    if (next) onLoadTodos?.(task.taskId);
  };

  const submitContinue = () => {
    onContinueGraph?.(task.graphId);
    setContinuing(false);
    setNote("");
  };

  return (
    <div
      className="assistant-subcard assistant-task-node"
      data-status={meta.tone}
      data-phase={task.displayPhase}
      role="button"
      tabIndex={0}
      aria-label={`任务 ${task.title}，${meta.label}，双击或回车查看详情`}
      title="双击查看任务详情"
      onDoubleClick={handleToggle}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleToggle();
        }
      }}
    >
      <div className="assistant-subcard-icon" aria-hidden="true">
        <meta.Icon size={16} className={meta.spin ? "assistant-spin" : undefined} />
      </div>
      <div className="assistant-subcard-body">
        <div className="assistant-subcard-head">
          <strong>{task.title}</strong>
          {task.requiresConfirmation ? (
            <span title="高风险/不可逆节点，执行前需确认" aria-label="需确认">
              ⚠️
            </span>
          ) : null}
          <span className={`assistant-subcard-status assistant-subcard-status-${meta.tone}`}>
            {meta.label}
          </span>
        </div>

        {/* 展开详情区 */}
        {expanded ? (
          <div className="assistant-task-node-detail">
            {task.descriptionPreview ? (
              <p className="assistant-task-node-desc">{task.descriptionPreview}</p>
            ) : null}
            {task.safeExplanation ? (
              <p className="assistant-task-node-explanation">{task.safeExplanation}</p>
            ) : null}

            {/* 子步骤 */}
            <button
              type="button"
              className="assistant-link assistant-task-node-todo-toggle"
              aria-expanded={todoExpanded}
              onClick={(e) => {
                e.stopPropagation();
                handleTodoToggle();
              }}
              onDoubleClick={(e) => e.stopPropagation()}
            >
              {todoExpanded ? "收起子步骤" : "查看子步骤"}
            </button>
            {todoExpanded ? (
              todos && todos.length > 0 ? (
                <ul className="task-node-todo-list" aria-label={`${task.title} 的子步骤`}>
                  {todos.map((todo) => (
                    <li
                      key={todo.todoId}
                      className={`task-node-todo-item task-node-todo-${todo.status}`}
                    >
                      <span className="todo-status">
                        {TODO_STATUS_LABELS[todo.status] ?? todo.status}
                      </span>
                      <span className="todo-text">{todo.text}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="task-node-todo-empty">暂无子步骤信息</p>
              )
            ) : null}

            {/* 裁定操作 */}
            {showAdjudication ? (
              <div className="assistant-task-node-adjudication" aria-label={`${task.title} 审核`}>
                <button
                  type="button"
                  className="assistant-task-node-decide-btn assistant-task-node-decide-accept"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDecide?.(task.adjudicationId!, "accepted");
                  }}
                  onDoubleClick={(e) => e.stopPropagation()}
                >
                  认可
                </button>
                <button
                  type="button"
                  className="assistant-task-node-decide-btn assistant-task-node-decide-return"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDecide?.(task.adjudicationId!, "returned", "请根据反馈返工。");
                  }}
                  onDoubleClick={(e) => e.stopPropagation()}
                >
                  打回
                </button>
                <button
                  type="button"
                  className="assistant-task-node-decide-btn assistant-task-node-decide-abandon"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDecide?.(task.adjudicationId!, "abandoned");
                  }}
                  onDoubleClick={(e) => e.stopPropagation()}
                >
                  放弃
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="assistant-subcard-foot">
          <button
            type="button"
            className="assistant-link"
            onClick={(event) => {
              event.stopPropagation();
              handleToggle();
            }}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            {expanded ? "收起详情" : "双击 / 点这里查看详情"}
          </button>

          {/* 暂停续跑 */}
          {showContinue && onContinueGraph ? (
            continuing ? (
              <div
                className="assistant-continue-form"
                onClick={(event) => event.stopPropagation()}
                onDoubleClick={(event) => event.stopPropagation()}
              >
                <input
                  className="assistant-continue-input"
                  aria-label="继续任务的补充说明（可选）"
                  placeholder="补充一句（可选）…"
                  value={note}
                  onChange={(event) => setNote(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      event.stopPropagation();
                      submitContinue();
                    } else {
                      event.stopPropagation();
                    }
                  }}
                />
                <button
                  type="button"
                  className="assistant-continue-btn"
                  onClick={(event) => {
                    event.stopPropagation();
                    submitContinue();
                  }}
                  onKeyDown={(event) => event.stopPropagation()}
                >
                  <Play size={12} />
                  继续
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="assistant-continue-btn"
                onClick={(event) => {
                  event.stopPropagation();
                  setContinuing(true);
                }}
                onKeyDown={(event) => event.stopPropagation()}
              >
                <Play size={12} />
                继续任务
              </button>
            )
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default TaskNodeCard;
