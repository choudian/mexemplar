/**
 * 025: TaskNodeCard 组件测试
 *
 * 验证：
 * - 收起态显示标题和状态标签
 * - 双击/Enter 展开详情（描述、暂停原因、todo、裁定操作）
 * - 裁定操作触发 onDecide 回调
 * - 暂停续跑触发 onContinueGraph 回调
 * - todo 子步骤懒加载
 * - requiresConfirmation 标记展示
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AssistantTaskSnapshot,
  AssistantTodoItem,
} from "../../src/api/assistantTasks";
import TaskNodeCard from "../../src/screens/assistant/TaskNodeCard";

function makeTask(
  overrides?: Partial<AssistantTaskSnapshot>,
): AssistantTaskSnapshot {
  return {
    taskId: "tsk-001",
    graphId: "graph-001",
    parentTaskId: "tsk-root",
    title: "整理报销",
    descriptionPreview: "整理本月报销并生成摘要",
    status: "running",
    displayPhase: "running",
    requiresReview: false,
    requiresConfirmation: false,
    safeExplanation: "",
    suspendReason: null,
    adjudicationId: null,
    ...overrides,
  };
}

const sampleTodos: AssistantTodoItem[] = [
  { todoId: "todo-1", text: "拉取数据", status: "done", sortOrder: 1 },
  { todoId: "todo-2", text: "清洗数据", status: "doing", sortOrder: 2 },
  { todoId: "todo-3", text: "输出结果", status: "todo", sortOrder: 3 },
];

describe("TaskNodeCard", () => {
  it("收起态显示标题和状态标签", () => {
    const task = makeTask();
    render(<TaskNodeCard task={task} />);

    expect(screen.getByText("整理报销")).toBeDefined();
    expect(screen.getByText("执行中")).toBeDefined();
    // 描述预览不应默认可见
    expect(screen.queryByText("整理本月报销并生成摘要")).toBeNull();
  });

  it("双击展开详情显示描述和暂停原因", () => {
    const task = makeTask({
      safeExplanation: "等待上级检查结果",
    });
    render(<TaskNodeCard task={task} />);

    const card = screen.getByRole("button", {
      name: /整理报销.*执行中/,
    });
    fireEvent.doubleClick(card);

    expect(screen.getByText("整理本月报销并生成摘要")).toBeDefined();
    expect(screen.getByText("等待上级检查结果")).toBeDefined();
  });

  it("点击链接展开详情", () => {
    const task = makeTask();
    render(<TaskNodeCard task={task} />);

    const link = screen.getByText("双击 / 点这里查看详情");
    fireEvent.click(link);

    expect(screen.getByText("整理本月报销并生成摘要")).toBeDefined();
    expect(screen.getByText("收起详情")).toBeDefined();
  });

  it("Enter 键展开详情", () => {
    const task = makeTask();
    render(<TaskNodeCard task={task} />);

    const card = screen.getByRole("button", {
      name: /整理报销.*执行中/,
    });
    fireEvent.keyDown(card, { key: "Enter" });

    expect(screen.getByText("整理本月报销并生成摘要")).toBeDefined();
  });

  it("裁定操作触发 onDecide 回调", () => {
    const task = makeTask({
      requiresReview: true,
      adjudicationId: "adj-001",
      displayPhase: "reviewing",
    });
    const onDecide = vi.fn();
    render(<TaskNodeCard task={task} onDecide={onDecide} />);

    // 先展开
    const link = screen.getByText("双击 / 点这里查看详情");
    fireEvent.click(link);

    // 点击裁定按钮
    fireEvent.click(screen.getByText("认可"));
    expect(onDecide).toHaveBeenCalledWith("adj-001", "accepted");

    fireEvent.click(screen.getByText("打回"));
    expect(onDecide).toHaveBeenCalledWith("adj-001", "returned", "请根据反馈返工。");

    fireEvent.click(screen.getByText("放弃"));
    expect(onDecide).toHaveBeenCalledWith("adj-001", "abandoned");
  });

  it("暂停续跑触发 onContinueGraph 回调", () => {
    const task = makeTask({
      displayPhase: "paused",
      suspendReason: "user_stop",
      status: "suspended",
    });
    const onContinueGraph = vi.fn();
    render(<TaskNodeCard task={task} onContinueGraph={onContinueGraph} />);

    // 点击"继续任务"按钮展开续跑表单
    const continueBtn = screen.getByText("继续任务");
    fireEvent.click(continueBtn);

    // 表单展开后，点击 Play 按钮提交
    const playBtn = screen.getByRole("button", { name: "继续" });
    fireEvent.click(playBtn);

    expect(onContinueGraph).toHaveBeenCalledWith("graph-001");
  });

  it("todo 子步骤默认不展示，展开后可见", () => {
    const task = makeTask();
    render(<TaskNodeCard task={task} todos={sampleTodos} />);

    // todo 不应默认可见
    expect(screen.queryByText("拉取数据")).toBeNull();

    // 先展开卡片
    const link = screen.getByText("双击 / 点这里查看详情");
    fireEvent.click(link);

    // 点击"查看子步骤"
    const todoToggle = screen.getByText("查看子步骤");
    fireEvent.click(todoToggle);

    expect(screen.getByText("拉取数据")).toBeDefined();
    expect(screen.getByText("清洗数据")).toBeDefined();
    expect(screen.getByText("输出结果")).toBeDefined();
  });

  it("展开 todo 时触发 onLoadTodos 回调", () => {
    const task = makeTask();
    const onLoadTodos = vi.fn();
    render(<TaskNodeCard task={task} onLoadTodos={onLoadTodos} />);

    // 先展开卡片
    const link = screen.getByText("双击 / 点这里查看详情");
    fireEvent.click(link);

    // 点击"查看子步骤"
    fireEvent.click(screen.getByText("查看子步骤"));

    expect(onLoadTodos).toHaveBeenCalledWith("tsk-001");
  });

  it("无 todo 时展开显示空状态", () => {
    const task = makeTask();
    render(<TaskNodeCard task={task} todos={[]} />);

    // 先展开卡片
    const link = screen.getByText("双击 / 点这里查看详情");
    fireEvent.click(link);

    // 点击"查看子步骤"
    fireEvent.click(screen.getByText("查看子步骤"));

    expect(screen.getByText("暂无子步骤信息")).toBeDefined();
  });

  it("requiresConfirmation 节点显示标记", () => {
    const task = makeTask({
      requiresConfirmation: true,
    });
    render(<TaskNodeCard task={task} />);

    expect(screen.getByLabelText("需确认")).toBeDefined();
  });

  it("非暂停状态不显示续跑按钮", () => {
    const task = makeTask({ displayPhase: "running" });
    render(<TaskNodeCard task={task} onContinueGraph={vi.fn()} />);

    expect(screen.queryByText("继续任务")).toBeNull();
  });

  it("非审核状态不显示裁定按钮", () => {
    const task = makeTask({ requiresReview: false });
    render(<TaskNodeCard task={task} onDecide={vi.fn()} />);

    // 先展开
    const link = screen.getByText("双击 / 点这里查看详情");
    fireEvent.click(link);

    expect(screen.queryByText("认可")).toBeNull();
    expect(screen.queryByText("打回")).toBeNull();
    expect(screen.queryByText("放弃")).toBeNull();
  });
});
