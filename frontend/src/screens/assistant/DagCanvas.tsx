import { useCallback, useRef, useState } from "react";

import type { DagLayout } from "../../components/taskGraph/layoutDag";

/**
 * DAG 画布（哑组件）：接收布局结果画 SVG，管理选中态、平移、缩放。
 *
 * 不引图形库，纯 SVG + transform。拖拽改 translate，滚轮改 scale，双击复位。
 */
function DagCanvas({
  layout,
  selectedTaskId,
  onSelectTask,
  className,
}: {
  layout: DagLayout;
  selectedTaskId: string | null;
  onSelectTask: (taskId: string) => void;
  className?: string;
}): JSX.Element {
  const svgRef = useRef<SVGSVGElement>(null);
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  const dragState = useRef<{ startX: number; startY: number; baseTx: number; baseTy: number } | null>(null);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      dragState.current = { startX: e.clientX, startY: e.clientY, baseTx: tx, baseTy: ty };
    },
    [tx, ty],
  );

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragState.current) return;
    setTx(dragState.current.baseTx + (e.clientX - dragState.current.startX));
    setTy(dragState.current.baseTy + (e.clientY - dragState.current.startY));
  }, []);

  const handleMouseUp = useCallback(() => { dragState.current = null; }, []);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      const newScale = Math.max(0.3, Math.min(3, scale * delta));
      const ratio = newScale / scale;
      setTx(mx - (mx - tx) * ratio);
      setTy(my - (my - ty) * ratio);
      setScale(newScale);
    },
    [scale, tx, ty],
  );

  const handleDoubleClick = useCallback(() => { setScale(1); setTx(0); setTy(0); }, []);

  return (
    <svg
      ref={svgRef}
      className={className}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onWheel={handleWheel}
      onDoubleClick={handleDoubleClick}
      style={{ cursor: dragState.current ? "grabbing" : "grab", userSelect: "none" }}
    >
      <g transform={`translate(${tx},${ty}) scale(${scale})`}>
        {layout.edges.map((edge, i) => (
          <path key={`e${i}`} className={`edge${edge.blocked ? " blocked" : ""}${edge.backEdge ? " back-edge" : ""}`} d={edge.path} />
        ))}
        {layout.nodes.map((node) => {
          const isSelected = node.taskId === selectedTaskId;
          const isFocus = node.taskId === layout.focusTaskId;
          return (
            <g
              key={node.taskId}
              className={`nd${isSelected ? " sel" : ""}`}
              data-t={node.tone}
              data-n={node.taskId}
              transform={`translate(${node.x},${node.y})`}
              onClick={(e) => { e.stopPropagation(); onSelectTask(node.taskId); }}
            >
              <rect width={node.width} height={node.height} />
              <text x={11} y={17}>{node.title}</text>
              {isFocus ? <rect className="attn-ring" x={-5} y={-5} width={node.width + 10} height={node.height + 10} rx={10} /> : null}
            </g>
          );
        })}
      </g>
    </svg>
  );
}

export default DagCanvas;
