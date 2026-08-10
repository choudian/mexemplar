import { ChevronRight } from "lucide-react";

import type { AssistantSubagentSummary } from "../../api/assistant";
import type { AssistantTodoItem } from "../../api/assistantTasks";
import { subagentStatusTone } from "./executorStatus";

const STATUS_LABELS: Record<string, string> = {
  running: "正在干",
  done: "完成",
  suspended: "暂停",
  failed: "失败",
};

const TODO_STATUS_LABELS: Record<string, string> = {
  done: "完成",
  doing: "进行",
  todo: "待办",
  skipped: "跳过",
};

/**
 * 执行体卡片（⑦ 递归抽屉）：正面显示执行体名称 + 角色 + 状态 + todo 清单。
 * 设计 345-353：没做 todolist 的执行体放最后一句产出。
 */
function ExecutorCard({
  summary,
  todos,
  onClick,
}: {
  summary: AssistantSubagentSummary;
  todos?: AssistantTodoItem[];
  onClick?: () => void;
}): JSX.Element {
  const tone = subagentStatusTone(summary.status);
  const statusLabel = STATUS_LABELS[summary.status] ?? summary.status;
  const orderedTodos = todos ? [...todos].sort((a, b) => a.sortOrder - b.sortOrder) : [];

  return (
    <button type="button" className="me-agent" onClick={onClick}>
      <span className="me-agent-head">
        <span className="who">{summary.label}</span>
        <span className="kind">{summary.task || "执行体"}</span>
        <span className="st" data-t={tone}>{statusLabel}</span>
        <ChevronRight size={12} className="chev" />
      </span>
      <span className="me-agent-face">
        {orderedTodos.length > 0 ? (
          <ul className="task-node-todo-list">
            {orderedTodos.map((todo) => (
              <li key={todo.todoId} className={`task-node-todo-item task-node-todo-${todo.status}`}>
                <span className="todo-status">{TODO_STATUS_LABELS[todo.status]}</span>
                <span className="todo-text">{todo.text}</span>
              </li>
            ))}
          </ul>
        ) : summary.lastOutput ? (
          <span className="plain">{summary.lastOutput}</span>
        ) : null}
      </span>
    </button>
  );
}

export default ExecutorCard;
