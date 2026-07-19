import { useEffect, useState } from "react";
import {
  CalendarClock,
  ChevronDown,
  ChevronRight,
  Clock4,
  History,
  MessageSquare,
  Pause,
  Play,
  RefreshCcw,
  ShieldAlert,
  Sparkles,
  Trash2,
} from "lucide-react";

import { Badge, IconButton } from "../../components/primitives";
import { useAssistantStore } from "../../state/assistantStore";
import { useScheduledStore } from "../../state/scheduledStore";
import { useShellStore } from "../../state/shellStore";
import { useToastStore } from "../../state/toastStore";
import type {
  ScheduledTaskItem,
  ScheduledTaskRunItem,
  ScheduledRunStatus,
  ScheduledTaskStatus,
} from "../../api/scheduledTasks";

const STATUS_LABEL: Record<ScheduledTaskStatus, string> = {
  active: "运行中",
  paused: "已暂停",
  completed: "已完成",
  expired: "已过期",
};

const RUN_STATUS_LABEL: Record<ScheduledRunStatus, string> = {
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  waiting_user: "需要你的帮助",
  skipped: "本次跳过",
};

// 行内操作在组件本地按 `${taskId}:${action}` 维护 loading/disabled 状态。
type InlineAction = "pause" | "resume" | "fire" | "delete" | "set-unattended";

function runStatusTone(
  status: ScheduledRunStatus,
): "neutral" | "ok" | "warn" | "danger" {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "danger";
  if (status === "waiting_user") return "warn";
  return "neutral";
}

function statusTone(
  status: ScheduledTaskStatus,
): "neutral" | "ok" | "warn" | "danger" {
  if (status === "active") return "ok";
  if (status === "paused") return "warn";
  if (status === "expired") return "danger";
  return "neutral";
}

function formatDate(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function lastRunLabel(task: ScheduledTaskItem): string {
  if (!task.lastRunAt) return "还没跑过";
  const when = formatDate(task.lastRunAt);
  if (!task.lastRunOutcome) return `上次执行 ${when}`;
  return `上次执行 ${when} · ${RUN_STATUS_LABEL[task.lastRunOutcome] ?? "执行中"}`;
}

function nextFireLabel(task: ScheduledTaskItem): string {
  if (task.status === "paused") return "已暂停";
  if (task.status === "completed") return "已完成";
  if (task.status === "expired") return "已过期";
  if (!task.nextFireAt) return "未排期";
  const when = formatDate(task.nextFireAt);
  return when ? `下次 ${when}` : "未排期";
}

const EXAMPLE_PROMPTS = [
  "现在就帮我看一下今天的会议安排",
  "明天下午 3 点整理本周会议纪要",
  "每天 9 点查一下竞品价格",
];

export function ScheduledScreen(): JSX.Element {
  const hydrated = useScheduledStore((s) => s.hydrated);
  const tasks = useScheduledStore((s) => s.tasks);
  const tasksTotal = useScheduledStore((s) => s.tasksTotal);
  const loading = useScheduledStore((s) => s.loading);
  const lastError = useScheduledStore((s) => s.lastError);
  const runsByTask = useScheduledStore((s) => s.runsByTask);
  const expandedTaskIds = useScheduledStore((s) => s.expandedTaskIds);
  const loadingRunsTaskIds = useScheduledStore((s) => s.loadingRunsTaskIds);
  const load = useScheduledStore((s) => s.load);
  const loadRuns = useScheduledStore((s) => s.loadRuns);
  const toggleExpanded = useScheduledStore((s) => s.toggleExpanded);
  const takeover = useScheduledStore((s) => s.takeover);
  const patchTask = useScheduledStore((s) => s.patchTask);
  const fireNow = useScheduledStore((s) => s.fireNow);
  const remove = useScheduledStore((s) => s.remove);

  const setRoute = useShellStore((s) => s.setRoute);
  const selectSession = useAssistantStore((s) => s.selectSession);
  const setAssistantDraft = useAssistantStore((s) => s.setDraft);
  const notifySuccess = useToastStore((s) => s.notifySuccess);
  const notifyInfo = useToastStore((s) => s.notifyInfo);
  const notifyWarning = useToastStore((s) => s.notifyWarning);

  const [openingRunId, setOpeningRunId] = useState<string | null>(null);
  // 行内操作态：`${taskId}:${action}` → true；同一行同一动作串行，不同行动作并行可点。
  const [pendingActions, setPendingActions] = useState<Record<string, boolean>>(
    {},
  );

  useEffect(() => {
    void load().catch(() => undefined);
  }, [load]);

  const expandTask = (task: ScheduledTaskItem) => {
    const willExpand = !expandedTaskIds.has(task.scheduledTaskId);
    toggleExpanded(task.scheduledTaskId, willExpand);
    if (willExpand && !runsByTask[task.scheduledTaskId]) {
      void loadRuns(task.scheduledTaskId);
    }
  };

  const setActionPending = (
    task: ScheduledTaskItem,
    action: InlineAction,
    on: boolean,
  ) => {
    setPendingActions((prev) => {
      const key = `${task.scheduledTaskId}:${action}`;
      const next = { ...prev };
      if (on) next[key] = true;
      else delete next[key];
      return next;
    });
  };

  const isActionPending = (
    task: ScheduledTaskItem,
    action: InlineAction,
  ): boolean => Boolean(pendingActions[`${task.scheduledTaskId}:${action}`]);

  const runPauseOrResume = async (task: ScheduledTaskItem) => {
    const action: InlineAction = task.status === "active" ? "pause" : "resume";
    if (isActionPending(task, action)) return;
    setActionPending(task, action, true);
    const nextStatus: "paused" | "active" =
      action === "pause" ? "paused" : "active";
    try {
      const updated = await patchTask(task.scheduledTaskId, {
        status: nextStatus,
      });
      if (updated) {
        notifySuccess(
          action === "pause"
            ? `已暂停「${task.title}」`
            : `已启用「${task.title}」`,
        );
      } else {
        // patchTask 已在 store 层置 lastError；这里给一个可行动提示。
        notifyWarning(
          action === "pause"
            ? "没能暂停,稍后再试一下。"
            : "没能启用,稍后再试一下。",
        );
      }
    } finally {
      setActionPending(task, action, false);
    }
  };

  const runFireNow = async (task: ScheduledTaskItem) => {
    if (isActionPending(task, "fire")) return;
    setActionPending(task, "fire", true);
    try {
      const fired = await fireNow(task.scheduledTaskId);
      if (fired) {
        notifyInfo(`已触发「${task.title}」,跑完会通知你。`);
      } else {
        notifyWarning("没能触发这条任务，稍后再试一下。");
      }
    } finally {
      setActionPending(task, "fire", false);
    }
  };

  const runDelete = async (task: ScheduledTaskItem) => {
    if (isActionPending(task, "delete")) return;
    setActionPending(task, "delete", true);
    try {
      const removed = await remove(task.scheduledTaskId);
      if (removed) {
        notifySuccess(`已删除「${task.title}」,历史记录保留。`);
      } else {
        notifyWarning("没能删除这条任务，稍后再试一下。");
      }
    } finally {
      setActionPending(task, "delete", false);
    }
  };

  const runSetUnattended = async (
    task: ScheduledTaskItem,
    enabled: boolean,
  ) => {
    if (isActionPending(task, "set-unattended")) return;
    setActionPending(task, "set-unattended", true);
    try {
      const updated = await patchTask(task.scheduledTaskId, {
        unattendedAutoApprove: enabled,
      });
      if (updated) {
        notifySuccess(
          enabled
            ? `已开启「${task.title}」的免确认授权。`
            : `已收回「${task.title}」的免确认授权。`,
        );
      } else {
        notifyWarning(
          enabled
            ? "开启授权失败,稍后再试一下。"
            : "收回授权失败,稍后再试一下。",
        );
      }
    } finally {
      setActionPending(task, "set-unattended", false);
    }
  };

  const openRunSession = async (run: ScheduledTaskRunItem) => {
    if (run.status === "skipped") {
      return;
    }
    if (run.status !== "waiting_user" && run.status !== "failed") {
      // 已成功的 run 只读历史会话：直接打开。running 当前不展示入口。
      setOpeningRunId(run.runId);
      try {
        await selectSession(run.sessionId);
        setRoute("assistant");
      } catch {
        // best-effort：失败留给既有 toast 路径。
      } finally {
        setOpeningRunId(null);
      }
      return;
    }
    // waiting_user / failed：经 takeover REST 获得可继续的 sessionId。
    setOpeningRunId(run.runId);
    try {
      const takeoverResult = await takeover(run.scheduledTaskId, run.runId);
      if (takeoverResult) {
        await selectSession(takeoverResult.sessionId);
        if (
          takeoverResult.recoveryDraft &&
          !useAssistantStore.getState().draft.trim()
        ) {
          setAssistantDraft(takeoverResult.recoveryDraft);
        }
        setRoute("assistant");
      }
    } finally {
      setOpeningRunId(null);
    }
  };

  const heroSubtitle = (() => {
    if (!hydrated) return "正在读取你的定时任务…";
    if (tasksTotal === 0) return "在对话里告诉 AI 要在什么时间做什么";
    if (tasksTotal === 1) return "当前有 1 条定时任务";
    return `当前有 ${tasksTotal} 条定时任务`;
  })();

  return (
    <section className="scheduled-screen" aria-label="调度中心">
      <header className="scheduled-hero">
        <div className="scheduled-hero-text">
          <h2>调度中心</h2>
          <p>{heroSubtitle}</p>
        </div>
        <div className="scheduled-hero-right">
          <IconButton
            label="刷新列表"
            onClick={() => void load().catch(() => undefined)}
            disabled={loading}
          >
            <RefreshCcw size={16} />
          </IconButton>
        </div>
      </header>

      {lastError ? (
        <div className="scheduled-error" role="alert">
          {lastError}
        </div>
      ) : null}

      {loading && tasks.length === 0 ? (
        <div className="scheduled-status">正在加载…</div>
      ) : null}

      {!loading && hydrated && tasks.length === 0 ? (
        <div className="scheduled-empty" role="status">
          <CalendarClock size={40} aria-hidden="true" />
          <p>还没有定时任务</p>
          <span>
            到 AI 助手对话里说一句什么时间做什么，AI 会跟你核对后再创建。
          </span>
          <ul
            className="scheduled-empty-examples"
            aria-label="试试这样和 AI 说"
          >
            {EXAMPLE_PROMPTS.map((prompt) => (
              <li key={prompt}>「{prompt}」</li>
            ))}
          </ul>
        </div>
      ) : null}

      {tasks.length > 0 ? (
        <ul className="scheduled-task-list">
          {tasks.map((task) => {
            const expanded = expandedTaskIds.has(task.scheduledTaskId);
            const runs = runsByTask[task.scheduledTaskId] ?? [];
            const isLoadingRuns = loadingRunsTaskIds.includes(
              task.scheduledTaskId,
            );
            const canPauseOrResume =
              task.status === "active" || task.status === "paused";
            const pauseResumeAction: InlineAction =
              task.status === "active" ? "pause" : "resume";
            const pauseResumeLabel = task.status === "active" ? "暂停" : "启用";
            const PauseResumeIcon = task.status === "active" ? Pause : Play;
            const anyActionOnRow =
              isActionPending(task, "pause") ||
              isActionPending(task, "resume") ||
              isActionPending(task, "fire") ||
              isActionPending(task, "delete");
            return (
              <li
                className="scheduled-task-row"
                data-status={task.status}
                key={task.scheduledTaskId}
              >
                <div className="scheduled-task-head-bar">
                  <button
                    className="scheduled-task-head"
                    type="button"
                    aria-expanded={expanded}
                    aria-label={`${expanded ? "收起" : "展开"}任务执行记录`}
                    onClick={() => expandTask(task)}
                  >
                    <span className="scheduled-task-caret" aria-hidden="true">
                      {expanded ? (
                        <ChevronDown size={16} />
                      ) : (
                        <ChevronRight size={16} />
                      )}
                    </span>
                    <div className="scheduled-task-main">
                      <div className="scheduled-task-titleline">
                        <strong>{task.title}</strong>
                        <Badge tone={statusTone(task.status)}>
                          {STATUS_LABEL[task.status]}
                        </Badge>
                        {task.unattendedAutoApprove ? (
                          <span
                            className="scheduled-task-unattended"
                            title="这条任务在跑时会自动放行高危动作。可在详情里收回授权。"
                          >
                            <ShieldAlert size={12} aria-hidden="true" />
                            <span>已授权免确认</span>
                          </span>
                        ) : null}
                      </div>
                      <div className="scheduled-task-meta">
                        <span className="scheduled-task-schedule">
                          <Clock4 size={12} aria-hidden="true" />
                          {task.scheduleDescription}
                        </span>
                        <span>{nextFireLabel(task)}</span>
                        <span>{lastRunLabel(task)}</span>
                      </div>
                    </div>
                  </button>
                  <div
                    className="scheduled-task-actions"
                    role="group"
                    aria-label="任务操作"
                  >
                    {canPauseOrResume ? (
                      <button
                        type="button"
                        className="scheduled-task-action"
                        disabled={
                          anyActionOnRow ||
                          isActionPending(task, pauseResumeAction)
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          void runPauseOrResume(task);
                        }}
                        aria-label={pauseResumeLabel}
                      >
                        <PauseResumeIcon size={13} aria-hidden="true" />
                        <span>{pauseResumeLabel}</span>
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="scheduled-task-action"
                      disabled={anyActionOnRow || isActionPending(task, "fire")}
                      onClick={(event) => {
                        event.stopPropagation();
                        void runFireNow(task);
                      }}
                      aria-label="现在跑一次"
                      title="立刻触发一次,不影响原排期"
                    >
                      <Sparkles size={13} aria-hidden="true" />
                      <span>现在跑一次</span>
                    </button>
                    <button
                      type="button"
                      className="scheduled-task-action scheduled-task-action-danger"
                      disabled={
                        anyActionOnRow || isActionPending(task, "delete")
                      }
                      onClick={(event) => {
                        event.stopPropagation();
                        void runDelete(task);
                      }}
                      aria-label={`删除${task.title}`}
                      title="删除后历史记录仍保留"
                    >
                      <Trash2 size={13} aria-hidden="true" />
                      <span>删除</span>
                    </button>
                  </div>
                </div>
                {expanded ? (
                  <div className="scheduled-detail">
                    <div className="scheduled-detail-settings">
                      <div className="scheduled-detail-row">
                        <span className="scheduled-detail-label">
                          免确认授权
                        </span>
                        {task.unattendedAutoApprove ? (
                          <>
                            <span className="scheduled-detail-value scheduled-detail-warn">
                              <ShieldAlert size={12} aria-hidden="true" />
                              已开启:跑起来遇到高危动作会自动放行
                            </span>
                            <button
                              type="button"
                              className="scheduled-detail-toggle"
                              disabled={isActionPending(task, "set-unattended")}
                              onClick={() => void runSetUnattended(task, false)}
                            >
                              收回授权
                            </button>
                          </>
                        ) : (
                          <>
                            <span className="scheduled-detail-value scheduled-detail-muted">
                              未开启:遇到高危动作会按拒绝处理
                            </span>
                            <button
                              type="button"
                              className="scheduled-detail-toggle"
                              disabled={isActionPending(task, "set-unattended")}
                              onClick={() => void runSetUnattended(task, true)}
                              title="仅授权这条定时任务自动放行高危动作"
                            >
                              开启授权
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="scheduled-runs">
                      {isLoadingRuns && runs.length === 0 ? (
                        <div className="scheduled-runs-loading">
                          正在读取执行记录…
                        </div>
                      ) : null}
                      {!isLoadingRuns && runs.length === 0 ? (
                        <div className="scheduled-runs-empty">
                          这条任务还没有执行记录。
                        </div>
                      ) : null}
                      {runs.length > 0 ? (
                        <ul className="scheduled-run-list">
                          {runs.map((run) => (
                            <RunRow
                              key={run.runId}
                              run={run}
                              opening={openingRunId === run.runId}
                              onOpen={() => void openRunSession(run)}
                            />
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

function RunRow({
  run,
  opening,
  onOpen,
}: {
  run: ScheduledTaskRunItem;
  opening: boolean;
  onOpen: () => void;
}): JSX.Element {
  const canOpen =
    run.status === "waiting_user" ||
    run.status === "failed" ||
    run.status === "succeeded";
  const openLabel =
    run.status === "waiting_user"
      ? "去帮一把"
      : run.status === "failed"
        ? "接着处理"
        : "查看会话";
  return (
    <li className="scheduled-run-row" data-status={run.status}>
      <span className="scheduled-run-status">
        <Badge tone={runStatusTone(run.status)}>
          {RUN_STATUS_LABEL[run.status]}
        </Badge>
      </span>
      <div className="scheduled-run-body">
        <div className="scheduled-run-time">
          <History size={12} aria-hidden="true" />
          <span>开始 {formatDate(run.startedAt) || "—"}</span>
          {run.finishedAt ? (
            <span>结束 {formatDate(run.finishedAt)}</span>
          ) : null}
        </div>
        {run.summary ? (
          <p className="scheduled-run-summary">{run.summary}</p>
        ) : null}
        {run.failureReason ? (
          <p className="scheduled-run-failure">{run.failureReason}</p>
        ) : null}
      </div>
      <div className="scheduled-run-actions">
        <button
          type="button"
          className="scheduled-run-open"
          disabled={!canOpen || opening}
          onClick={onOpen}
          aria-label={openLabel}
        >
          <MessageSquare size={14} aria-hidden="true" />
          <span>{openLabel}</span>
        </button>
      </div>
    </li>
  );
}

export default ScheduledScreen;
