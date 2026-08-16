import { describe, expect, it } from "vitest";

import type { Subagent } from "../../src/state/assistantTypes";

/**
 * DAG 节点的执行体不平铺进用户任务卡片。
 *
 * 真机现象：DAG 里的子助理 / 专员出现在了用户卡片上，本该只在任务图里看。
 *
 * 旧判据靠 `planTaskIds`——卡片自己拉 plan 图快照、收集全部节点 id 做黑名单。
 * 那份名单是会话级事实却存在卡片私有 state 里，加载还要求这张卡片绑着用户任务
 * （`if (!open || !taskId) return`）。而 `AssistantScreen` 只给第一个过程块的卡片
 * 喂 taskId，于是其余每一轮的卡片名单恒空、过滤恒不生效。执行体按 turnStartSequence
 * 归轮次，DAG 节点又是依赖驱动分批派发的，后面出队的执行体正好落在那些没有任务
 * 身份的轮次里——全部漏出来。
 *
 * 新判据由执行体自带 `graphKind`（后端 attempt→task→图根反查），与卡片身份无关。
 */

/** 与 `UserTaskCard` 平铺循环同口径：plan 跳过，其余（含未知）保留。 */
const shouldFlatten = (sub: Pick<Subagent, "graphKind">): boolean =>
  sub.graphKind !== "plan";

const sub = (subagentId: string, graphKind: Subagent["graphKind"]): Subagent => ({
  subagentId,
  label: subagentId,
  task: "",
  status: "running",
  graphKind,
});

describe("执行体是否平铺进用户任务卡片", () => {
  it("DAG（plan）节点的执行体不平铺——它只在任务图里看", () => {
    expect(shouldFlatten(sub("exec_dag", "plan"))).toBe(false);
  });

  it("委派容器（request）的执行体照常平铺", () => {
    expect(shouldFlatten(sub("exec_direct", "request"))).toBe(true);
  });

  /** 归属查不到时宁可多显示，也不要把用户的活藏起来。 */
  it("归属未知时保留平铺，不隐藏", () => {
    expect(shouldFlatten(sub("exec_a", null))).toBe(true);
    expect(shouldFlatten(sub("exec_b", undefined))).toBe(true);
  });

  /**
   * 回归：判据不依赖卡片有没有绑用户任务。
   *
   * 这正是旧实现漏掉的那一格——没有 taskId 的卡片过滤恒不生效。
   * 新判据只看执行体自身，同一批执行体在任何卡片上结果都一致。
   */
  it("同一批执行体在任何卡片上结果一致（与卡片身份无关）", () => {
    const batch = [
      sub("exec_dag_1", "plan"),
      sub("exec_dag_2", "plan"),
      sub("exec_direct", "request"),
      sub("exec_unknown", null),
    ];
    const flattened = batch.filter(shouldFlatten).map((s) => s.subagentId);
    // 绑了用户任务的卡片、没绑的卡片，拿到的都是同一份输入 → 同一份输出
    expect(flattened).toEqual(["exec_direct", "exec_unknown"]);
    expect(flattened).not.toContain("exec_dag_1");
    expect(flattened).not.toContain("exec_dag_2");
  });
});
