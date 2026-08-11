import { useEffect, useRef } from "react";
import { ArrowUpRight, Clock4, Loader2, X } from "lucide-react";

import { Badge } from "../../components/primitives";
import SafeMarkdown from "../assistant/SafeMarkdown";
import {
  isScheduledTriggerMessage,
  useScheduledSessionStore,
} from "../../state/scheduledSessionStore";
import { formatMonthDayTime } from "../../utils/dates";
import type { AssistantMessage } from "../../api/assistant";
import type { ScheduledRunStatus } from "../../api/scheduledTasks";

const RUN_STATUS_LABEL: Record<ScheduledRunStatus, string> = {
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  waiting_user: "需要你的帮助",
  skipped: "本次跳过",
};

function runStatusTone(status: ScheduledRunStatus): "neutral" | "ok" | "warn" | "danger" {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "danger";
  if (status === "waiting_user") return "warn";
  return "neutral";
}

/**
 * 调度中心「查看这一轮」弹窗。
 *
 * 这一屏回答的问题是"我不在的时候它干了什么"，所以第一条消息如实标成自动触发，
 * 而不是伪装成用户说过的话——那段文本是调度系统投的 prompt 脚手架，用户从没打过。
 */
export function ScheduledSessionDialog({
  onOpenInAssistant,
}: {
  /** 跳主助理屏接着处理；弹窗只做轻量对话，任务图/执行体/失败恢复都在那边。 */
  onOpenInAssistant: (sessionId: string) => void;
}): JSX.Element | null {
  const open = useScheduledSessionStore((s) => s.open);
  const task = useScheduledSessionStore((s) => s.task);
  const run = useScheduledSessionStore((s) => s.run);
  const messages = useScheduledSessionStore((s) => s.messages);
  const loading = useScheduledSessionStore((s) => s.loading);
  const sending = useScheduledSessionStore((s) => s.sending);
  const running = useScheduledSessionStore((s) => s.running);
  const draft = useScheduledSessionStore((s) => s.draft);
  const error = useScheduledSessionStore((s) => s.error);
  const close = useScheduledSessionStore((s) => s.close);
  const setDraft = useScheduledSessionStore((s) => s.setDraft);
  const send = useScheduledSessionStore((s) => s.send);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  // 新消息到达时贴住底部——这一屏是按时间读下来的，最新一条最重要。
  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length, running]);

  if (!open || !task || !run) return null;

  const canSend = draft.trim().length > 0 && !sending && !running;
  // 这两种结局往往要看任务图、执行体或改重试，弹窗故意不装这些能力，给个明确出口。
  const needsFullScreen = run.status === "waiting_user" || run.status === "failed";

  return (
    <div className="me-modal" onClick={close}>
      <div
        className="me-dlg sched-session-dlg"
        role="dialog"
        aria-modal="true"
        aria-label={`${task.title} 这一轮的对话`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="me-dlg-bar">
          <strong>{task.title}</strong>
          <Badge tone={runStatusTone(run.status)}>{RUN_STATUS_LABEL[run.status]}</Badge>
          <span className="dlg-stats">{formatMonthDayTime(run.startedAt) || ""}</span>
          <button type="button" className="me-icon-button" aria-label="关闭" onClick={close}>
            <X size={16} />
          </button>
        </div>

        <div className="sched-session-body" ref={scrollRef}>
          {loading ? (
            <div className="sched-session-state">
              <Loader2 size={18} className="assistant-spin" aria-hidden="true" />
              <span>正在打开这一轮的记录…</span>
            </div>
          ) : messages.length === 0 ? (
            <div className="sched-session-state">这一轮没有留下对话内容。</div>
          ) : (
            messages.map((message) => (
              <ScheduledMessage key={message.sequence} message={message} startedAt={run.startedAt} />
            ))
          )}
          {running ? (
            <div className="sched-session-running">
              <Loader2 size={14} className="assistant-spin" aria-hidden="true" />
              <span>正在处理…</span>
            </div>
          ) : null}
        </div>

        {error ? <p className="sched-session-error">{error}</p> : null}

        {needsFullScreen && run.sessionId ? (
          <div className="sched-session-handoff">
            <span>要看任务分解或改重试，去主助理里更顺手。</span>
            <button
              type="button"
              className="me-button me-button-secondary"
              onClick={() => onOpenInAssistant(run.sessionId as string)}
            >
              在主助理里继续
              <ArrowUpRight size={13} aria-hidden="true" />
            </button>
          </div>
        ) : null}

        <div className="sched-session-footer">
          <textarea
            className="sched-session-input"
            aria-label="接着说点什么"
            placeholder={running ? "正在处理，稍等一下…" : "接着说点什么…"}
            rows={2}
            value={draft}
            disabled={running}
            onChange={(event) => setDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (canSend) void send();
              }
            }}
          />
          <button
            type="button"
            className="me-button me-button-primary"
            disabled={!canSend}
            onClick={() => void send()}
          >
            {sending ? "发送中…" : "发送"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ScheduledMessage({
  message,
  startedAt,
}: {
  message: AssistantMessage;
  startedAt: string;
}): JSX.Element {
  // 调度投的那条不是用户说的话：标成自动触发，不摊内部 prompt 原文。
  if (isScheduledTriggerMessage(message)) {
    return (
      <div className="sched-session-trigger">
        <Clock4 size={12} aria-hidden="true" />
        <span>自动触发 {formatMonthDayTime(startedAt) || ""}</span>
      </div>
    );
  }

  if (message.role === "summary") {
    return (
      <details className="assistant-summary">
        <summary>之前的对话内容</summary>
        <div className="assistant-summary-body">
          <SafeMarkdown content={message.content} />
        </div>
      </details>
    );
  }

  return (
    <article className="assistant-message" data-role={message.role}>
      {message.role === "assistant" ? <div className="assistant-avatar" aria-hidden="true" /> : null}
      <div className="assistant-message-content">
        <div className="assistant-message-meta">{message.role === "user" ? "你" : "Assistant"}</div>
        {message.rendering === "safe_markdown" ? (
          <SafeMarkdown content={message.content} />
        ) : (
          <p>{message.content}</p>
        )}
      </div>
    </article>
  );
}

export default ScheduledSessionDialog;
