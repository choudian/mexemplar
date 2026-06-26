/**
 * US5: TaskGraphPanel 节点展开 todo 可见性测试
 *
 * 验证：
 * - 默认界面不展示 todo（需用户主动展开）
 * - 展开节点后可见 todo 子步骤
 * - requiresConfirmation 标记正确展示
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type {
  AssistantTaskGraphSnapshot,
  AssistantTodoItem,
} from "../../src/api/assistantTasks";
import { TaskGraphPanel } from "../../src/screens/assistant/TaskGraphPanel";

// 最小可行快照
function makeGraph(
  overrides?: Partial<AssistantTaskGraphSnapshot>,
): AssistantTaskGraphSnapshot {
  return {
    graphId: "graph-001",
    sessionId: "sess-001",
    version: 1,
    tasks: [
      {
        taskId: "tsk-001",
        graphId: "graph-001",
        parentTaskId: "tsk-root",
        title: "步骤A",
        descriptionPreview: "先做这个",
        status: "running",
        displayPhase: "running",
        requiresReview: false,
        requiresConfirmation: false,
        safeExplanation: "",
      },
    ],
    edges: [],
    adjudications: [],
    ...overrides,
  };
}

const sampleTodos: Record<string, AssistantTodoItem[]> = {
  "tsk-001": [
    { todoId: "todo-1", text: "拉取数据", status: "done", sortOrder: 1 },
    { todoId: "todo-2", text: "清洗数据", status: "doing", sortOrder: 2 },
    { todoId: "todo-3", text: "输出结果", status: "todo", sortOrder: 3 },
  ],
};

describe("TaskGraphPanel todo visibility", () => {
  it("默认不展示 todo 子步骤", () => {
    const graph = makeGraph();
    render(
      <TaskGraphPanel
        graph={graph}
        todosByTaskId={sampleTodos}
      />,
    );

    // todo 内容不应默认可见
    expect(screen.queryByText("拉取数据")).toBeNull();
    expect(screen.queryByText("清洗数据")).toBeNull();
    expect(screen.queryByText("输出结果")).toBeNull();
  });

  it("展开节点后可见 todo 子步骤", () => {
    const graph = makeGraph();
    render(
      <TaskGraphPanel
        graph={graph}
        todosByTaskId={sampleTodos}
      />,
    );

    // 点击"查看子步骤"按钮展开
    const toggleButton = screen.getByLabelText("展开 步骤A 的子步骤");
    fireEvent.click(toggleButton);

    // todo 内容应可见
    expect(screen.getByText("拉取数据")).toBeDefined();
    expect(screen.getByText("清洗数据")).toBeDefined();
    expect(screen.getByText("输出结果")).toBeDefined();
  });

  it("收起节点后 todo 不可见", () => {
    const graph = makeGraph();
    render(
      <TaskGraphPanel
        graph={graph}
        todosByTaskId={sampleTodos}
      />,
    );

    // 展开
    const expandButton = screen.getByLabelText("展开 步骤A 的子步骤");
    fireEvent.click(expandButton);
    expect(screen.getByText("拉取数据")).toBeDefined();

    // 收起
    const collapseButton = screen.getByLabelText("收起 步骤A 的子步骤");
    fireEvent.click(collapseButton);
    expect(screen.queryByText("拉取数据")).toBeNull();
  });

  it("无 todo 时展开显示空状态", () => {
    const graph = makeGraph();
    render(
      <TaskGraphPanel
        graph={graph}
        todosByTaskId={{}}
      />,
    );

    const toggleButton = screen.getByLabelText("展开 步骤A 的子步骤");
    fireEvent.click(toggleButton);

    expect(screen.getByText("暂无子步骤信息")).toBeDefined();
  });

  it("requiresConfirmation 节点显示标记", () => {
    const graph = makeGraph({
      tasks: [
        {
          taskId: "tsk-001",
          graphId: "graph-001",
          parentTaskId: "tsk-root",
          title: "发送邮件",
          descriptionPreview: "对外发送",
          status: "pending_dispatch",
          displayPhase: "reviewing",
          requiresReview: false,
          requiresConfirmation: true,
          safeExplanation: "",
        },
      ],
    });
    render(<TaskGraphPanel graph={graph} />);

    // 需确认标记应可见
    expect(screen.getByLabelText("需确认")).toBeDefined();
  });

  it("展开时触发 onLoadTodos 回调", () => {
    const graph = makeGraph();
    let loadedTaskId: string | null = null;

    render(
      <TaskGraphPanel
        graph={graph}
        todosByTaskId={{}}
        onLoadTodos={(taskId) => {
          loadedTaskId = taskId;
        }}
      />,
    );

    const toggleButton = screen.getByLabelText("展开 步骤A 的子步骤");
    fireEvent.click(toggleButton);

    expect(loadedTaskId).toBe("tsk-001");
  });
});
