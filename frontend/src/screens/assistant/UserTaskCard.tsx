import { Loader2, Play, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  continueUserTask,
  getUserTaskDistribution,
  type TaskDistribution,
  type UserTaskContinueResponse,
} from "../../api/userTasks";

/** 分布条各段的配置：key → 颜色类 + 标签。顺序决定渲染顺序。 */
const DISTRIBUTION_SEGMENTS: { key: string; cls: string; label: string }[] = [
  { key: "done", cls: "s-done", label: "已完成" },
  { key: "skipped", cls: "s-done", label: "已跳过" },
  { key: "delivered", cls: "s-rev", label: "待验收" },
  { key: "running", cls: "s-run", label: "进行中" },
  { key: "pending_dispatch", cls: "s-todo", label: "待开始" },
  { key: "suspended:user", cls: "s-you", label: "等你回答" },
  { key: "suspended:assistant", cls: "s-bug", label: "需处理" },
  { key: "suspended:system", cls: "s-bug", label: "等待中" },
];

/** 判断有没有可以"继续"的暂停（suspended:user 之外的暂停）。 */
function hasPushable(distribution: TaskDistribution | null): boolean {
  if (!distribution) return false;
  return Object.entries(distribution).some(
    ([key, count]) =>
      key.startsWith("suspended:") &&
      key !== "suspended:user" &&
      key !== "suspended:assistant" &&
      (count ?? 0) > 0,
  );
}

/** 判断有没有需要用户关注的暂停。 */
function needsAttention(distribution: TaskDistribution | null): boolean {
  if (!distribution) return false;
  return Object.entries(distribution).some(([key, count]) => {
    if ((count ?? 0) === 0) return false;
    return (
      key === "suspended:user" ||
      key === "suspended:assistant" ||
      key === "delivered"
    );
  });
}

/**
 * 用户任务卡片（⑦ 界面层）：折叠在对话流里，展示一件事的状态。
 *
 * 折叠行：▶ [迷你分布条] 任务标题  N/M
 * 展开后：分布条 + 状态计数 + 继续按钮（有推得动的暂停时显示）
 * 点继续后就地显示回报（几摊动了/没动/原因）
 */
function UserTaskCard({
  sessionId,
  taskId,
  title,
}: {
  sessionId: string;
  taskId: string;
  title: string;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [distribution, setDistribution] = useState<TaskDistribution | null>(null);
  const [loadingDist, setLoadingDist] = useState(false);
  const [continueResult, setContinueResult] = useState<UserTaskContinueResponse | null>(null);
  const [continuing, setContinuing] = useState(false);

  const loadDistribution = useCallback(() => {
    setLoadingDist(true);
    getUserTaskDistribution(sessionId, taskId)
      .then((res) => setDistribution(res.distribution))
      .catch(() => setDistribution(null))
      .finally(() => setLoadingDist(false));
  }, [sessionId, taskId]);

  // 初次加载 + 定时刷新（任务在跑时 10 秒刷新一次）
  useEffect(() => {
    loadDistribution();
    const timer = setInterval(loadDistribution, 10000);
    return () => clearInterval(timer);
  }, [loadDistribution]);

  const total = distribution
    ? Object.values(distribution).reduce((a, b) => a + b, 0)
    : 0;
  const done =
    (distribution?.["done"] ?? 0) + (distribution?.["skipped"] ?? 0);

  const showContinue = hasPushable(distribution);
  const defectCount = distribution?.["suspended:assistant"] ?? 0;
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

  return (
    <details
      className="assistant-activity me-task-fold"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>
        {loadingDist ? (
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

          {/* 撞缺陷提示（设计 295 行：不给「继续」，给说明） */}
          {hasDefect ? (
            <p className="me-defect-notice">
              有 {defectCount} 步遇到程序问题，做不下去了。已记录详情，正在处理。
            </p>
          ) : null}

          {/* 继续回报 */}
          {continueResult ? (
            <div className="me-report">
              {continueResult.success ? (
                <p className="me-report-head">
                  已继续 · {continueResult.pushed.length + continueResult.notPushed.length} 摊里动了{" "}
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
