import { Bot, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getExecutorDetail } from "../../api/assistant";
import type { ExecutorDetail } from "../../api/assistant";
import { getAssistantTaskTodos } from "../../api/assistantTasks";
import type { AssistantTodoItem } from "../../api/assistantTasks";
import { ActivityStepRow, LoadableContent } from "./ActivityStepRow";
import ExecutorCard from "./ExecutorCard";
import { EXECUTOR_REFRESH_MS } from "./executorStatus";

interface DrawerLayer {
  executorSessionId: string;
  label: string;
}

/**
 * 递归执行体抽屉（⑦）：点开一个执行体，看它的过程 + 它派出去的子执行体。
 * 面包屑可逐级返回。事件隔离：抽屉内点击不冒泡。
 */
function ExecutorDrawer({
  sessionId,
  initialExecutorSessionId,
  initialLabel,
  onClose,
}: {
  sessionId: string;
  initialExecutorSessionId: string;
  initialLabel: string;
  onClose: () => void;
}): JSX.Element {
  const [stack, setStack] = useState<DrawerLayer[]>([
    { executorSessionId: initialExecutorSessionId, label: initialLabel },
  ]);
  const [detail, setDetail] = useState<ExecutorDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [todosByTaskId, setTodosByTaskId] = useState<Record<string, AssistantTodoItem[]>>({});

  const currentLayer = stack[stack.length - 1];
  const currentSessionId = currentLayer.executorSessionId;

  // 首次打开/切层：清空并显示加载态
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setDetail(null);
    getExecutorDetail(sessionId, currentSessionId)
      .then((d) => { if (active) setDetail(d); })
      .catch(() => { if (active) setError("过程加载失败，请重试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [sessionId, currentSessionId, reloadKey]);

  // 打开期间自动跟进最新过程。只在执行体还在跑时轮询——终态了内容不再变，
  // 继续轮询纯属浪费。抽屉一关组件卸载，定时器随 cleanup 停掉。
  // 静默替换，不清空 detail：否则每次刷新都会闪一下加载态。
  useEffect(() => {
    if (detail?.summary.status !== "running") return;
    let active = true;
    const timer = setInterval(() => {
      getExecutorDetail(sessionId, currentSessionId)
        .then((d) => { if (active) setDetail(d); })
        .catch(() => { /* 刷新失败保留上一次内容，不打断阅读 */ });
    }, EXECUTOR_REFRESH_MS);
    return () => { active = false; clearInterval(timer); };
  }, [sessionId, currentSessionId, detail?.summary.status]);

  // 加载子执行体的 todo（⑦ 递归规则：任意深度的执行体卡片正面展示 todolist）
  useEffect(() => {
    if (!detail || detail.children.length === 0) return;
    let active = true;
    const taskIds = detail.children
      .map((c) => c.taskId)
      .filter((tid): tid is string => Boolean(tid));
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
      setTodosByTaskId((prev) => ({ ...prev, ...map }));
    });
    return () => { active = false; };
  }, [detail, sessionId]);

  const handleNavigate = useCallback((childSessionId: string, childLabel: string) => {
    setStack((prev) => [...prev, { executorSessionId: childSessionId, label: childLabel }]);
  }, []);

  const handleBack = useCallback((index: number) => {
    setStack((prev) => prev.slice(0, index + 1));
  }, []);

  const handleRetry = () => setReloadKey((key) => key + 1);

  return (
    <div className="assistant-drawer-scrim" onClick={onClose}>
      <aside className="assistant-drawer" role="dialog" aria-label={`执行体详情：${currentLayer.label}`} onClick={(e) => e.stopPropagation()}>
        <header className="assistant-drawer-head">
          <div className="assistant-drawer-title">
            <Bot size={16} />
            <div>
              <strong>{detail?.summary.label ?? currentLayer.label}</strong>
              <small>{detail?.summary.task || ""}</small>
            </div>
          </div>
          <button type="button" className="me-icon-button" aria-label="关闭" onClick={onClose}><X size={16} /></button>
        </header>
        <div className="assistant-drawer-body me-scroll">
          {stack.length > 1 ? (
            <div className="crumb">
              {stack.map((layer, i) => (
                <span key={layer.executorSessionId}>
                  {i > 0 ? <span> / </span> : null}
                  {i < stack.length - 1 ? (
                    <button type="button" onClick={() => handleBack(i)}>{layer.label}</button>
                  ) : (
                    <span>{layer.label}</span>
                  )}
                </span>
              ))}
            </div>
          ) : null}

          <p className="assistant-drawer-hint">这是它自己的完整过程，包含调用的工具和原文。</p>

          {loading || error ? (
            <LoadableContent loading={loading} error={error} emptyLabel="" onRetry={handleRetry} />
          ) : !detail ? null : detail.steps.length === 0 ? (
            <div className="assistant-drawer-empty">还没有步骤。</div>
          ) : (
            <ol className="assistant-steplist">
              {detail.steps.map((step) => (
                <li key={step.seq} className="assistant-step" data-kind={step.kind}>
                  <ActivityStepRow kind={step.kind} seq={step.seq} toolName={step.toolName} text={step.text} />
                </li>
              ))}
            </ol>
          )}

          {detail && detail.children.length > 0 ? (
            <>
              <div className="sect">它派出去的</div>
              {detail.children.map((child) => (
                <div key={child.subagentId} style={{ marginBottom: 7 }}>
                  <ExecutorCard
                    summary={child}
                    todos={child.taskId ? todosByTaskId[child.taskId] : undefined}
                    onClick={() => handleNavigate(child.subagentId, child.label)}
                  />
                </div>
              ))}
            </>
          ) : null}

          {detail?.summary.lastOutput ? (
            <div className="assistant-drawer-output"><span>产出</span><p>{detail.summary.lastOutput}</p></div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

export default ExecutorDrawer;
