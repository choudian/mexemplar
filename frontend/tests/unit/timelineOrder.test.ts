import { describe, expect, it } from "vitest";

import { NO_ANCHOR, executorAnchorSeq, graphAnchorSeq } from "../../src/screens/assistant/timelineOrder";
import type { ActivityStep } from "../../src/state/assistantTypes";

const GRAPH = "tg_49ac87baaaad40b5";

const step = (seq: number, toolName: string | undefined, text: string): ActivityStep => ({
  seq,
  kind: toolName ? (seq % 2 === 1 ? "tool_call" : "tool_result") : "reasoning",
  toolName,
  text,
  subagentId: null,
  redacted: false,
});

/**
 * 真机那一轮的实际步骤序列（会话 ast_23fe2cf36171）：
 * 先建用户任务、委派规划专员、回话，裁定回流之后第 13 步才启动图。
 */
const realTurnSteps: ActivityStep[] = [
  step(1, "create_task", '{"title":"E:\\\\code\\\\Exemplar 各模块分析报告"}'),
  step(2, "create_task", '{"success": true, "userTaskId": "utsk_8f2933dfed8f4c9b"}'),
  step(3, "delegate_to_planner", '{"task":"对 E:\\\\code\\\\Exemplar 项目进行各模块分析"}'),
  step(4, "delegate_to_planner", '{"accepted": true, "taskId": "tsk_aecc84"}'),
  step(5, "reply_to_user", '{"message":"已启动模块分析任务"}'),
  step(6, "reply_to_user", "已启动 E:\\code\\Exemplar 的模块分析任务！"),
  step(7, "decide_task_adjudication", '{"decision":"accept"}'),
  step(8, "decide_task_adjudication", '{"accepted": true, "adjudicationId": "adj_1"}'),
  step(9, "start_graph", `{"graphId": "${GRAPH}"}`),
  step(10, "start_graph", `{"success": true, "graphId": "${GRAPH}"}`),
  step(11, "reply_to_user", '{"message":"规划已完成，DAG 任务图已启动执行"}'),
];

describe("任务图在时间流里的位置", () => {
  it("锚到「启动图」那一步，而不是本轮开头", () => {
    expect(graphAnchorSeq(realTurnSteps, GRAPH)).toBe(10);
  });

  it("排在启动图之后，不再插到「创建任务」后面", () => {
    const anchor = graphAnchorSeq(realTurnSteps, GRAPH);
    const createTaskSeq = 2;
    const startGraphResultSeq = 10;
    const replyAfterStartSeq = 11;

    expect(anchor).toBeGreaterThan(createTaskSeq);
    expect(anchor).toBeGreaterThanOrEqual(startGraphResultSeq);
    expect(anchor).toBeLessThan(replyAfterStartSeq);
  });

  it("旧排序键（userMessageSequence）会把图插到「创建任务」后面", () => {
    // 真机上这张图的 userMessageSequence 是 2——那是"本轮用户消息在消息表里
    // 排第 2 条"，拿它当步骤号用，图就落在第 2 个步骤后面。
    const oldKey = 2;
    const newKey = graphAnchorSeq(realTurnSteps, GRAPH);

    const before = (key: number) =>
      realTurnSteps.filter((s) => s.seq <= key).map((s) => s.toolName);

    expect(before(oldKey)).toEqual(["create_task", "create_task"]);
    expect(before(oldKey)).not.toContain("start_graph");
    expect(before(newKey)).toContain("start_graph");
  });

  it("一轮建多张图时各自配对自己的 graphId", () => {
    const other = "tg_9815032e3b1a4200";
    const steps: ActivityStep[] = [
      step(3, "start_graph", `{"success": true, "graphId": "${other}"}`),
      step(7, "start_graph", `{"success": true, "graphId": "${GRAPH}"}`),
    ];
    expect(graphAnchorSeq(steps, other)).toBe(3);
    expect(graphAnchorSeq(steps, GRAPH)).toBe(7);
  });

  it("本轮没启动过这张图时排到末尾，不假装它先发生", () => {
    expect(graphAnchorSeq(realTurnSteps, "tg_不在本轮")).toBe(NO_ANCHOR);
    expect(graphAnchorSeq([], GRAPH)).toBe(NO_ANCHOR);
  });

  it("只认 start_graph 的步骤，别的工具提到 graphId 不算", () => {
    const steps: ActivityStep[] = [
      step(2, "reply_to_user", `任务图 ${GRAPH} 已经建好了`),
      step(6, "start_graph", `{"success": true, "graphId": "${GRAPH}"}`),
    ];
    expect(graphAnchorSeq(steps, GRAPH)).toBe(6);
  });
});

describe("执行体在时间流里的位置", () => {
  it("锚到「派出去」那一步——重启后实时锚点没了也能排对", () => {
    // 真机那轮：delegate_to_planner 在第 3/4 步，结果里带 taskId
    expect(executorAnchorSeq(realTurnSteps, "tsk_aecc84")).toBe(4);
  });

  it("排在委派之后、启动图之前，不再堆到末尾", () => {
    const executor = executorAnchorSeq(realTurnSteps, "tsk_aecc84");
    const graph = graphAnchorSeq(realTurnSteps, GRAPH);

    expect(executor).toBeLessThan(graph);
    expect(executor).not.toBe(NO_ANCHOR);
  });

  it("三种委派工具都认", () => {
    for (const tool of ["delegate_to_subagent", "delegate_to_planner", "delegate_to_specialist"]) {
      const steps = [step(4, tool, '{"accepted": true, "taskId": "tsk_x"}')];
      expect(executorAnchorSeq(steps, "tsk_x")).toBe(4);
    }
  });

  it("没有 taskId 或本轮没派过它时排到末尾", () => {
    expect(executorAnchorSeq(realTurnSteps, null)).toBe(NO_ANCHOR);
    expect(executorAnchorSeq(realTurnSteps, undefined)).toBe(NO_ANCHOR);
    expect(executorAnchorSeq(realTurnSteps, "tsk_别的轮次")).toBe(NO_ANCHOR);
  });
});
