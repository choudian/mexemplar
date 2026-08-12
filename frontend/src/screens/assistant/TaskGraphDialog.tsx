import { Loader2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getAssistantTaskGraph, getAssistantTaskTodos } from "../../api/assistantTasks";
import type { AssistantTaskGraphSnapshot, AssistantTaskSnapshot, AssistantTodoItem } from "../../api/assistantTasks";
import { getExecutorDetail } from "../../api/assistant";
import type { ExecutorDetail } from "../../api/assistant";
import DagCanvas from "./DagCanvas";
import ExecutorCard from "./ExecutorCard";
import { EXECUTOR_REFRESH_MS } from "./executorStatus";
import { layoutDag } from "../../components/taskGraph/layoutDag";
import { ActivityStepRow, LoadableContent } from "./ActivityStepRow";

type SideView =
  | { kind: "node"; taskId: string }
  | { kind: "executor"; executorSessionId: string; label: string };

const STATUS_TEXT: Record<string, string> = {
  done: "完成",
  run: "正在干",
  you: "等你回答",
  bug: "撞上程序问题",
  todo: "等前置",
};

/** 全图弹窗（⑦）：左图右详情，手写分层布局，平移缩放。 */
function TaskGraphDialog({
  sessionId,
  graphId,
  taskTitle,
  onClose,
}: {
  sessionId: string;
  graphId: string;
  taskTitle: string;
  onClose: () => void;
}): JSX.Element {
  const [graph, setGraph] = useState<AssistantTaskGraphSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [sideStack, setSideStack] = useState<SideView[]>([]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    getAssistantTaskGraph(sessionId, graphId)
      .then((g) => {
        if (!active) return;
        setGraph(g);
        const layout = layoutDag(g.tasks, g.edges);
        if (layout.focusTaskId) {
          setSelectedTaskId(layout.focusTaskId);
          setSideStack([{ kind: "node", taskId: layout.focusTaskId }]);
        }
      })
      .catch(() => {
        if (active) setError("任务图加载失败，请重试。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [sessionId, graphId]);

  const layout = useMemo(
    () => (graph ? layoutDag(graph.tasks, graph.edges) : null),
    [graph],
  );

  const currentSide = sideStack[sideStack.length - 1];

  const selectedTask = useMemo(() => {
    if (!graph || !selectedTaskId) return null;
    return graph.tasks.find((t) => t.taskId === selectedTaskId) ?? null;
  }, [graph, selectedTaskId]);

  const [executorDetail, setExecutorDetail] = useState<ExecutorDetail | null>(null);
  const [executorLoading, setExecutorLoading] = useState(false);

  useEffect(() => {
    if (!currentSide || currentSide.kind !== "executor") {
      setExecutorDetail(null);
      return;
    }
    let active = true;
    setExecutorLoading(true);
    setExecutorDetail(null);
    getExecutorDetail(sessionId, currentSide.executorSessionId)
      .then((d) => {
        if (active) setExecutorDetail(d);
      })
      .catch(() => {
        if (active) setExecutorDetail(null);
      })
      .finally(() => {
        if (active) setExecutorLoading(false);
      });
    return () => {
      active = false;
    };
  }, [sessionId, currentSide]);

  // 侧栏停在某个执行体上时自动跟进它的最新过程，与抽屉同一套规则：
  // 只在还在跑时轮询、静默替换不闪、切走或关窗随 cleanup 停。
  useEffect(() => {
    if (!currentSide || currentSide.kind !== "executor") return;
    if (executorDetail?.summary.status !== "running") return;
    const executorSessionId = currentSide.executorSessionId;
    let active = true;
    const timer = setInterval(() => {
      getExecutorDetail(sessionId, executorSessionId)
        .then((d) => {
          if (active) setExecutorDetail(d);
        })
        .catch(() => {
          /* 刷新失败保留上一次内容，不打断阅读 */
        });
    }, EXECUTOR_REFRESH_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [sessionId, currentSide, executorDetail?.summary.status]);

  const handleSelectNode = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
    setSideStack([{ kind: "node", taskId }]);
  }, []);

  const handleOpenExecutor = useCallback((executorSessionId: string, label: string) => {
    setSideStack((prev) => [...prev, { kind: "executor", executorSessionId, label }]);
  }, []);

  const handleSideBack = useCallback((index: number) => {
    setSideStack((prev) => {
      const next = prev.slice(0, index + 1);
      const target = next[next.length - 1];
      if (target?.kind === "node") setSelectedTaskId(target.taskId);
      return next;
    });
  }, []);

  const stats = graph
    ? graph.tasks.length + " 个节点 · " + graph.tasks.filter((t) => t.status === "done" || t.status === "skipped").length + " 完成 · " + graph.tasks.filter((t) => t.status === "suspended").length + " 卡住"
    : "";

  return (
    <div className="me-modal" onClick={onClose}>
      <div className="me-dlg" onClick={(e) => e.stopPropagation()}>
        <div className="me-dlg-bar">
          <strong>{taskTitle} · 任务图</strong>
          <span className="dlg-stats">{stats}</span>
          <button type="button" className="me-icon-button" aria-label="关闭" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div className="me-dlg-split">
          <div className="me-dlg-canvas">
            {loading ? (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
                <Loader2 size={20} className="assistant-spin" />
              </div>
            ) : error ? (
              <LoadableContent loading={false} error={error} emptyLabel="" onRetry={() => window.location.reload()} />
            ) : layout && layout.nodes.length > 0 ? (
              <DagCanvas layout={layout} selectedTaskId={selectedTaskId} onSelectTask={handleSelectNode} />
            ) : (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)", fontSize: 13 }}>
                这张图还没有可展示的节点
              </div>
            )}
          </div>
          <div className="me-dlg-side">
            {sideStack.length > 1 ? (
              <div className="crumb">
                {sideStack.map((view, i) => (
                  <span key={i}>
                    {i > 0 ? <span> / </span> : null}
                    {i < sideStack.length - 1 ? (
                      <button type="button" onClick={() => handleSideBack(i)}>
                        {view.kind === "node"
                          ? graph?.tasks.find((t) => t.taskId === view.taskId)?.title ?? "节点"
                          : view.label}
                      </button>
                    ) : (
                      <span>{view.kind === "node" ? selectedTask?.title ?? "节点" : view.label}</span>
                    )}
                  </span>
                ))}
              </div>
            ) : null}

            {!currentSide ? (
              <p className="sub">点左侧节点查看详情</p>
            ) : currentSide.kind === "node" ? (
              selectedTask ? (
                <NodeDetail task={selectedTask} sessionId={sessionId} onOpenExecutor={handleOpenExecutor} />
              ) : (
                <p className="sub">未选中节点</p>
              )
            ) : executorLoading ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-muted)", fontSize: "12.5px" }}>
                <Loader2 size={14} className="assistant-spin" /> 加载执行体详情…
              </div>
            ) : executorDetail ? (
              <ExecutorSideDetail detail={executorDetail} sessionId={sessionId} onNavigate={handleOpenExecutor} />
            ) : (
              <p className="sub">执行体详情加载失败</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function NodeDetail({
  task,
  sessionId,
  onOpenExecutor,
}: {
  task: AssistantTaskSnapshot;
  sessionId: string;
  onOpenExecutor: (executorSessionId: string, label: string) => void;
}): JSX.Element {
  const [todos, setTodos] = useState<AssistantTodoItem[]>([]);
  useEffect(() => {
    let active = true;
    getAssistantTaskTodos(sessionId, task.taskId)
      .then((r) => { if (active) setTodos(r.items); })
      .catch(() => { if (active) setTodos([]); });
    return () => { active = false; };
  }, [sessionId, task.taskId]);

  const tone = deriveToneForTask(task);
  const statusText = STATUS_TEXT[tone] ?? task.status;
  const hasDefect = task.suspendReason === "blocked_by_defect";
  return (
    <div>
      <h5>
        {task.title}
        <span className="st-tag" data-t={tone}>{statusText}</span>
      </h5>
      <p className="sub">
        {task.assignee ? (task.assignee.label ?? task.assignee.id) : "还没派人"}
        {task.descriptionPreview ? " · " + task.descriptionPreview : ""}
      </p>
      {hasDefect ? (
        <p className="sub" style={{ color: "var(--danger)" }}>
          重试一定还是同样的结果。助理正在判断跳过它还是放弃它。
        </p>
      ) : null}
      {task.safeExplanation ? (
        <p className="sub" style={{ marginBottom: 10 }}>{task.safeExplanation}</p>
      ) : null}
      {task.executorSessionId ? (
        <>
          <div className="sect">干这个节点的</div>
          <ExecutorCard
            summary={{
              subagentId: task.executorSessionId,
              label: task.assignee?.label ?? task.assignee?.id ?? "执行体",
              task: task.title,
              status: deriveExecutorStatus(task),
              lastOutput: null,
              turnStartSequence: null,
              taskId: task.taskId,
            }}
            todos={todos}
            onClick={() =>
              onOpenExecutor(
                task.executorSessionId ?? "",
                task.assignee?.label ?? task.assignee?.id ?? "执行体",
              )
            }
          />
          <p className="assistant-drawer-hint" style={{ margin: "8px 0 0" }}>
            点它看调了什么工具 —— 就在这一栏里往下钻。
          </p>
        </>
      ) : (
        <p className="sub">这一步还没有执行记录。</p>
      )}
    </div>
  );
}

function ExecutorSideDetail({
  detail,
  sessionId,
  onNavigate,
}: {
  detail: ExecutorDetail;
  sessionId: string;
  onNavigate: (executorSessionId: string, label: string) => void;
}): JSX.Element {
  const [todosByTaskId, setTodosByTaskId] = useState<Record<string, AssistantTodoItem[]>>({});
  useEffect(() => {
    if (detail.children.length === 0) return;
    let active = true;
    const taskIds = detail.children.map((c) => c.taskId).filter((tid): tid is string => Boolean(tid));
    if (taskIds.length === 0) return;
    Promise.all(
      taskIds.map((tid) =>
        getAssistantTaskTodos(sessionId, tid)
          .then((r) => ({ tid, items: r.items }))
          .catch(() => ({ tid, items: [] as AssistantTodoItem[] })),
      ),
    ).then((results) => {
      if (!active) return;
      const map: Record<string, AssistantTodoItem[]> = {};
      for (const { tid, items } of results) {
        map[tid] = items;
      }
      setTodosByTaskId(map);
    });
    return () => { active = false; };
  }, [detail, sessionId]);

  return (
    <div>
      <h5>{detail.summary.label}</h5>
      <p className="sub">{detail.summary.task}</p>
      {detail.steps.length > 0 ? (
        <ol className="assistant-steplist">
          {detail.steps.map((step) => (
            <li key={step.seq} className="assistant-step" data-kind={step.kind}>
              <ActivityStepRow kind={step.kind} seq={step.seq} toolName={step.toolName} text={step.text} />
            </li>
          ))}
        </ol>
      ) : (
        <p className="sub">还没有步骤。</p>
      )}
      {detail.children.length > 0 ? (
        <>
          <div className="sect">它派出去的</div>
          {detail.children.map((child) => (
            <div key={child.subagentId} style={{ marginBottom: 7 }}>
              <ExecutorCard
                summary={child}
                todos={child.taskId ? todosByTaskId[child.taskId] : undefined}
                onClick={() => onNavigate(child.subagentId, child.label)}
              />
            </div>
          ))}
        </>
      ) : null}
      {detail.summary.lastOutput ? (
        <div className="assistant-drawer-output">
          <span>产出</span>
          <p>{detail.summary.lastOutput}</p>
        </div>
      ) : null}
    </div>
  );
}

function deriveToneForTask(task: AssistantTaskSnapshot): string {
  if (task.status === "done" || task.status === "skipped") return "done";
  if (task.status === "suspended") {
    if (task.waitingOn === "user") return "you";
    return "bug";
  }
  if (task.status === "running" || task.status === "delivered") return "run";
  return "todo";
}

function deriveExecutorStatus(task: AssistantTaskSnapshot): "running" | "done" | "suspended" | "failed" {
  if (task.status === "done" || task.status === "skipped") return "done";
  if (task.status === "suspended") return "suspended";
  if (task.status === "abandoned" || task.status === "cancelled") return "failed";
  return "running";
}

export default TaskGraphDialog;
