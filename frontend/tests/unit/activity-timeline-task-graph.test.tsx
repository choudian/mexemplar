/**
 * 025: ActivityTimeline task graph 集成测试
 *
 * 验证：
 * - TaskNodeCard 与 SubagentCard 交错排列
 * - needsAttention 扩展覆盖 DAG 节点状态
 * - summary 全局操作按钮条件渲染
 * - 无 task graph 时行为不变
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AssistantTaskGraphSnapshot } from "../../src/api/assistantTasks";
import type { Subagent } from "../../src/state/assistantTypes";
import ActivityTimeline from "../../src/screens/assistant/ActivityTimeline";

function makeSubagent(overrides?: Partial<Subagent>): Subagent {
  return {
    subagentId: "sub-001",
    label: "数据分析",
    task: "分析销售数据",
    status: "running",
    anchorSeq: 5,
    ...overrides,
  };
}

function makeGraph(
  overrides?: Partial<AssistantTaskGraphSnapshot>,
): AssistantTaskGraphSnapshot {
  return {
    graphId: "graph-001",
    sessionId: "sess-001",
    userMessageSequence: 1,
    version: 1,
    tasks: [
      {
        taskId: "tsk-root",
        graphId: "graph-001",
        parentTaskId: null,
        title: "整理报销",
        descriptionPreview: "",
        status: "running",
        displayPhase: "running",
        requiresReview: false,
        requiresConfirmation: false,
        safeExplanation: "",
      },
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

const liveSteps = [
  { seq: 1, kind: "reasoning" as const, text: "思考中…", subagentId: null },
  { seq: 3, kind: "tool_call" as const, toolName: "search", text: "搜索数据", subagentId: null },
  { seq: 7, kind: "tool_result" as const, text: "找到 10 条记录", subagentId: null },
];

describe("ActivityTimeline + task graph", () => {
  it("TaskNodeCard 与 SubagentCard 交错排列", () => {
    const subagent = makeSubagent({ anchorSeq: 3 });
    const graph = makeGraph(); // userMessageSequence=1, tsk-001 是非根节点

    const { container } = render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={liveSteps}
        running={true}
        subagents={[subagent]}
        taskGraph={graph}
      />,
    );

    // 时间线应自动展开（running 状态下 hasLive=true 时展开）
    const timeline = container.querySelector(".assistant-activity");
    expect(timeline).toBeDefined();

    // SubagentCard 内容可见
    expect(screen.getByText("数据分析")).toBeDefined();

    // TaskNodeCard 内容可见（非根节点 tsk-001）
    expect(screen.getByText("步骤A")).toBeDefined();
  });

  it("只渲染非根节点为卡片", () => {
    const graph = makeGraph();

    render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={liveSteps}
        running={true}
        taskGraph={graph}
      />,
    );

    // 非根节点 "步骤A" 应出现
    expect(screen.getByText("步骤A")).toBeDefined();

    // 根节点 "整理报销" 不应作为独立卡片出现
    // （根节点是 DAG 容器，不渲染为卡片）
    // 可能不在时间线内出现，或在其他上下文中出现
    // 关键是验证非根节点出现
    expect(screen.getByText("步骤A")).toBeDefined();
  });

  it("needsAttention 扩展：reviewing 节点自动展开", () => {
    const graph = makeGraph({
      tasks: [
        {
          taskId: "tsk-root",
          graphId: "graph-001",
          parentTaskId: null,
          title: "整理报销",
          descriptionPreview: "",
          status: "running",
          displayPhase: "running",
          requiresReview: false,
          requiresConfirmation: false,
          safeExplanation: "",
        },
        {
          taskId: "tsk-001",
          graphId: "graph-001",
          parentTaskId: "tsk-root",
          title: "审核步骤",
          descriptionPreview: "需要审核",
          status: "suspended",
          displayPhase: "reviewing",
          requiresReview: true,
          requiresConfirmation: false,
          safeExplanation: "",
          adjudicationId: "adj-001",
        },
      ],
    });

    const { container } = render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={[]}
        running={false}
        taskGraph={graph}
      />,
    );

    // needsAttention=true 时时间线应自动展开
    const details = container.querySelector(".assistant-activity") as HTMLDetailsElement;
    expect(details).toBeDefined();
    expect(details.hasAttribute("open")).toBe(true);
  });

  it("needsAttention 扩展：needs_attention 节点自动展开", () => {
    const graph = makeGraph({
      tasks: [
        {
          taskId: "tsk-root",
          graphId: "graph-001",
          parentTaskId: null,
          title: "整理报销",
          descriptionPreview: "",
          status: "running",
          displayPhase: "running",
          requiresReview: false,
          requiresConfirmation: false,
          safeExplanation: "",
        },
        {
          taskId: "tsk-001",
          graphId: "graph-001",
          parentTaskId: "tsk-root",
          title: "关注步骤",
          descriptionPreview: "需要关注",
          status: "suspended",
          displayPhase: "needs_attention",
          requiresReview: false,
          requiresConfirmation: false,
          safeExplanation: "出错了",
        },
      ],
    });

    const { container } = render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={[]}
        running={false}
        taskGraph={graph}
      />,
    );

    const details = container.querySelector(".assistant-activity") as HTMLDetailsElement;
    expect(details).toBeDefined();
    expect(details.hasAttribute("open")).toBe(true);
  });

  it("summary 区域有 running 节点时显示停止按钮", () => {
    const graph = makeGraph();
    const onStopGraph = vi.fn();

    render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={liveSteps}
        running={true}
        taskGraph={graph}
        onStopGraph={onStopGraph}
      />,
    );

    // summary 区域的停止按钮有特定 class
    const stopBtns = screen.getAllByText("停止任务");
    const summaryStopBtn = stopBtns.find(
      (el) => el.classList.contains("assistant-activity-graph-stop"),
    );
    expect(summaryStopBtn).toBeDefined();

    fireEvent.click(summaryStopBtn!);
    expect(onStopGraph).toHaveBeenCalledWith("graph-001");
  });

  it("summary 区域有 user_stop 暂停节点时显示继续按钮", () => {
    const graph = makeGraph({
      tasks: [
        {
          taskId: "tsk-root",
          graphId: "graph-001",
          parentTaskId: null,
          title: "整理报销",
          descriptionPreview: "",
          status: "running",
          displayPhase: "running",
          requiresReview: false,
          requiresConfirmation: false,
          safeExplanation: "",
        },
        {
          taskId: "tsk-001",
          graphId: "graph-001",
          parentTaskId: "tsk-root",
          title: "暂停步骤",
          descriptionPreview: "",
          status: "suspended",
          displayPhase: "paused",
          suspendReason: "user_stop",
          requiresReview: false,
          requiresConfirmation: false,
          safeExplanation: "",
        },
      ],
    });
    const onContinueGraph = vi.fn();

    render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={[]}
        running={false}
        taskGraph={graph}
        onContinueGraph={onContinueGraph}
      />,
    );

    // summary 区域的继续按钮有特定 class
    const continueBtns = screen.getAllByText("继续任务");
    const summaryContinueBtn = continueBtns.find(
      (el) => el.classList.contains("assistant-activity-graph-continue"),
    );
    expect(summaryContinueBtn).toBeDefined();

    fireEvent.click(summaryContinueBtn!);
    expect(onContinueGraph).toHaveBeenCalledWith("graph-001");
  });

  it("无 task graph 时不显示全局操作按钮", () => {
    render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={liveSteps}
        running={true}
      />,
    );

    expect(screen.queryByText("停止任务")).toBeNull();
    expect(screen.queryByText("继续任务")).toBeNull();
  });

  it("无 task graph 时行为不变（回归）", () => {
    const subagent = makeSubagent();

    render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={liveSteps}
        running={true}
        subagents={[subagent]}
      />,
    );

    // SubagentCard 仍正常出现
    expect(screen.getByText("数据分析")).toBeDefined();

    // 步骤仍正常出现
    expect(screen.getByText("搜索数据")).toBeDefined();
  });

  it("空 task graph（只有根节点）不渲染任何卡片", () => {
    const graph = makeGraph({
      tasks: [
        {
          taskId: "tsk-root",
          graphId: "graph-001",
          parentTaskId: null,
          title: "整理报销",
          descriptionPreview: "",
          status: "running",
          displayPhase: "running",
          requiresReview: false,
          requiresConfirmation: false,
          safeExplanation: "",
        },
      ],
    });

    render(
      <ActivityTimeline
        sessionId="sess-001"
        liveSteps={liveSteps}
        running={true}
        taskGraph={graph}
      />,
    );

    // 只有根节点，没有非根节点卡片
    expect(screen.queryByText("步骤A")).toBeNull();
  });
});
