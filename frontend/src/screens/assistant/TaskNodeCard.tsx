import {
  AlertTriangle,
  Ban,
  Check,
  CheckCircle2,
  FileText,
  GitBranch,
  GitMerge,
  Loader2,
  PauseCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Send,
  Shield,
  SquareTerminal,
  Undo2,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import type {
  AssistantTaskSnapshot,
  AssistantTodoItem,
  TaskAdjudicationDecision,
  TaskDisplayPhase,
} from "../../api/assistantTasks";
import type {
  ExternalCodingAvailableAction,
  ExternalCodingSessionDetail,
  ExternalCodingSessionTaskSummary,
} from "../../api/externalCodingSessions";
import { useExternalCodingSessionStore } from "../../state/externalCodingSessionStore";

/** displayPhase → 用户可见标签、图标、色调 */
const PHASE_META: Record<
  TaskDisplayPhase,
  { label: string; tone: string; Icon: LucideIcon; spin?: boolean }
> = {
  running: { label: "执行中", tone: "running", Icon: Loader2, spin: true },
  reviewing: { label: "待审核", tone: "reviewing", Icon: Shield },
  needs_attention: {
    label: "需要关注",
    tone: "needs_attention",
    Icon: AlertTriangle,
  },
  paused: { label: "已暂停", tone: "paused", Icon: PauseCircle },
  done: { label: "已完成", tone: "done", Icon: CheckCircle2 },
};

const TODO_STATUS_LABELS: Record<string, string> = {
  todo: "待办",
  doing: "进行中",
  done: "已完成",
  skipped: "已跳过",
};

const EXTERNAL_CODING_TOOL_LABELS: Record<string, string> = {
  claude_code: "Claude Code",
  codex_cli: "Codex CLI",
};

const EXTERNAL_CODING_STATUS_LABELS: Record<string, string> = {
  abandoned: "已放弃",
  completed: "已完成",
  created: "已创建",
  failed: "失败",
  implementing: "实现中",
  interrupted: "已中断",
  merge_blocked: "合并受阻",
  merge_ready: "可合并",
  merged: "已合并",
  plan_approved: "计划通过",
  plan_ready: "待审计划",
  plan_rejected: "计划打回",
  planning: "规划中",
  rollback_proposed: "回滚待确认",
  rolled_back: "已回滚",
  waiting_user: "等用户处理",
};

const EXTERNAL_CODING_PHASE_LABELS: Record<string, string> = {
  done: "完成",
  implement: "实现",
  merge: "合并",
  plan: "计划",
  rollback: "回滚",
};

const EXTERNAL_CODING_BUSY_LABELS: Partial<Record<ExternalCodingAvailableAction, string>> = {
  abandon: "正在放弃 coding session…",
  approve_plan: "正在批准计划…",
  confirm_rollback: "正在执行回滚…",
  escalate_to_user: "正在更新等待状态…",
  merge: "正在执行合并…",
  merge_analysis: "正在分析合并风险…",
  reject_plan: "正在发送修改意见…",
  resume: "正在继续 coding session…",
  rollback_plan: "正在生成回滚方案…",
};

const EXTERNAL_CODING_RISK_LABELS: Record<string, string> = {
  conflict_predicted: "预测存在冲突",
  low: "低风险",
  overlap: "文件存在重叠",
  unknown: "风险未知",
};

const EXTERNAL_CODING_ROLLBACK_LABELS: Record<string, string> = {
  manual: "手动处理",
  reset_hard: "重置历史",
  reverse_patch: "反向补丁",
  revert_commit: "撤销本次提交",
};

type ExternalCodingFormAction = Exclude<
  ExternalCodingAvailableAction,
  "approve_plan" | "inspect"
>;

const WINDOWS_PATH_PATTERN = /\b[A-Za-z]:[\\/][^\s"'<>|]+/g;
const UNC_PATH_PATTERN = /\\\\[^\\\s]+\\[^\s"'<>|]+/g;
const FILE_URL_PATTERN = /file:\/\/\/[^\s"'<>]+/gi;
const UNIX_LOCAL_PATH_PATTERN =
  /(^|[\s("'`])\/(?:Users|home|tmp|var|opt|mnt|workspace|repo|code)(?:\/[^\s"'`)<>{}]+)+/g;

function safeVisibleText(value: string): string {
  return value
    .replace(FILE_URL_PATTERN, "[本地路径已隐藏]")
    .replace(WINDOWS_PATH_PATTERN, "[本地路径已隐藏]")
    .replace(UNC_PATH_PATTERN, "[本地路径已隐藏]")
    .replace(UNIX_LOCAL_PATH_PATTERN, "$1[本地路径已隐藏]");
}

function externalCodingErrorMessage(
  detail: ExternalCodingSessionDetail,
): string | null {
  if (!detail.lastErrorCategory && !detail.lastErrorMessage) return null;
  switch (detail.lastErrorCategory) {
    case "login_required":
      return "外部 coding 工具需要登录。完成登录后可继续此任务。";
    case "network":
      return "网络连接中断。网络恢复后可继续此任务。";
    case "quota_exhausted":
      return "当前工具的可用额度不足。可稍后继续，或放弃后改用其他工具。";
    case "model_unavailable":
      return "所需的高推理档位暂不可用。请稍后继续。";
    case "missing_artifact":
      return "外部 coding 工具没有提交完整结果，请继续任务并补齐结果。";
    case "protocol_violation":
      return "检测到执行过程偏离约定，请查看计划和结果后决定是否继续。";
    default:
      return detail.lastErrorMessage
        ? safeVisibleText(detail.lastErrorMessage)
        : "coding session 未能继续，请刷新状态后重试。";
  }
}

interface ExternalCodingSessionPanelProps {
  summary: ExternalCodingSessionTaskSummary;
}

function ExternalCodingSessionPanel({
  summary,
}: ExternalCodingSessionPanelProps): JSX.Element {
  const codingSessionId = summary.codingSessionId;
  const detail = useExternalCodingSessionStore(
    (state) => state.detailsById[codingSessionId],
  );
  const loading = useExternalCodingSessionStore((state) =>
    state.loadingIds.includes(codingSessionId),
  );
  const busyAction = useExternalCodingSessionStore(
    (state) => state.busyActionById[codingSessionId],
  );
  const error = useExternalCodingSessionStore(
    (state) => state.errorById[codingSessionId] ?? "",
  );
  const notice = useExternalCodingSessionStore(
    (state) => state.noticeById[codingSessionId] ?? "",
  );
  const load = useExternalCodingSessionStore((state) => state.load);
  const refresh = useExternalCodingSessionStore((state) => state.refresh);
  const clearFeedback = useExternalCodingSessionStore(
    (state) => state.clearFeedback,
  );
  const [activeAction, setActiveAction] = useState<ExternalCodingFormAction | null>(
    null,
  );
  const [draftText, setDraftText] = useState("");
  const [resumePhase, setResumePhase] = useState<"" | "plan" | "implement">("");
  const [targetBranch, setTargetBranch] = useState("main");
  const [targetWorktreePath, setTargetWorktreePath] = useState("");

  useEffect(() => {
    if (!detail) {
      void load(codingSessionId);
    }
  }, [codingSessionId, detail, load]);

  const availableActions = detail?.availableActions ?? [];
  const hasAction = (action: ExternalCodingAvailableAction) =>
    availableActions.includes(action);
  const effectiveStatus = detail?.status ?? summary.status;
  const effectivePhase = detail?.phase ?? summary.phase;
  const mergeRecord = detail?.mergeRecords[0];
  const rollbackDecision = detail?.rollbackDecisions[0];
  const visibleError = detail ? externalCodingErrorMessage(detail) : null;
  const busy = Boolean(busyAction);

  const openAction = (action: ExternalCodingFormAction) => {
    clearFeedback(codingSessionId);
    setActiveAction(action);
    setDraftText("");
    setResumePhase("");
    setTargetBranch(mergeRecord?.targetBranch || "main");
    setTargetWorktreePath("");
  };

  const closeAction = () => {
    setActiveAction(null);
    setDraftText("");
    setTargetWorktreePath("");
  };

  const execute = async (operation: () => Promise<boolean>) => {
    if (await operation()) closeAction();
  };

  const submitAction = () => {
    if (!activeAction || busy) return;
    const actions = useExternalCodingSessionStore.getState();
    const trimmedDraft = draftText.trim();
    switch (activeAction) {
      case "reject_plan":
        if (trimmedDraft) {
          void execute(() => actions.rejectPlan(codingSessionId, trimmedDraft));
        }
        break;
      case "resume":
        void execute(() =>
          actions.resume(
            codingSessionId,
            trimmedDraft,
            resumePhase || undefined,
          ),
        );
        break;
      case "abandon":
        if (trimmedDraft) {
          void execute(() => actions.abandon(codingSessionId, trimmedDraft));
        }
        break;
      case "escalate_to_user":
        if (trimmedDraft) {
          void execute(() => actions.escalateToUser(codingSessionId, trimmedDraft));
        }
        break;
      case "merge_analysis":
        if (targetBranch.trim() && targetWorktreePath.trim()) {
          void execute(() =>
            actions.analyzeMerge(
              codingSessionId,
              targetBranch.trim(),
              targetWorktreePath.trim(),
            ),
          );
        }
        break;
      case "merge":
        if (
          mergeRecord &&
          (mergeRecord.conflictRisk === "low" || trimmedDraft)
        ) {
          void execute(() =>
            actions.merge(codingSessionId, mergeRecord.mergeRecordId, trimmedDraft),
          );
        }
        break;
      case "rollback_plan":
        if (trimmedDraft) {
          void execute(() => actions.planRollback(codingSessionId, trimmedDraft));
        }
        break;
      case "confirm_rollback":
        if (rollbackDecision) {
          void execute(() =>
            actions.confirmRollback(codingSessionId, rollbackDecision.rollbackId),
          );
        }
        break;
    }
  };

  const needsText =
    activeAction === "reject_plan" ||
    activeAction === "abandon" ||
    activeAction === "escalate_to_user" ||
    activeAction === "rollback_plan" ||
    (activeAction === "merge" && mergeRecord?.conflictRisk !== "low");
  const canSubmit =
    !busy &&
    (activeAction === "resume" ||
      activeAction === "confirm_rollback" ||
      (activeAction === "merge_analysis"
        ? Boolean(targetBranch.trim() && targetWorktreePath.trim())
        : needsText
          ? Boolean(draftText.trim())
          : activeAction === "merge" && Boolean(mergeRecord)));

  return (
    <section
      className="assistant-external-coding-item"
      onDoubleClick={(event) => event.stopPropagation()}
    >
      <div className="assistant-external-coding-head">
        <span className="assistant-external-coding-tool">
          <SquareTerminal size={13} />
          {EXTERNAL_CODING_TOOL_LABELS[summary.tool] ?? summary.tool}
        </span>
        <span className="assistant-external-coding-status">
          {EXTERNAL_CODING_STATUS_LABELS[effectiveStatus] ?? effectiveStatus}
        </span>
        <button
          type="button"
          className="assistant-external-coding-refresh"
          title="刷新 coding session 状态"
          aria-label="刷新 coding session 状态"
          disabled={loading || busy}
          onClick={() => void refresh(codingSessionId)}
        >
          <RefreshCw size={13} className={loading ? "assistant-spin" : undefined} />
        </button>
      </div>

      <div className="assistant-external-coding-meta">
        <span>
          <FileText size={12} />
          {EXTERNAL_CODING_PHASE_LABELS[effectivePhase] ?? effectivePhase}
        </span>
        {detail?.branchName ? (
          <span>
            <GitBranch size={12} />
            {detail.branchName}
          </span>
        ) : null}
      </div>

      {loading && !detail ? (
        <p className="assistant-external-coding-progress" role="status">
          <Loader2 size={12} className="assistant-spin" />
          正在加载详情…
        </p>
      ) : null}
      {detail?.planPreview ? (
        <div className="assistant-external-coding-preview">
          <strong>计划摘要</strong>
          <p>{safeVisibleText(detail.planPreview)}</p>
        </div>
      ) : null}
      {detail?.resultPreview ? (
        <div className="assistant-external-coding-preview">
          <strong>结果摘要</strong>
          <p>{safeVisibleText(detail.resultPreview)}</p>
        </div>
      ) : null}
      {detail?.logTail ? (
        <div className="assistant-external-coding-log">
          <strong>最近活动</strong>
          <pre className="assistant-external-coding-logtail">
            {safeVisibleText(detail.logTail)}
          </pre>
        </div>
      ) : null}
      {visibleError ? (
        <p className="assistant-external-coding-error">{visibleError}</p>
      ) : null}
      {detail?.reviewRecommended && detail.reviewSkippedReason ? (
        <p className="assistant-external-coding-review">
          <Shield size={12} />
          {safeVisibleText(detail.reviewSkippedReason)}
        </p>
      ) : null}

      {detail && availableActions.some((action) => action !== "inspect") ? (
        <div
          className="assistant-external-coding-actions"
          aria-label="coding session 可用操作"
        >
          {hasAction("approve_plan") ? (
            <button
              type="button"
              className="assistant-external-coding-action is-primary"
              disabled={busy}
              onClick={() =>
                void useExternalCodingSessionStore
                  .getState()
                  .approvePlan(codingSessionId)
              }
            >
              <Check size={12} />
              批准计划
            </button>
          ) : null}
          {hasAction("reject_plan") ? (
            <button
              type="button"
              className="assistant-external-coding-action"
              disabled={busy}
              onClick={() => openAction("reject_plan")}
            >
              <Undo2 size={12} />
              打回计划
            </button>
          ) : null}
          {hasAction("resume") ? (
            <button
              type="button"
              className="assistant-external-coding-action is-primary"
              disabled={busy}
              onClick={() => openAction("resume")}
            >
              <Play size={12} />
              继续
            </button>
          ) : null}
          {hasAction("merge_analysis") ? (
            <button
              type="button"
              className="assistant-external-coding-action is-primary"
              disabled={busy}
              onClick={() => openAction("merge_analysis")}
            >
              <Shield size={12} />
              分析合并
            </button>
          ) : null}
          {hasAction("merge") ? (
            <button
              type="button"
              className="assistant-external-coding-action is-primary"
              disabled={busy || !mergeRecord}
              onClick={() => openAction("merge")}
            >
              <GitMerge size={12} />
              执行合并
            </button>
          ) : null}
          {hasAction("rollback_plan") ? (
            <button
              type="button"
              className="assistant-external-coding-action"
              disabled={busy}
              onClick={() => openAction("rollback_plan")}
            >
              <RotateCcw size={12} />
              准备回滚
            </button>
          ) : null}
          {hasAction("confirm_rollback") ? (
            <button
              type="button"
              className="assistant-external-coding-action is-danger"
              disabled={busy || !rollbackDecision}
              onClick={() => openAction("confirm_rollback")}
            >
              <RotateCcw size={12} />
              确认回滚
            </button>
          ) : null}
          {hasAction("escalate_to_user") ? (
            <button
              type="button"
              className="assistant-external-coding-action"
              disabled={busy}
              onClick={() => openAction("escalate_to_user")}
            >
              <Send size={12} />
              等待用户处理
            </button>
          ) : null}
          {hasAction("abandon") ? (
            <button
              type="button"
              className="assistant-external-coding-action is-danger"
              disabled={busy}
              onClick={() => openAction("abandon")}
            >
              <Ban size={12} />
              放弃
            </button>
          ) : null}
        </div>
      ) : null}

      {activeAction && hasAction(activeAction) ? (
        <div className="assistant-external-coding-action-form">
          <div className="assistant-external-coding-form-head">
            <strong>
              {activeAction === "reject_plan"
                ? "说明需要调整的内容"
                : activeAction === "resume"
                  ? "继续此 coding session"
                  : activeAction === "abandon"
                    ? "说明放弃原因"
                    : activeAction === "escalate_to_user"
                      ? "说明需要用户处理的事项"
                      : activeAction === "merge_analysis"
                        ? "选择合并目标"
                        : activeAction === "merge"
                          ? "确认执行合并"
                          : activeAction === "rollback_plan"
                            ? "说明希望撤销的内容"
                            : "确认执行回滚"
              }
            </strong>
            <button
              type="button"
              className="assistant-external-coding-form-close"
              aria-label="取消当前操作"
              title="取消"
              disabled={busy}
              onClick={closeAction}
            >
              <X size={13} />
            </button>
          </div>

          {activeAction === "resume" ? (
            <>
              <select
                aria-label="继续阶段"
                value={resumePhase}
                disabled={busy}
                onChange={(event) =>
                  setResumePhase(
                    event.currentTarget.value as "" | "plan" | "implement",
                  )
                }
              >
                <option value="">继续当前阶段</option>
                <option value="plan">重新规划</option>
                <option value="implement">继续实现</option>
              </select>
              <textarea
                aria-label="继续说明（可选）"
                placeholder="补充说明（可选）"
                rows={2}
                value={draftText}
                disabled={busy}
                onChange={(event) => setDraftText(event.currentTarget.value)}
              />
            </>
          ) : null}

          {activeAction === "merge_analysis" ? (
            <div className="assistant-external-coding-merge-fields">
              <label>
                <span>目标分支</span>
                <input
                  aria-label="合并目标分支"
                  value={targetBranch}
                  disabled={busy}
                  onChange={(event) => setTargetBranch(event.currentTarget.value)}
                />
              </label>
              <label>
                <span>目标工作区</span>
                <input
                  type="password"
                  autoComplete="off"
                  aria-label="合并目标工作区路径"
                  placeholder="输入本地路径"
                  value={targetWorktreePath}
                  disabled={busy}
                  onChange={(event) =>
                    setTargetWorktreePath(event.currentTarget.value)
                  }
                />
              </label>
              <small>路径仅用于本次分析，不会在此处显示。</small>
            </div>
          ) : null}

          {activeAction === "merge" && mergeRecord ? (
            <div className="assistant-external-coding-risk-summary">
              <span>
                {EXTERNAL_CODING_RISK_LABELS[mergeRecord.conflictRisk] ??
                  "风险未知"}
              </span>
              <span>{mergeRecord.changedFiles.length} 个变更文件</span>
              <span>{mergeRecord.overlapFiles.length} 个重叠文件</span>
            </div>
          ) : null}

          {activeAction === "confirm_rollback" && rollbackDecision ? (
            <div className="assistant-external-coding-confirm-copy">
              <p>
                将按“
                {EXTERNAL_CODING_ROLLBACK_LABELS[rollbackDecision.chosenStrategy] ??
                  "受控回滚"}
                ”执行。此操作会修改当前代码，请确认已理解影响。
              </p>
              {rollbackDecision.safeExplanation ? (
                <p>{safeVisibleText(rollbackDecision.safeExplanation)}</p>
              ) : null}
            </div>
          ) : null}

          {needsText ? (
            <textarea
              aria-label={
                activeAction === "merge"
                  ? "合并风险裁定说明"
                  : activeAction === "rollback_plan"
                    ? "回滚意图"
                    : activeAction === "reject_plan"
                      ? "计划修改意见"
                      : activeAction === "abandon"
                        ? "放弃原因"
                        : "等待用户处理原因"
              }
              placeholder={
                activeAction === "merge"
                  ? "说明为何可以在当前风险下继续"
                  : "填写说明"
              }
              rows={2}
              value={draftText}
              disabled={busy}
              onChange={(event) => setDraftText(event.currentTarget.value)}
            />
          ) : null}

          <button
            type="button"
            className={`assistant-external-coding-form-submit${
              activeAction === "abandon" || activeAction === "confirm_rollback"
                ? " is-danger"
                : ""
            }`}
            disabled={!canSubmit}
            onClick={submitAction}
          >
            {busy ? <Loader2 size={12} className="assistant-spin" /> : <Check size={12} />}
            {activeAction === "merge_analysis"
              ? "开始分析"
              : activeAction === "merge"
                ? "确认合并"
                : activeAction === "confirm_rollback"
                  ? "执行回滚"
                  : "确认"
            }
          </button>
        </div>
      ) : null}

      {busyAction ? (
        <p className="assistant-external-coding-progress" role="status">
          <Loader2 size={12} className="assistant-spin" />
          {EXTERNAL_CODING_BUSY_LABELS[busyAction] ?? "正在处理…"}
        </p>
      ) : null}
      {error ? (
        <div className="assistant-external-coding-feedback is-error" role="alert">
          <AlertTriangle size={13} />
          <span>{error}</span>
          <button
            type="button"
            aria-label="关闭错误提示"
            title="关闭"
            onClick={() => clearFeedback(codingSessionId)}
          >
            <X size={12} />
          </button>
        </div>
      ) : null}
      {notice ? (
        <div
          className="assistant-external-coding-feedback is-success"
          role="status"
          aria-live="polite"
        >
          <CheckCircle2 size={13} />
          <span>{notice}</span>
          <button
            type="button"
            aria-label="关闭成功提示"
            title="关闭"
            onClick={() => clearFeedback(codingSessionId)}
          >
            <X size={12} />
          </button>
        </div>
      ) : null}
    </section>
  );
}

interface TaskNodeCardProps {
  task: AssistantTaskSnapshot;
  todos?: AssistantTodoItem[];
  onLoadTodos?: (taskId: string) => void;
  onDecide?: (
    adjudicationId: string,
    decision: TaskAdjudicationDecision,
    instruction?: string,
  ) => void;
  onContinueGraph?: (graphId: string) => void;
}

/**
 * DAG 调度节点卡片（025）：交互对齐 SubagentCard——收起看标题+状态，
 * 双击/Enter 就地展开看详情（描述、暂停原因、todo 子步骤、裁定操作）。
 * 暂停（user_stop）时底部显示"继续任务"按钮。
 */
function TaskNodeCard({
  task,
  todos,
  onLoadTodos,
  onDecide,
  onContinueGraph,
}: TaskNodeCardProps): JSX.Element {
  const meta = PHASE_META[task.displayPhase] ?? PHASE_META.running;
  const [expanded, setExpanded] = useState(false);
  const [todoExpanded, setTodoExpanded] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [note, setNote] = useState("");

  const showContinue =
    task.displayPhase === "paused" && task.suspendReason === "user_stop";
  const showAdjudication = task.requiresReview && !!task.adjudicationId;
  const externalCodingSessions = task.externalCodingSessions ?? [];

  const handleToggle = () => {
    setExpanded((prev) => !prev);
  };

  const handleTodoToggle = () => {
    const next = !todoExpanded;
    setTodoExpanded(next);
    if (next) onLoadTodos?.(task.taskId);
  };

  const submitContinue = () => {
    onContinueGraph?.(task.graphId);
    setContinuing(false);
    setNote("");
  };

  return (
    <div
      className="assistant-subcard assistant-task-node"
      data-status={meta.tone}
      data-phase={task.displayPhase}
      role="button"
      tabIndex={0}
      aria-label={`任务 ${task.title}，${meta.label}，双击或回车查看详情`}
      title="双击查看任务详情"
      onDoubleClick={handleToggle}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleToggle();
        }
      }}
    >
      <div className="assistant-subcard-icon" aria-hidden="true">
        <meta.Icon size={16} className={meta.spin ? "assistant-spin" : undefined} />
      </div>
      <div className="assistant-subcard-body">
        <div className="assistant-subcard-head">
          <strong>{task.title}</strong>
          {task.requiresConfirmation ? (
            <span
              className="assistant-subcard-confirm-flag"
              role="img"
              title="高风险/不可逆节点，执行前需确认"
              aria-label="需确认"
            >
              <AlertTriangle size={14} />
            </span>
          ) : null}
          <span className={`assistant-subcard-status assistant-subcard-status-${meta.tone}`}>
            {meta.label}
          </span>
        </div>

        {/* 展开详情区 */}
        {expanded ? (
          <div className="assistant-task-node-detail">
            {task.descriptionPreview ? (
              <p className="assistant-task-node-desc">{task.descriptionPreview}</p>
            ) : null}
            {task.safeExplanation ? (
              <p className="assistant-task-node-explanation">{task.safeExplanation}</p>
            ) : null}

            {externalCodingSessions.length > 0 ? (
              <div className="assistant-external-coding-list" aria-label={`${task.title} 的外部 coding session`}>
                {externalCodingSessions.map((session) => (
                  <ExternalCodingSessionPanel
                    key={session.codingSessionId}
                    summary={session}
                  />
                ))}
              </div>
            ) : null}

            {/* 子步骤 */}
            <button
              type="button"
              className="assistant-link assistant-task-node-todo-toggle"
              aria-expanded={todoExpanded}
              onClick={(e) => {
                e.stopPropagation();
                handleTodoToggle();
              }}
              onDoubleClick={(e) => e.stopPropagation()}
            >
              {todoExpanded ? "收起子步骤" : "查看子步骤"}
            </button>
            {todoExpanded ? (
              todos && todos.length > 0 ? (
                <ul className="task-node-todo-list" aria-label={`${task.title} 的子步骤`}>
                  {todos.map((todo) => (
                    <li
                      key={todo.todoId}
                      className={`task-node-todo-item task-node-todo-${todo.status}`}
                    >
                      <span className="todo-status">
                        {TODO_STATUS_LABELS[todo.status] ?? todo.status}
                      </span>
                      <span className="todo-text">{todo.text}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="task-node-todo-empty">暂无子步骤信息</p>
              )
            ) : null}

            {/* 裁定操作 */}
            {showAdjudication ? (
              <div className="assistant-task-node-adjudication" aria-label={`${task.title} 审核`}>
                <button
                  type="button"
                  className="assistant-task-node-decide-btn assistant-task-node-decide-accept"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDecide?.(task.adjudicationId!, "accepted");
                  }}
                  onDoubleClick={(e) => e.stopPropagation()}
                >
                  认可
                </button>
                <button
                  type="button"
                  className="assistant-task-node-decide-btn assistant-task-node-decide-return"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDecide?.(task.adjudicationId!, "returned", "请根据反馈返工。");
                  }}
                  onDoubleClick={(e) => e.stopPropagation()}
                >
                  打回
                </button>
                <button
                  type="button"
                  className="assistant-task-node-decide-btn assistant-task-node-decide-abandon"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDecide?.(task.adjudicationId!, "abandoned");
                  }}
                  onDoubleClick={(e) => e.stopPropagation()}
                >
                  放弃
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="assistant-subcard-foot">
          <button
            type="button"
            className="assistant-link"
            onClick={(event) => {
              event.stopPropagation();
              handleToggle();
            }}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            {expanded ? "收起详情" : "双击 / 点这里查看详情"}
          </button>

          {/* 暂停续跑 */}
          {showContinue && onContinueGraph ? (
            continuing ? (
              <div
                className="assistant-continue-form"
                onClick={(event) => event.stopPropagation()}
                onDoubleClick={(event) => event.stopPropagation()}
              >
                <input
                  className="assistant-continue-input"
                  aria-label="继续任务的补充说明（可选）"
                  placeholder="补充一句（可选）…"
                  value={note}
                  onChange={(event) => setNote(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      event.stopPropagation();
                      submitContinue();
                    } else {
                      event.stopPropagation();
                    }
                  }}
                />
                <button
                  type="button"
                  className="assistant-continue-btn"
                  onClick={(event) => {
                    event.stopPropagation();
                    submitContinue();
                  }}
                  onKeyDown={(event) => event.stopPropagation()}
                >
                  <Play size={12} />
                  继续
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="assistant-continue-btn"
                onClick={(event) => {
                  event.stopPropagation();
                  setContinuing(true);
                }}
                onKeyDown={(event) => event.stopPropagation()}
              >
                <Play size={12} />
                继续任务
              </button>
            )
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default TaskNodeCard;
