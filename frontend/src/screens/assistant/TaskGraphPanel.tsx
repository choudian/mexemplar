import { useState } from "react";

import type {
  AssistantTaskGraphSnapshot,
  AssistantTodoItem,
  TaskAdjudicationDecision,
} from "../../api/assistantTasks";

const DISPLAY_PHASE_LABELS: Record<string, string> = {
  running: "执行中",
  reviewing: "待审核",
  needs_attention: "需要关注",
  paused: "已暂停",
  done: "已完成",
};

const TODO_STATUS_LABELS: Record<string, string> = {
  todo: "待办",
  doing: "进行中",
  done: "已完成",
  skipped: "已跳过",
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
  /** 024: 按 taskId 索引的 todo 列表，从 assistantTaskStore.todosByTaskId 传入 */
  todosByTaskId?: Record<string, AssistantTodoItem[]>;
  /** 024: 点击节点展开时触发加载该节点 todo 的回调 */
  onLoadTodos?: (taskId: string) => void;
}

export function TaskGraphPanel({
  graph,
  loading = false,
  onStop,
  onContinue,
  onDecide,
  todosByTaskId,
  onLoadTodos,
}: TaskGraphPanelProps) {
  const [expanded, setExpanded] = useState(false);
  /** 024: 按节点 taskId 记录哪些节点展开了 todo */
  const [expandedTodoTaskIds, setExpandedTodoTaskIds] = useState<Set<string>>(
    new Set(),
  );

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

  const toggleTodoExpand = (taskId: string) => {
    setExpandedTodoTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) {
        next.delete(taskId);
      } else {
        next.add(taskId);
        // 首次展开时触发加载 todo（懒加载）
        onLoadTodos?.(taskId);
      }
      return next;
    });
  };

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
        {graph.tasks.map((task) => {
          const isTodoExpanded = expandedTodoTaskIds.has(task.taskId);
          const todos = todosByTaskId?.[task.taskId];
          const hasTodos = todos && todos.length > 0;
          // 只为非根节点展示 todo 入口（根节点是 DAG 容器，不执行）
          const canShowTodoToggle = task.parentTaskId !== null;

          return (
            <li key={task.taskId}>
              <span>{task.title}</span>
              <span>{DISPLAY_PHASE_LABELS[task.displayPhase] ?? "进行中"}</span>
              {task.requiresConfirmation && (
                <span title="高风险/不可逆节点，执行前需确认" aria-label="需确认">⚠️</span>
              )}
              {/* 024: 按节点展开 todo（DEC-E：默认不展示，展开可见） */}
              {canShowTodoToggle && (
                <button
                  type="button"
                  className="task-node-todo-toggle"
                  aria-expanded={isTodoExpanded}
                  aria-label={isTodoExpanded ? `收起 ${task.title} 的子步骤` : `展开 ${task.title} 的子步骤`}
                  onClick={() => toggleTodoExpand(task.taskId)}
                >
                  {isTodoExpanded ? "收起子步骤" : "查看子步骤"}
                </button>
              )}
              {isTodoExpanded && hasTodos ? (
                <ul className="task-node-todo-list" aria-label={`${task.title} 的子步骤`}>
                  {todos.map((todo) => (
                    <li key={todo.todoId} className={`task-node-todo-item task-node-todo-${todo.status}`}>
                      <span className="todo-status">{TODO_STATUS_LABELS[todo.status] ?? todo.status}</span>
                      <span className="todo-text">{todo.text}</span>
                    </li>
                  ))}
                </ul>
              ) : isTodoExpanded && !hasTodos ? (
                <p className="task-node-todo-empty">暂无子步骤信息</p>
              ) : null}
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
          );
        })}
      </ul>
    </section>
  );
}
