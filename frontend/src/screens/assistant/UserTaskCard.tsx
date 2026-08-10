import { Loader2, Play, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  continueUserTask,
  getUserTaskDistribution,
  getUserTaskGraphs,
  type TaskDistribution,
  type UserTaskContinueResponse,
  type UserTaskGraphSummary,
} from "../../api/userTasks";
import { getAssistantTaskGraph } from "../../api/assistantTasks";
import type { AssistantTaskSnapshot } from "../../api/assistantTasks";
import TaskGraphPeek from "./TaskGraphPeek";
import ExecutorCard from "./ExecutorCard";

/** 分布条各段的配置：key → 颜色类 + 标签。顺序决定渲染顺序。
 *
 * 分布 key 用 ``suspend_reason``（后端 ``status_distribution_for_user_task``
 * 按 ``suspended:{suspend_reason}`` 聚合）。每个暂停原因一个 key，前端可以
 * 精确区分「等用户回答」（``waiting_user``，不可继续）和「用户手动停」
 * （``user_stop``，可继续）。
 */
const DISTRIBUTION_SEGMENTS: { key: string; cls: string; label: string }[] = [
  { key: "done", cls: "s-done", label: "已完成" },
  { key: "skipped", cls: "s-done", label: "已跳过" },
  { key: "delivered", cls: "s-rev", label: "待验收" },
  { key: "running", cls: "s-run", label: "进行中" },
  { key: "pending_dispatch", cls: "s-todo", label: "待开始" },
  { key: "suspended:waiting_user", cls: "s-you", label: "等你回答" },
  { key: "suspended:quota_exhausted", cls: "s-you", label: "额度耗尽" },
  { key: "suspended:user_stop", cls: "s-you", label: "已暂停" },
  { key: "suspended:interrupted", cls: "s-you", label: "已中断" },
  { key: "suspended:blocked_by_defect", cls: "s-bug", label: "需处理" },
  { key: "suspended:budget_exhausted", cls: "s-bug", label: "轮次耗尽" },
  { key: "suspended:waiting_system", cls: "s-bug", label: "等待中" },
];

const STATUS_LABELS: Record<string, string> = {
  active: "在办",
  cooling: "冷却",
  done: "办完",
  dropped: "不办了",
};

/** 不可继续的暂停原因：等用户回答（要先回答问题）和撞缺陷（重试无用）。 */
const UNPUSHABLE_SUSPEND_REASONS = new Set([
  "suspended:waiting_user",
  "suspended:blocked_by_defect",
]);

/**
 * 判断有没有可以"继续"的暂停。
 *
 * 用 ``suspend_reason`` 维度判断（与后端 ``_CONTINUE_CANNOT_MOVE`` 同维度）：
 * ``waiting_user`` 要先回答问题、``blocked_by_defect`` 重试必是同样的结果，
 * 这两种不给继续按钮。其余暂停原因（``user_stop``、``interrupted``、
 * ``quota_exhausted`` 等）点继续都能推动。
 */
function hasPushable(distribution: TaskDistribution | null): boolean {
  if (!distribution) return false;
  return Object.entries(distribution).some(
    ([key, count]) =>
      key.startsWith("suspended:") &&
      !UNPUSHABLE_SUSPEND_REASONS.has(key) &&
      (count ?? 0) > 0,
  );
}

/** 需要用户关注的暂停原因：等用户回答、撞缺陷、额度耗尽、待验收。 */
function needsAttention(distribution: TaskDistribution | null): boolean {
  if (!distribution) return false;
  return Object.entries(distribution).some(([key, count]) => {
    if ((count ?? 0) === 0) return false;
    return (
      key === "suspended:waiting_user" ||
      key === "suspended:blocked_by_defect" ||
      key === "suspended:quota_exhausted" ||
      key === "delivered"
    );
  });
}

/**
 * 用户任务卡片（⑦ 界面层）：折叠在对话流里，展示一件事的状态。
 *
 * 折叠行：▶ [迷你分布条] 任务标题  N/M
 * 展开后：分布条 + 状态计数 + 局部图 + 继续按钮（有推得动的暂停时显示）
 * 点继续后就地显示回报（几摊动了/没动/原因）
 */
function UserTaskCard({
  sessionId,
  taskId,
  title,
  status = "active",
  onOpenFullGraph,
  onOpenExecutor,
}: {
  sessionId: string;
  taskId: string;
  title: string;
  status?: string;
  onOpenFullGraph: (graphId: string, title: string) => void;
  onOpenExecutor: (executorSessionId: string, label: string) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [distribution, setDistribution] = useState<TaskDistribution | null>(null);
  const [loadingDist, setLoadingDist] = useState(false);
  const [graphs, setGraphs] = useState<UserTaskGraphSummary[]>([]);
  const [executorTasks, setExecutorTasks] = useState<AssistantTaskSnapshot[]>([]);
  const [continueResult, setContinueResult] = useState<UserTaskContinueResponse | null>(null);
  const [continuing, setContinuing] = useState(false);

  const loadDistribution = useCallback(() => {
    setLoadingDist(true);
    getUserTaskDistribution(sessionId, taskId)
      .then((res) => setDistribution(res.distribution))
      .catch(() => setDistribution(null))
      .finally(() => setLoadingDist(false));
  }, [sessionId, taskId]);

  // 首次加载 distribution（summary 需要它显示继续按钮/缺陷标签）；
  // graphs 展开时才加载（懒加载，只在用户要看局部图时请求）
  useEffect(() => {
    loadDistribution();
  }, [loadDistribution]);

  useEffect(() => {
    if (!open) return;
    getUserTaskGraphs(sessionId, taskId)
      .then((res) => {
        const gs = res.graphs ?? [];
        setGraphs(gs);
        // 加载所有图的快照，提取有 executorSessionId 的节点（供执行体列表展示）
        return Promise.all(
          gs.map((g) => getAssistantTaskGraph(sessionId, g.graphId).catch(() => null)),
        );
      })
      .then((snapshots) => {
        const tasks: AssistantTaskSnapshot[] = [];
        for (const snap of snapshots) {
          if (!snap) continue;
          for (const t of snap.tasks) {
            if (t.executorSessionId && t.status !== "done" && t.status !== "skipped") {
              tasks.push(t);
            }
          }
        }
        setExecutorTasks(tasks);
      })
      .catch(() => {
        setGraphs([]);
        setExecutorTasks([]);
      });
  }, [open, sessionId, taskId, loadDistribution]);

  const total = distribution
    ? Object.values(distribution).reduce((a, b) => a + b, 0)
    : 0;
  const done =
    (distribution?.["done"] ?? 0) + (distribution?.["skipped"] ?? 0);

  const showContinue = hasPushable(distribution);
  const defectCount = distribution?.["suspended:blocked_by_defect"] ?? 0;
  const hasDefect = defectCount > 0;
  const shouldAutoOpen = needsAttention(distribution) || continueResult != null;

  useEffect(() => {
    if (shouldAutoOpen) setOpen(true);
  }, [shouldAutoOpen]);

  const handleContinue = () => {
    setContinuing(true);
    setContinueResult(null);
    continueUserTask(sessionId, taskId)
      .then((res) => {
        setContinueResult(res);
        loadDistribution();
      })
      .catch(() => {
        setContinueResult({
          pushed: [],
          notPushed: [],
          stillFinishing: [],
          total: 0,
          success: false,
        });
      })
      .finally(() => setContinuing(false));
  };

  // 迷你分布条段
  const miniSegments = DISTRIBUTION_SEGMENTS.filter(
    (seg) => (distribution?.[seg.key] ?? 0) > 0,
  );

  // 多节点图（nodeCount > 1）才显示局部图入口
  const graphsWithNodes = graphs.filter((g) => g.nodeCount > 1);

  return (
    <details
      className="assistant-activity me-task-fold"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>
        {loadingDist && open ? (
          <Loader2 size={13} className="assistant-spin" />
        ) : (
          <ChevronRight size={13} className={`me-chev${open ? " me-chev-open" : ""}`} />
        )}
        {miniSegments.length > 0 ? (
          <span className="me-mini">
            {miniSegments.map((seg) => (
              <i
                key={seg.key}
                className={seg.cls}
                style={{ flex: distribution?.[seg.key] ?? 0 }}
              />
            ))}
          </span>
        ) : null}
        <span className="me-task-fold-title">{title}</span>
        {total > 0 ? (
          <span className="assistant-activity-count">
            {done}/{total}
          </span>
        ) : null}
        {hasDefect ? (
          <span className="me-attention-tag">需处理</span>
        ) : null}
        {showContinue ? (
          <button
            type="button"
            className="assistant-activity-graph-btn assistant-activity-graph-continue"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              handleContinue();
            }}
            disabled={continuing}
            title="继续这件事"
          >
            {continuing ? <Loader2 size={12} className="assistant-spin" /> : <Play size={12} />}
            继续
          </button>
        ) : null}
      </summary>
      <div className="assistant-activity-body">
        <div className="me-task">
          {/* 标题行 + 状态标签 */}
          <div className="me-task-head">
            <span className="me-task-title">{title}</span>
            <span className="me-pill" data-status={status}>
              {STATUS_LABELS[status] ?? status}
            </span>
          </div>

          {/* 分布条 */}
          {miniSegments.length > 0 ? (
            <>
              <div className="me-bar">
                {miniSegments.map((seg) => (
                  <i
                    key={seg.key}
                    className={seg.cls}
                    style={{ flex: distribution?.[seg.key] ?? 0 }}
                  />
                ))}
              </div>
              <div className="me-legend">
                {miniSegments.map((seg) => (
                  <span key={seg.key}>
                    <i className={seg.cls} />
                    <b>
                      {seg.label} {distribution?.[seg.key] ?? 0}
                    </b>
                  </span>
                ))}
              </div>
            </>
          ) : (
            <p className="me-empty">暂无执行进度</p>
          )}

          {/* 局部图（每张多节点图一个） */}
          {graphsWithNodes.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 10 }}>
              {graphsWithNodes.map((g) => (
                <TaskGraphPeek
                  key={g.graphId}
                  sessionId={sessionId}
                  graphId={g.graphId}
                  title={g.title}
                  onOpenFullGraph={() => onOpenFullGraph(g.graphId, title)}
                />
              ))}
            </div>
          ) : null}

          {/* 执行体列表（点开看它的工具调用和子执行体，⑦ 核心交互） */}
          {executorTasks.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 10 }}>
              {executorTasks.map((task) => (
                <ExecutorCard
                  key={task.taskId}
                  summary={{
                    subagentId: task.executorSessionId ?? "",
                    label: task.assignee?.label ?? task.assignee?.id ?? "执行体",
                    task: task.title,
                    status: task.status === "suspended" ? "suspended" : "running",
                    lastOutput: null,
                    turnStartSequence: null,
                  }}
                  onClick={() =>
                    onOpenExecutor(
                      task.executorSessionId ?? "",
                      task.assignee?.label ?? task.assignee?.id ?? "执行体",
                    )
                  }
                />
              ))}
            </div>
          ) : null}

          {/* 撞缺陷提示（设计 295 行：不给「继续」，给说明） */}
          {hasDefect ? (
            <p className="me-defect-notice">
              有 {defectCount} 步遇到程序问题，做不下去了。已记录详情，正在处理。
            </p>
          ) : null}

          {/* 额度耗尽提示（设计 307-308 行：只提示这一种原因） */}
          {(distribution?.["suspended:quota_exhausted"] ?? 0) > 0 ? (
            <p className="me-defect-notice">模型额度耗尽。</p>
          ) : null}

          {/* 继续回报 */}
          {continueResult ? (
            <div className="me-report">
              {continueResult.success ? (
                <p className="me-report-head">
                  已继续 · {continueResult.pushed.length + continueResult.notPushed.length + continueResult.stillFinishing.length} 摊里动了{" "}
                  {continueResult.pushed.length} 摊
                </p>
              ) : (
                <p className="me-report-head me-report-fail">
                  没有推动任何任务
                </p>
              )}
              {continueResult.pushed.length > 0 ? (
                <ul className="me-report-list">
                  {continueResult.pushed.map((item, i) => (
                    <li key={`p${i}`} className="me-report-pushed">
                      动了 &nbsp;{item.title} —— 已重新开工
                    </li>
                  ))}
                </ul>
              ) : null}
              {continueResult.stillFinishing.length > 0 ? (
                <ul className="me-report-list">
                  {continueResult.stillFinishing.map((item, i) => (
                    <li key={`s${i}`} className="me-report-blocked">
                      收尾中 &nbsp;{item.title} —— {item.reason ?? "正在收尾，尚未重新开工"}
                    </li>
                  ))}
                </ul>
              ) : null}
              {continueResult.notPushed.length > 0 ? (
                <ul className="me-report-list">
                  {continueResult.notPushed.map((item, i) => (
                    <li key={`n${i}`} className="me-report-blocked">
                      没动 &nbsp;{item.title} —— {item.reason}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </details>
  );
}

export default UserTaskCard;
