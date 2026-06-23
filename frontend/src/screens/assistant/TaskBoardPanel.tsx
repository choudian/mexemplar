import type { AssistantTaskBoardItem } from "../../api/assistantTasks";

interface TaskBoardPanelProps {
  items?: AssistantTaskBoardItem[];
  loading?: boolean;
}

export function TaskBoardPanel({
  items = [],
  loading = false,
}: TaskBoardPanelProps) {
  if (loading) {
    return (
      <section className="assistant-collab-panel assistant-task-board" aria-label="任务看板">
        <div role="status">正在加载任务看板</div>
      </section>
    );
  }
  if (items.length === 0) {
    return null;
  }
  return (
    <section className="assistant-collab-panel assistant-task-board" aria-label="任务看板">
      <header>
        <strong>任务看板</strong>
        <span>{items.length}</span>
      </header>
      <ul>
        {items.map((item) => (
          <li key={item.taskId}>
            <div>
              <span>{item.title}</span>
              <small>{item.claimStatus === "claimed" ? "已认领" : "待认领"}</small>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
