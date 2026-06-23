import { useMemo } from "react";

import type { AssistantTaskSnapshot, AssistantTodoItem } from "../../api/assistantTasks";

interface TodoChecklistPanelProps {
  tasks?: AssistantTaskSnapshot[];
  todosByTaskId?: Record<string, AssistantTodoItem[]>;
  loadingTaskIds?: string[];
}

const TODO_STATUS_LABELS: Record<AssistantTodoItem["status"], string> = {
  todo: "未开始",
  doing: "自查中",
  done: "已做完",
  skipped: "略过",
};

export function TodoChecklistPanel({
  tasks = [],
  todosByTaskId = {},
  loadingTaskIds = [],
}: TodoChecklistPanelProps) {
  const taskSections = useMemo(
    () =>
      tasks
        .map((task) => ({
          task,
          items: todosByTaskId[task.taskId] ?? [],
          loading: loadingTaskIds.includes(task.taskId),
        }))
        .filter((section) => section.loading || section.items.length > 0),
    [tasks, todosByTaskId, loadingTaskIds],
  );

  if (taskSections.length === 0) {
    return null;
  }

  return (
    <section className="assistant-collab-panel assistant-task-todos" aria-label="私人清单">
      <header>
        <strong>私人清单</strong>
        <span>{taskSections.reduce((count, section) => count + section.items.length, 0)}</span>
      </header>
      {taskSections.map(({ task, items, loading }) => (
        <article key={task.taskId}>
          <h3>{task.title}</h3>
          {loading ? <div role="status">正在加载私人清单</div> : null}
          {items.length > 0 ? (
            <ol>
              {items.map((item) => (
                <li key={item.todoId}>
                  <span>{item.text}</span>
                  <small>{TODO_STATUS_LABELS[item.status]}</small>
                </li>
              ))}
            </ol>
          ) : null}
        </article>
      ))}
    </section>
  );
}
