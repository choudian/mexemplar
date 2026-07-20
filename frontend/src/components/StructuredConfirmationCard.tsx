import { useEffect, useState } from "react";
import { AlarmClock, ShieldAlert } from "lucide-react";

import { Button } from "./primitives";
import type { SchedulingConfirmationDraft } from "../api/scheduledTasks";
import { parseApiDateTime } from "../utils/dates";

const INSTRUCTION_MAX = 4000;
const TITLE_MAX = 120;

export interface StructuredConfirmationCardProps {
  requestId: string;
  draft: SchedulingConfirmationDraft;
  expiresAt: string;
  unattendedAutoApprove: boolean;
  submitting: boolean;
  onSubmit: (editedDraft: SchedulingConfirmationDraft, unattendedAutoApprove: boolean) => void;
  onCancel: () => void;
}

function remainingLabel(expiresAt: string, nowMs: number): string {
  const remainingMs = (parseApiDateTime(expiresAt)?.getTime() ?? Number.NaN) - nowMs;
  if (!Number.isFinite(remainingMs) || remainingMs <= 0) {
    return "已超时";
  }
  const totalSeconds = Math.floor(remainingMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `剩余 ${minutes}:${String(seconds).padStart(2, "0")}`;
}

/**
 * 全局确认卡：核对调度解析结果 + 编辑指令 + 勾选免确认 + 取消。
 * 抽取自 ClarificationCard.tsx 的倒计时/卡片容器模式，但承载 scheduled task 的 draft + 附加布尔开关。
 * 零模型调用，纯展示 + 表单。fail-closed：超时后控件 disabled，等同拒绝创建。
 */
export function StructuredConfirmationCard({
  requestId,
  draft,
  expiresAt,
  unattendedAutoApprove: initialUnattended,
  submitting,
  onSubmit,
  onCancel,
}: StructuredConfirmationCardProps): JSX.Element {
  const [title, setTitle] = useState(draft.title);
  const [instruction, setInstruction] = useState(draft.instruction);
  const [unattendedAutoApprove, setUnattendedAutoApprove] = useState(initialUnattended);
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  // 后端可能换一张新卡（rare），props 变化时同步草稿。
  useEffect(() => {
    setTitle(draft.title);
    setInstruction(draft.instruction);
    setUnattendedAutoApprove(initialUnattended);
  }, [draft.title, draft.instruction, initialUnattended]);

  const countdown = remainingLabel(expiresAt, nowMs);
  const expired = countdown === "已超时";
  const controlsDisabled = submitting || expired;
  const canSubmit = !controlsDisabled && title.trim().length > 0 && instruction.trim().length > 0;

  const scheduleKindLabel = draft.scheduleKind === "recurring" ? "周期任务" : "一次性任务";

  const handleSubmit = () => {
    if (!canSubmit) return;
    onSubmit({ ...draft, title: title.trim(), instruction: instruction.trim() }, unattendedAutoApprove);
  };

  return (
    <div
      className="structured-confirmation"
      role="dialog"
      aria-label="确认创建定时任务"
      data-request-id={requestId}
    >
      <div className="structured-confirmation-title">
        <AlarmClock size={16} aria-hidden="true" />
        <span>需要你确认这条定时任务</span>
        <span className="structured-confirmation-countdown" aria-live="polite">
          {countdown}
        </span>
      </div>

      <dl className="structured-confirmation-meta">
        <div>
          <dt>任务标题</dt>
          <dd>
            <input
              type="text"
              className="structured-confirmation-input"
              aria-label="任务标题"
              maxLength={TITLE_MAX}
              value={title}
              disabled={controlsDisabled}
              onChange={(e) => setTitle(e.target.value)}
            />
          </dd>
        </div>
        <div>
          <dt>触发时间</dt>
          <dd className="structured-confirmation-schedule">{draft.scheduleDescription}</dd>
        </div>
        <div>
          <dt>类型</dt>
          <dd>{scheduleKindLabel}</dd>
        </div>
      </dl>

      <div className="structured-confirmation-instruction">
        <label htmlFor={`structured-confirmation-instruction-${requestId}`}>
          要 AI 帮你做什么（可调整）
        </label>
        <textarea
          id={`structured-confirmation-instruction-${requestId}`}
          className="structured-confirmation-textarea"
          aria-label="任务指令"
          maxLength={INSTRUCTION_MAX}
          value={instruction}
          rows={4}
          disabled={controlsDisabled}
          onChange={(e) => setInstruction(e.target.value)}
        />
      </div>

      <label className={`structured-confirmation-toggle ${unattendedAutoApprove ? "is-on" : ""}`}>
        <input
          type="checkbox"
          checked={unattendedAutoApprove}
          disabled={controlsDisabled}
          onChange={(e) => setUnattendedAutoApprove(e.target.checked)}
        />
        <span className="structured-confirmation-toggle-label">
          <ShieldAlert size={14} aria-hidden="true" />
          <span>允许这个任务在没人值守时自动放行高危动作</span>
        </span>
        <span className="structured-confirmation-toggle-hint">
          勾选后只对这一条任务生效。它跑起来若触发删除文件、执行命令等动作，将不再问你。
          不确定就别勾——可以之后再回收。
        </span>
      </label>

      <div className="structured-confirmation-actions">
        <Button kind="secondary" disabled={controlsDisabled} onClick={onCancel}>
          暂不创建
        </Button>
        <Button kind="primary" disabled={!canSubmit} onClick={handleSubmit}>
          确认创建
        </Button>
      </div>
    </div>
  );
}

export default StructuredConfirmationCard;
