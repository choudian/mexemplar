import { describe, expect, test } from "vitest";

import {
  deriveNodeTone,
  layoutDag,
  pickFocusTaskId,
  pickPeekNodes,
  NODE_WIDTH,
  NODE_HEIGHT,
  LAYER_GAP_Y,
  CANVAS_PADDING,
} from "../../src/components/taskGraph/layoutDag";
import type {
  AssistantTaskSnapshot,
  AssistantTaskEdgeSnapshot,
} from "../../src/api/assistantTasks";

// ── 工厂 ──────────────────────────────────────────────────────────────────

function makeTask(overrides: Partial<AssistantTaskSnapshot>): AssistantTaskSnapshot {
  return {
    taskId: overrides.taskId ?? "t1",
    graphId: "g1",
    parentTaskId: null,
    title: overrides.title ?? "Task 1",
    descriptionPreview: "",
    status: overrides.status ?? "pending_dispatch",
    displayPhase: overrides.displayPhase ?? "running",
    requiresReview: false,
    requiresConfirmation: false,
    safeExplanation: "",
    suspendReason: overrides.suspendReason,
    waitingOn: overrides.waitingOn,
    ...overrides,
  };
}

function edge(source: string, target: string): AssistantTaskEdgeSnapshot {
  return { sourceTaskId: source, targetTaskId: target, type: "dependency" };
}

// ── deriveNodeTone ────────────────────────────────────────────────────────

describe("deriveNodeTone", () => {
  test("done and skipped → done", () => {
    expect(deriveNodeTone(makeTask({ status: "done" }))).toBe("done");
    expect(deriveNodeTone(makeTask({ status: "skipped" }))).toBe("done");
  });

  test("running → run", () => {
    expect(deriveNodeTone(makeTask({ status: "running" }))).toBe("run");
  });

  test("suspended + waiting_on=user → you", () => {
    expect(
      deriveNodeTone(makeTask({ status: "suspended", waitingOn: "user", suspendReason: "waiting_user" })),
    ).toBe("you");
  });

  test("suspended + blocked_by_defect → bug", () => {
    expect(
      deriveNodeTone(makeTask({ status: "suspended", suspendReason: "blocked_by_defect", waitingOn: "assistant" })),
    ).toBe("bug");
  });

  test("pending_dispatch → todo", () => {
    expect(deriveNodeTone(makeTask({ status: "pending_dispatch", displayPhase: "paused" }))).toBe("todo");
  });
});

// ── pickFocusTaskId ───────────────────────────────────────────────────────

describe("pickFocusTaskId", () => {
  test("needs_attention beats running", () => {
    const tasks = [
      makeTask({ taskId: "a", displayPhase: "running" }),
      makeTask({ taskId: "b", displayPhase: "needs_attention" }),
    ];
    expect(pickFocusTaskId(tasks)).toBe("b");
  });

  test("同优先级取第一个（created 原序）", () => {
    const tasks = [
      makeTask({ taskId: "a", displayPhase: "running" }),
      makeTask({ taskId: "b", displayPhase: "running" }),
    ];
    expect(pickFocusTaskId(tasks)).toBe("a");
  });

  test("空列表返回 null", () => {
    expect(pickFocusTaskId([])).toBeNull();
  });
});

// ── pickPeekNodes ─────────────────────────────────────────────────────────

describe("pickPeekNodes", () => {
  test("线性链：focus + 前置 + 下游", () => {
    const tasks = [
      makeTask({ taskId: "a", status: "done", displayPhase: "done" }),
      makeTask({ taskId: "b", status: "suspended", displayPhase: "needs_attention", suspendReason: "blocked_by_defect", waitingOn: "assistant" }),
      makeTask({ taskId: "c", status: "pending_dispatch", displayPhase: "paused" }),
    ];
    const edges = [edge("a", "b"), edge("b", "c")];
    const result = pickPeekNodes(tasks, edges);
    expect(result.has("b")).toBe(true); // focus
    expect(result.has("a")).toBe(true); // 前置
    expect(result.has("c")).toBe(true); // 下游
  });

  test("全跑完 → 空集", () => {
    const tasks = [
      makeTask({ taskId: "a", status: "done", displayPhase: "done" }),
      makeTask({ taskId: "b", status: "done", displayPhase: "done" }),
    ];
    const result = pickPeekNodes(tasks, [edge("a", "b")]);
    expect(result.size).toBe(0);
  });

  test("单节点 → 空集", () => {
    const result = pickPeekNodes([makeTask({ taskId: "a" })], []);
    expect(result.size).toBe(0);
  });
});

// ── layoutDag ─────────────────────────────────────────────────────────────

describe("layoutDag", () => {
  test("空图返回空布局", () => {
    const result = layoutDag([], []);
    expect(result.nodes).toHaveLength(0);
    expect(result.focusTaskId).toBeNull();
  });

  test("单节点不画图", () => {
    const result = layoutDag([makeTask({ taskId: "a" })], []);
    expect(result.nodes).toHaveLength(0);
  });

  test("线性链：层号递增", () => {
    const tasks = [
      makeTask({ taskId: "a", status: "done", displayPhase: "done" }),
      makeTask({ taskId: "b", status: "running", displayPhase: "running" }),
      makeTask({ taskId: "c", status: "pending_dispatch", displayPhase: "paused" }),
    ];
    const edges = [edge("a", "b"), edge("b", "c")];
    const result = layoutDag(tasks, edges);
    expect(result.nodes).toHaveLength(3);
    const layers = result.nodes.map((n) => n.layer);
    expect(layers).toEqual([0, 1, 2]);
  });

  test("分叉后汇合：汇合节点取最长路径", () => {
    // a → b → d
    // a → c → d  (d 有两条入边)
    const tasks = [
      makeTask({ taskId: "a", displayPhase: "running" }),
      makeTask({ taskId: "b", displayPhase: "running" }),
      makeTask({ taskId: "c", displayPhase: "running" }),
      makeTask({ taskId: "d", displayPhase: "running" }),
    ];
    const edges = [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")];
    const result = layoutDag(tasks, edges);
    const dNode = result.nodes.find((n) => n.taskId === "d")!;
    // d 的最长路径是 a→b→d 或 a→c→d，都是 2 层
    expect(dNode.layer).toBe(2);
  });

  test("多个根节点", () => {
    const tasks = [
      makeTask({ taskId: "r1", displayPhase: "running" }),
      makeTask({ taskId: "r2", displayPhase: "running" }),
      makeTask({ taskId: "c", displayPhase: "running" }),
    ];
    const edges = [edge("r1", "c"), edge("r2", "c")];
    const result = layoutDag(tasks, edges);
    const r1 = result.nodes.find((n) => n.taskId === "r1")!;
    const r2 = result.nodes.find((n) => n.taskId === "r2")!;
    expect(r1.layer).toBe(0);
    expect(r2.layer).toBe(0);
  });

  test("成环不死循环，回边被标记", () => {
    // a → b → c → a（环）
    const tasks = [
      makeTask({ taskId: "a", displayPhase: "running" }),
      makeTask({ taskId: "b", displayPhase: "running" }),
      makeTask({ taskId: "c", displayPhase: "running" }),
    ];
    const edges = [edge("a", "b"), edge("b", "c"), edge("c", "a")];
    // 不应抛异常
    const result = layoutDag(tasks, edges);
    expect(result.nodes).toHaveLength(3);
    // 至少有一条边被标为回边
    expect(result.edges.some((e) => e.backEdge)).toBe(true);
  });

  test("坐标基于层号和层内位置", () => {
    const tasks = [
      makeTask({ taskId: "a", status: "done", displayPhase: "done" }),
      makeTask({ taskId: "b", status: "running", displayPhase: "running" }),
    ];
    const result = layoutDag(tasks, [edge("a", "b")]);
    const a = result.nodes.find((n) => n.taskId === "a")!;
    const b = result.nodes.find((n) => n.taskId === "b")!;
    expect(a.x).toBe(CANVAS_PADDING);
    expect(a.y).toBe(CANVAS_PADDING);
    expect(b.y).toBe(CANVAS_PADDING + LAYER_GAP_Y + NODE_HEIGHT);
  });

  test("focusTaskId 选 needs_attention", () => {
    const tasks = [
      makeTask({ taskId: "a", status: "done", displayPhase: "done" }),
      makeTask({ taskId: "b", status: "suspended", displayPhase: "needs_attention", suspendReason: "blocked_by_defect", waitingOn: "assistant" }),
    ];
    const result = layoutDag(tasks, [edge("a", "b")]);
    expect(result.focusTaskId).toBe("b");
    const b = result.nodes.find((n) => n.taskId === "b")!;
    expect(b.attention).toBe(true);
  });

  test("blocked 边：target suspended + waiting_on=user", () => {
    const tasks = [
      makeTask({ taskId: "a", status: "done", displayPhase: "done" }),
      makeTask({ taskId: "b", status: "suspended", displayPhase: "paused", suspendReason: "waiting_user", waitingOn: "user" }),
    ];
    const result = layoutDag(tasks, [edge("a", "b")]);
    expect(result.edges[0].blocked).toBe(true);
  });

  test("画布尺寸正确", () => {
    const tasks = [
      makeTask({ taskId: "a", displayPhase: "running" }),
      makeTask({ taskId: "b", displayPhase: "running" }),
    ];
    const result = layoutDag(tasks, [edge("a", "b")]);
    expect(result.width).toBeGreaterThan(NODE_WIDTH);
    expect(result.height).toBeGreaterThan(NODE_HEIGHT);
  });
});
