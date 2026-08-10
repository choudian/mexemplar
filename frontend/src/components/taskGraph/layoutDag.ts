/**
 * DAG 布局纯函数（⑦ 任务图可视化）。
 *
 * 按 `2026-07-21-task-graph-dag-viewer-design.md` 实现手写分层布局（Sugiyama 简化版），
 * 不引入 reactflow / dagre / d3 等图形库。
 *
 * 输入 tasks + edges，输出每个节点的层号与坐标、每条边的 SVG path。
 * 纯函数，无 React 依赖，可直接单测。
 */

import type {
  AssistantTaskSnapshot,
  AssistantTaskEdgeSnapshot,
} from "../../api/assistantTasks";

// ── 布局常量 ──────────────────────────────────────────────────────────────

/** 节点固定宽度（px）。mockup 用 120-140，取 140 容纳中文标题。 */
export const NODE_WIDTH = 140;
/** 节点高度（px）。 */
export const NODE_HEIGHT = 26;
/** 同层节点之间的水平间距（px）。 */
export const NODE_GAP_X = 48;
/** 层与层之间的垂直间距（px）。 */
export const LAYER_GAP_Y = 38;
/** 画布四周留白（px）。 */
export const CANVAS_PADDING = 18;

// ── 类型 ──────────────────────────────────────────────────────────────────

/** 节点在画布上的视觉色调，对应 mockup 的 `data-t`。 */
export type NodeTone = "done" | "run" | "you" | "bug" | "todo";

/** 布局后的单个节点。 */
export interface DagLayoutNode {
  taskId: string;
  title: string;
  tone: NodeTone;
  /** x 坐标（节点左上角）。 */
  x: number;
  /** y 坐标（节点左上角）。 */
  y: number;
  layer: number;
  width: number;
  height: number;
  /** 是否是当前最需要注意的节点（用于高亮/attn-ring）。 */
  attention: boolean;
}

/** 布局后的单条边。 */
export interface DagLayoutEdge {
  sourceTaskId: string;
  targetTaskId: string;
  /** SVG `d` 属性值。 */
  path: string;
  /** 是否是被阻塞的依赖（target 停住且需人处理）。 */
  blocked: boolean;
  /** 是否是回边（环上的边），虚线绘制。 */
  backEdge: boolean;
}

/** 完整布局结果。 */
export interface DagLayout {
  nodes: DagLayoutNode[];
  edges: DagLayoutEdge[];
  /** 画布总宽度（含留白）。 */
  width: number;
  /** 画布总高度（含留白）。 */
  height: number;
  /** 自动定位的「最需要注意」节点 id。 */
  focusTaskId: string | null;
}

// ── 辅助函数 ──────────────────────────────────────────────────────────────

/**
 * 把 task 的 status / displayPhase / waitingOn 映射成视觉色调。
 *
 * 判据与 mockup 一致：
 * - done/skipped → done（绿色）
 * - running → run（强调色）
 * - suspended + waiting_on=user → you（琥珀色）
 * - suspended + suspendReason=blocked_by_defect → bug（红色）
 * - suspended（其余）→ bug（红色，「需处理」/「等待中」共用）
 * - 其余 → todo（灰色）
 */
export function deriveNodeTone(task: AssistantTaskSnapshot): NodeTone {
  const { status, displayPhase, waitingOn, suspendReason } = task;
  if (status === "done" || status === "skipped") return "done";
  // suspended 优先于 displayPhase——status 是事实来源，displayPhase 是派生的
  if (status === "suspended") {
    if (waitingOn === "user") return "you";
    if (suspendReason === "blocked_by_defect") return "bug";
    return "bug";
  }
  if (status === "running" || displayPhase === "running") return "run";
  if (status === "delivered" || displayPhase === "reviewing") return "run";
  return "todo";
}

/** displayPhase 优先级：数字越小越优先。用于选 focus 节点。 */
const PHASE_PRIORITY: Record<string, number> = {
  needs_attention: 0,
  reviewing: 1,
  paused: 2,
  running: 3,
  done: 4,
};

/**
 * 按优先级 `needs_attention > reviewing > paused > running > done` 选最需要注意的节点。
 * 同优先级取层号最小；层号相同取层内序号最小。
 */
export function pickFocusTaskId(tasks: AssistantTaskSnapshot[]): string | null {
  if (tasks.length === 0) return null;
  let bestId: string | null = null;
  let bestPriority = Infinity;
  let bestOrder = Infinity;
  tasks.forEach((task, index) => {
    const priority = PHASE_PRIORITY[task.displayPhase] ?? 5;
    if (priority < bestPriority || (priority === bestPriority && index < bestOrder)) {
      bestId = task.taskId;
      bestPriority = priority;
      bestOrder = index;
    }
  });
  return bestId;
}

/**
 * 局部图裁剪：选 focus 节点 + 它的直接前置 + 被它挡住的下游。
 *
 * 设计 383-388 行的确定性规则：
 * - 有卡住的 → 卡住那个 + 直接前置 + 被它挡住的下游
 * - 没卡住，有在跑的 → 正在跑的 + 刚完成的前置 + 下一个
 * - 全跑完了 → 返回空集（不画局部图）
 */
export function pickPeekNodes(
  tasks: AssistantTaskSnapshot[],
  edges: AssistantTaskEdgeSnapshot[],
): Set<string> {
  if (tasks.length <= 1) return new Set();
  const focusId = pickFocusTaskId(tasks);
  if (!focusId) return new Set();

  const result = new Set<string>([focusId]);

  // 直接前置（edges 指向 focus 的 source）
  for (const edge of edges) {
    if (edge.targetTaskId === focusId) {
      result.add(edge.sourceTaskId);
    }
  }

  // 被它挡住的下游（edges 从 focus 出发，且 target 还没 done/skipped）
  for (const edge of edges) {
    if (edge.sourceTaskId === focusId) {
      const target = tasks.find((t) => t.taskId === edge.targetTaskId);
      if (target && target.status !== "done" && target.status !== "skipped") {
        result.add(edge.targetTaskId);
      }
    }
  }

  // 全跑完了不画局部图
  const allDone = tasks.every((t) => t.status === "done" || t.status === "skipped");
  if (allDone) return new Set();

  return result;
}

// ── 布局核心 ──────────────────────────────────────────────────────────────

/**
 * 分层布局：用最长路径给每个节点分层。
 *
 * 层号 = 从任一根到它的最长路径长度。用最长路径（而非最短）保证所有前驱
 * 严格位于更上层，连线永远向下。
 *
 * 回边检测：拓扑排序后若仍有未定层节点，说明有环；环上的边标为回边，
 * 计算层号时忽略回边但仍然画出来。绝不死循环。
 */
function computeLayers(
  taskIds: string[],
  adjacency: Map<string, string[]>,
): { layers: Map<string, number>; backEdges: Set<string> } {
  const layers = new Map<string, number>();
  const backEdges = new Set<string>();

  // 只考虑「前驱→后继」方向的边（adjacency 已是这个方向）
  // 先检测回边：如果 target 的层号已 >= source 的层号（source 已定层），则这条边是回边
  // 使用 Kahn 拓扑排序 + 最长路径

  // 构建入度表
  const inDegree = new Map<string, number>();
  taskIds.forEach((id) => inDegree.set(id, 0));
  adjacency.forEach((successors) => {
    successors.forEach((succ) => {
      inDegree.set(succ, (inDegree.get(succ) ?? 0) + 1);
    });
  });

  // 用队列做 Kahn 排序，同时计算最长路径层号
  const queue: string[] = [];
  taskIds.forEach((id) => {
    if ((inDegree.get(id) ?? 0) === 0) {
      layers.set(id, 0);
      queue.push(id);
    }
  });

  // 构建「前驱」反向索引（谁指向这个节点）
  const predecessors = new Map<string, string[]>();
  taskIds.forEach((id) => predecessors.set(id, []));
  adjacency.forEach((successors, source) => {
    successors.forEach((succ) => {
      predecessors.get(succ)?.push(source);
    });
  });

  let processed = 0;
  while (queue.length > 0) {
    const current = queue.shift()!;
    processed++;
    const currentLayer = layers.get(current) ?? 0;
    const successors = adjacency.get(current) ?? [];
    for (const succ of successors) {
      // 最长路径：取 max(当前层号, 前驱层号 + 1)
      const candidate = currentLayer + 1;
      if (candidate > (layers.get(succ) ?? -1)) {
        layers.set(succ, candidate);
      }
      const newDeg = (inDegree.get(succ) ?? 1) - 1;
      inDegree.set(succ, newDeg);
      if (newDeg === 0) {
        queue.push(succ);
      }
    }
  }

  // 如果有未处理的节点（环），给它们一个层号（max 前驱层 + 1，忽略环边）
  if (processed < taskIds.length) {
    for (const id of taskIds) {
      if (!layers.has(id)) {
        const preds = predecessors.get(id) ?? [];
        let maxPredLayer = 0;
        for (const pred of preds) {
          if (layers.has(pred)) {
            maxPredLayer = Math.max(maxPredLayer, (layers.get(pred) ?? 0) + 1);
          }
        }
        layers.set(id, maxPredLayer);
      }
    }
    // 标记回边：source 层号 >= target 层号的边
    adjacency.forEach((successors, source) => {
      const sourceLayer = layers.get(source) ?? 0;
      successors.forEach((succ) => {
        const succLayer = layers.get(succ) ?? 0;
        if (succLayer <= sourceLayer) {
          backEdges.add(`${source}->${succ}`);
        }
      });
    });
  }

  return { layers, backEdges };
}

/**
 * 层内排序：按前驱节点的平均横向位置排序；根节点按 tasks 数组原序。
 *
 * 这是启发式，不追求交叉数最优。
 */
function orderWithinLayers(
  taskIds: string[],
  layers: Map<string, number>,
  predecessors: Map<string, string[]>,
  nodeOrder: Map<string, number>,
): Map<string, number> {
  // 按层分组
  const maxLayer = Math.max(0, ...layers.values());
  const nodesByLayer: string[][] = Array.from({ length: maxLayer + 1 }, () => []);

  // 先把节点按 created_at 原序填入各层（保证根节点原序）
  taskIds.forEach((id) => {
    const layer = layers.get(id) ?? 0;
    nodesByLayer[layer].push(id);
  });

  // 层内排序：按前驱平均位置
  const positionInLayer = new Map<string, number>();
  for (let layer = 0; layer <= maxLayer; layer++) {
    const nodes = nodesByLayer[layer];
    if (layer === 0) {
      // 根层：保持原序
      nodes.forEach((id, index) => positionInLayer.set(id, index));
      continue;
    }
    // 非根层：按前驱平均位置排序，无前驱的按原序排末尾
    const withAvg = nodes.map((id, index) => {
      const preds = predecessors.get(id) ?? [];
      const predPositions = preds
        .map((p) => positionInLayer.get(p))
        .filter((p): p is number => p !== undefined);
      const avg = predPositions.length > 0
        ? predPositions.reduce((a, b) => a + b, 0) / predPositions.length
        : Number.MAX_SAFE_INTEGER;
      return { id, avg, fallback: index };
    });
    withAvg.sort((a, b) => {
      if (a.avg !== b.avg) return a.avg - b.avg;
      return a.fallback - b.fallback;
    });
    withAvg.forEach((item, index) => positionInLayer.set(item.id, index));
  }

  return positionInLayer;
}

/**
 * 生成 SVG path：从 source 底边到 target 顶边的贝塞尔曲线。
 *
 * 如果是回边（source 在 target 下方或同层），画成绕过去的曲线。
 */
function edgePath(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
  backEdge: boolean,
): string {
  const sourceBottomY = sy + NODE_HEIGHT;
  const targetTopY = ty;
  if (backEdge) {
    // 回边：画一条绕到右侧的 C 曲线
    const midY = (sourceBottomY + targetTopY) / 2;
    return `M${sx + NODE_WIDTH / 2},${sourceBottomY} C${sx + NODE_WIDTH / 2},${midY + 20} ${tx + NODE_WIDTH / 2},${midY - 20} ${tx + NODE_WIDTH / 2},${targetTopY}`;
  }
  // 正常边：简单的 C 曲线
  const midY = (sourceBottomY + targetTopY) / 2;
  return `M${sx + NODE_WIDTH / 2},${sourceBottomY} C${sx + NODE_WIDTH / 2},${midY} ${tx + NODE_WIDTH / 2},${midY} ${tx + NODE_WIDTH / 2},${targetTopY}`;
}

/**
 * 完整布局：tasks + edges → DagLayout。
 *
 * 空图或单节点返回空布局（设计 114-118 行：单节点不显示图入口）。
 */
export function layoutDag(
  tasks: AssistantTaskSnapshot[],
  edges: AssistantTaskEdgeSnapshot[],
): DagLayout {
  if (tasks.length <= 1) {
    return { nodes: [], edges: [], width: 0, height: 0, focusTaskId: null };
  }

  const taskIds = tasks.map((t) => t.taskId);
  const taskMap = new Map(tasks.map((t) => [t.taskId, t]));
  const nodeOrder = new Map(taskIds.map((id, i) => [id, i]));

  // 构建邻接表（source → [targets]），只保留两端都在 tasks 里的边
  const adjacency = new Map<string, string[]>();
  taskIds.forEach((id) => adjacency.set(id, []));
  edges.forEach((edge) => {
    if (taskMap.has(edge.sourceTaskId) && taskMap.has(edge.targetTaskId)) {
      adjacency.get(edge.sourceTaskId)?.push(edge.targetTaskId);
    }
  });

  // 构建前驱索引
  const predecessors = new Map<string, string[]>();
  taskIds.forEach((id) => predecessors.set(id, []));
  edges.forEach((edge) => {
    if (taskMap.has(edge.sourceTaskId) && taskMap.has(edge.targetTaskId)) {
      predecessors.get(edge.targetTaskId)?.push(edge.sourceTaskId);
    }
  });

  // 1. 分层
  const { layers, backEdges } = computeLayers(taskIds, adjacency);

  // 2. 层内排序
  const positionInLayer = orderWithinLayers(taskIds, layers, predecessors, nodeOrder);

  // 3. 计算坐标
  const maxLayer = Math.max(0, ...layers.values());
  // 每层节点数
  const layerCounts = new Map<number, number>();
  layers.forEach((layer) => {
    layerCounts.set(layer, (layerCounts.get(layer) ?? 0) + 1);
  });
  const maxNodesInLayer = Math.max(1, ...layerCounts.values());

  const nodes: DagLayoutNode[] = [];
  const focusTaskId = pickFocusTaskId(tasks);

  for (const task of tasks) {
    const id = task.taskId;
    const layer = layers.get(id) ?? 0;
    const posInLayer = positionInLayer.get(id) ?? 0;
    const x = CANVAS_PADDING + posInLayer * (NODE_WIDTH + NODE_GAP_X);
    const y = CANVAS_PADDING + layer * (NODE_HEIGHT + LAYER_GAP_Y);
    const tone = deriveNodeTone(task);
    nodes.push({
      taskId: id,
      title: task.title,
      tone,
      x,
      y,
      layer,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      attention: id === focusTaskId,
    });
  }

  // 4. 画边
  const layoutEdges: DagLayoutEdge[] = [];
  for (const edge of edges) {
    if (!taskMap.has(edge.sourceTaskId) || !taskMap.has(edge.targetTaskId)) continue;
    const sourceNode = nodes.find((n) => n.taskId === edge.sourceTaskId)!;
    const targetNode = nodes.find((n) => n.taskId === edge.targetTaskId)!;
    const backEdge = backEdges.has(`${edge.sourceTaskId}->${edge.targetTaskId}`);
    // blocked：target 停住且需人处理（waiting_on=user 或 blocked_by_defect）
    const target = taskMap.get(edge.targetTaskId)!;
    const blocked =
      target.status === "suspended" &&
      (target.waitingOn === "user" ||
        target.suspendReason === "blocked_by_defect");
    layoutEdges.push({
      sourceTaskId: edge.sourceTaskId,
      targetTaskId: edge.targetTaskId,
      path: edgePath(sourceNode.x, sourceNode.y, targetNode.x, targetNode.y, backEdge),
      blocked,
      backEdge,
    });
  }

  // 5. 画布尺寸
  const width = CANVAS_PADDING * 2 + maxNodesInLayer * (NODE_WIDTH + NODE_GAP_X) - NODE_GAP_X;
  const height = CANVAS_PADDING * 2 + (maxLayer + 1) * (NODE_HEIGHT + LAYER_GAP_Y) - LAYER_GAP_Y;

  return { nodes, edges: layoutEdges, width, height, focusTaskId };
}
