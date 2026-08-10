import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { getAssistantTaskGraph } from "../../api/assistantTasks";
import type { AssistantTaskGraphSnapshot } from "../../api/assistantTasks";
import { layoutDag, pickPeekNodes, CANVAS_PADDING, NODE_WIDTH } from "../../components/taskGraph/layoutDag";

/**
 * 局部图（⑦ 内嵌 132px 迷你 DAG）：只画卡住节点 + 前置 + 被挡下游。
 * 设计 372-389。点任意处或「看全图」→ onOpenFullGraph。
 */
function TaskGraphPeek({
  sessionId,
  graphId,
  title,
  onOpenFullGraph,
}: {
  sessionId: string;
  graphId: string;
  title: string;
  onOpenFullGraph: () => void;
}): JSX.Element | null {
  const [graph, setGraph] = useState<AssistantTaskGraphSnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getAssistantTaskGraph(sessionId, graphId)
      .then((g) => { if (active) setGraph(g); })
      .catch(() => { if (active) setGraph(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [sessionId, graphId]);

  if (loading) {
    return (
      <div className="me-peek">
        <div className="me-peek-head"><b>任务图</b><Loader2 size={12} className="assistant-spin" /></div>
      </div>
    );
  }

  if (!graph || graph.tasks.length <= 1) return null;

  const allDone = graph.tasks.every((t) => t.status === "done" || t.status === "skipped");
  if (allDone) return null;

  const fullLayout = layoutDag(graph.tasks, graph.edges);
  const peekIds = pickPeekNodes(graph.tasks, graph.edges);
  if (peekIds.size === 0) return null;

  const peekNodes = fullLayout.nodes.filter((n) => peekIds.has(n.taskId));
  const peekEdges = fullLayout.edges.filter(
    (e) => peekIds.has(e.sourceTaskId) && peekIds.has(e.targetTaskId),
  );

  const minX = Math.min(...peekNodes.map((n) => n.x)) - CANVAS_PADDING;
  const maxX = Math.max(...peekNodes.map((n) => n.x + n.width)) + CANVAS_PADDING;
  const viewWidth = Math.max(320, maxX - minX);

  const focusNode = graph.tasks.find((t) => t.taskId === fullLayout.focusTaskId);
  const why = focusNode
    ? focusNode.status === "suspended" && focusNode.suspendReason === "blocked_by_defect"
      ? `· 卡在「${focusNode.title}」`
      : focusNode.waitingOn === "user"
        ? `· 等你回答「${focusNode.title}」`
        : `· 正在干「${focusNode.title}」`
    : "";

  const blockedDownstream = graph.edges.filter(
    (e) => e.sourceTaskId === fullLayout.focusTaskId && peekIds.has(e.targetTaskId),
  ).length;

  return (
    <div className="me-peek">
      <div className="me-peek-head">
        <b>任务图</b>
        <span className="why">{why}{blockedDownstream > 0 ? `，挡住 ${blockedDownstream} 步` : ""}</span>
        <button type="button" className="more" onClick={onOpenFullGraph}>
          看全图（{graph.tasks.length} 个节点）▸
        </button>
      </div>
      <div className="me-peek-canvas" onClick={onOpenFullGraph} style={{ cursor: "pointer" }}>
        <svg viewBox={`${minX} 0 ${viewWidth} 132`}>
          {peekEdges.map((edge, i) => (
            <path key={`e${i}`} className={`edge${edge.blocked ? " blocked" : ""}${edge.backEdge ? " back-edge" : ""}`} d={edge.path} />
          ))}
          {peekNodes.map((node) => {
            const isFocus = node.taskId === fullLayout.focusTaskId;
            return (
              <g key={node.taskId} className={`nd${isFocus ? " sel" : ""}`} data-t={node.tone} data-n={node.taskId} transform={`translate(${node.x},${node.y})`}>
                <rect width={NODE_WIDTH} height={node.height} />
                <text x={11} y={17}>{node.title}</text>
                {isFocus ? <rect className="attn-ring" x={-5} y={-5} width={NODE_WIDTH + 10} height={node.height + 10} rx={10} /> : null}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export default TaskGraphPeek;
