import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { AssistantTaskGraphSnapshot } from "../../src/api/assistantTasks";
import type {
  AssistantMeetingTranscript,
  AssistantTaskBoardItem,
  AssistantTodoItem,
} from "../../src/api/assistantTasks";
import { MeetingChannelDrawer } from "../../src/screens/assistant/MeetingChannelDrawer";
import { TaskBoardPanel } from "../../src/screens/assistant/TaskBoardPanel";
import { TaskGraphPanel } from "../../src/screens/assistant/TaskGraphPanel";
import { TodoChecklistPanel } from "../../src/screens/assistant/TodoChecklistPanel";

const GRAPH: AssistantTaskGraphSnapshot = {
  graphId: "tg_1",
  sessionId: "ast_1",
  userMessageSequence: 1,
  version: 1,
  tasks: [
    {
      taskId: "tsk_1",
      graphId: "tg_1",
      parentTaskId: null,
      title: "整理报销",
      descriptionPreview: "整理本月报销",
      status: "running",
      displayPhase: "running",
      requiresReview: false,
      requiresConfirmation: false,
      safeExplanation: "",
      suspendReason: null,
      assignee: null,
      adjudicationId: null,
      updatedAt: "2026-06-17T12:00:00Z",
    },
  ],
  edges: [],
  adjudications: [],
};

const REVIEW_GRAPH: AssistantTaskGraphSnapshot = {
  ...GRAPH,
  tasks: [
    {
      ...GRAPH.tasks[0],
      requiresReview: true,
      adjudicationId: "adj_1",
      safeExplanation: "等待上级检查结果",
      displayPhase: "reviewing",
    },
  ],
};

const STOPPED_GRAPH: AssistantTaskGraphSnapshot = {
  ...GRAPH,
  tasks: [
    {
      ...GRAPH.tasks[0],
      status: "suspended",
      displayPhase: "paused",
      suspendReason: "user_stop",
    },
  ],
};

describe("TaskGraphPanel", () => {
  test("renders loading state", () => {
    render(<TaskGraphPanel graph={null} loading />);

    expect(screen.getByRole("status")).toHaveTextContent("正在加载任务进度");
  });

  test("renders empty state", () => {
    render(<TaskGraphPanel graph={null} />);

    expect(screen.getByLabelText("任务进度")).toHaveTextContent("暂无任务进度");
  });

  test("renders graph tasks", () => {
    render(<TaskGraphPanel graph={GRAPH} />);

    expect(screen.getByText("整理报销")).toBeInTheDocument();
    expect(screen.getByText("执行中")).toBeInTheDocument();
  });

  test("expands task safe details", () => {
    render(<TaskGraphPanel graph={GRAPH} />);

    fireEvent.click(screen.getByRole("button", { name: "展开任务详情" }));

    expect(screen.getByText("整理本月报销")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "收起任务详情" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  test("keeps focus on graph expand control", () => {
    render(<TaskGraphPanel graph={GRAPH} />);

    const expandButton = screen.getByRole("button", { name: "展开任务详情" });
    expandButton.focus();
    fireEvent.click(expandButton);

    expect(document.activeElement).toBe(expandButton);
  });

  test("exposes stop and continue controls", () => {
    const onStop = vi.fn();
    const onContinue = vi.fn();
    const { rerender } = render(<TaskGraphPanel graph={GRAPH} onStop={onStop} />);

    fireEvent.click(screen.getByRole("button", { name: "停止任务" }));
    expect(onStop).toHaveBeenCalledWith("tg_1");

    rerender(<TaskGraphPanel graph={STOPPED_GRAPH} onContinue={onContinue} />);
    fireEvent.click(screen.getByRole("button", { name: "继续任务" }));
    expect(onContinue).toHaveBeenCalledWith("tg_1");
  });

  test("exposes adjudication controls for review tasks", () => {
    const onDecide = vi.fn();
    render(<TaskGraphPanel graph={REVIEW_GRAPH} onDecide={onDecide} />);

    fireEvent.click(screen.getByRole("button", { name: "展开任务详情" }));
    fireEvent.click(screen.getByRole("button", { name: "认可" }));
    fireEvent.click(screen.getByRole("button", { name: "打回" }));
    fireEvent.click(screen.getByRole("button", { name: "放弃" }));

    expect(onDecide).toHaveBeenNthCalledWith(1, "adj_1", "accepted");
    expect(onDecide).toHaveBeenNthCalledWith(2, "adj_1", "returned", "请根据反馈返工。");
    expect(onDecide).toHaveBeenNthCalledWith(3, "adj_1", "abandoned");
  });
});

const BOARD_ITEMS: AssistantTaskBoardItem[] = [
  {
    taskId: "tsk_board",
    graphId: "tg_1",
    title: "核对发票",
    status: "pending_dispatch",
    claimStatus: "open",
    assignee: null,
    updatedAt: "2026-06-17T12:00:00Z",
  },
  {
    taskId: "tsk_claimed",
    graphId: "tg_1",
    title: "整理附件",
    status: "pending_dispatch",
    claimStatus: "claimed",
    claimId: "clm_1",
    assignee: { type: "specialist", id: "sp_1" },
    updatedAt: "2026-06-17T12:00:00Z",
  },
];

const MEETING: AssistantMeetingTranscript = {
  channelId: "mtg_1",
  status: "open",
  participants: [
    { type: "specialist", id: "sp_a" },
    { type: "specialist", id: "sp_b" },
  ],
  turnsUsed: 1,
  turnBudget: 12,
  messages: [
    {
      sequence: 1,
      senderId: "sp_a",
      content: "按日期排序。",
      createdAt: "2026-06-17T12:00:00Z",
    },
  ],
  nextAfterSequence: null,
  conclusion: null,
};

describe("TaskBoardPanel", () => {
  test("renders loading and empty states", () => {
    const { rerender } = render(<TaskBoardPanel items={[]} loading />);

    expect(screen.getByRole("status")).toHaveTextContent("正在加载任务看板");

    rerender(<TaskBoardPanel items={[]} />);
    expect(screen.queryByLabelText("任务看板")).not.toBeInTheDocument();
  });

  test("renders board item statuses", () => {
    render(<TaskBoardPanel items={BOARD_ITEMS} />);

    expect(screen.getByLabelText("任务看板")).toHaveTextContent("核对发票");
    // Board 是 agent-to-agent 概念，用户面板只展示状态
    expect(screen.getByText("已认领")).toBeInTheDocument();
    expect(screen.getByText("待认领")).toBeInTheDocument();
  });
});

describe("MeetingChannelDrawer", () => {
  test("renders loading state", () => {
    render(<MeetingChannelDrawer meeting={null} loading />);

    expect(screen.getByRole("status")).toHaveTextContent("正在加载会议记录");
  });

  test("renders transcript and close action", () => {
    const onClose = vi.fn();
    render(<MeetingChannelDrawer meeting={MEETING} onClose={onClose} />);

    expect(screen.getByLabelText("协作会议")).toHaveTextContent("按日期排序。");
    expect(screen.getByText("1/12")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalled();
  });
});

const TODOS: AssistantTodoItem[] = [
  { todoId: "todo_1", text: "收集发票", status: "todo", sortOrder: 1 },
  { todoId: "todo_2", text: "核对金额", status: "doing", sortOrder: 2 },
  { todoId: "todo_3", text: "生成邮件草稿", status: "done", sortOrder: 3 },
  { todoId: "todo_4", text: "电话确认", status: "skipped", sortOrder: 4 },
];

describe("TodoChecklistPanel", () => {
  test("renders private checklist with distinct status labels", () => {
    render(<TodoChecklistPanel tasks={GRAPH.tasks} todosByTaskId={{ tsk_1: TODOS }} />);

    const panel = screen.getByLabelText("私人清单");
    expect(panel).toHaveTextContent("整理报销");
    expect(panel).toHaveTextContent("收集发票");
    expect(panel).toHaveTextContent("未开始");
    expect(panel).toHaveTextContent("自查中");
    expect(panel).toHaveTextContent("已做完");
    expect(panel).toHaveTextContent("略过");
    expect(screen.queryByText("running")).not.toBeInTheDocument();
  });

  test("renders loading state without creating task graph nodes", () => {
    render(
      <TodoChecklistPanel
        tasks={GRAPH.tasks}
        todosByTaskId={{}}
        loadingTaskIds={["tsk_1"]}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("正在加载私人清单");
    expect(screen.getByLabelText("私人清单").querySelectorAll("li")).toHaveLength(0);
  });
});
