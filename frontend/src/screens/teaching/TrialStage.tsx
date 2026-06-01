import { Check, ShieldAlert, X, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { TrialPreviewRequest } from "../../api/teaching";
import { Button } from "../../components/primitives";
import { useShellStore } from "../../state/shellStore";
import { useSkillsStore } from "../../state/skillsStore";
import { useTeachingStore } from "../../state/teachingStore";
import { AgentBubble, AiMessageContent, ChatComposer, CollapsibleChevron, ThinkingIndicator, UserBubble, filterAgentMessages, useScrollToBottom } from "./shared";

const TRIAL_NEED = 3;
const DONE_COUNTDOWN_SECS = 3;

type TrialStageProps = {
  disabled?: boolean;
  onStart?: (text: string) => void | Promise<void>;
  preview?: TrialPreviewRequest | null;
  onPreviewDecision?: (requestId: string, decision: "approve" | "deny") => void;
};

function usePreviewExpired(preview?: TrialPreviewRequest | null): boolean {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!preview) return;
    const expiresAt = Date.parse(preview.expires_at);
    if (Number.isNaN(expiresAt) || expiresAt <= Date.now()) {
      setNow(Date.now());
      return;
    }
    const delayMs = Math.min(expiresAt - Date.now() + 10, 2_147_483_647);
    const timeout = window.setTimeout(() => setNow(Date.now()), delayMs);
    return () => window.clearTimeout(timeout);
  }, [preview?.expires_at, preview?.requestId]);

  if (!preview) return false;
  const expiresAt = Date.parse(preview.expires_at);
  return Number.isNaN(expiresAt) || expiresAt <= now;
}

function TrialChips({ chips, onPick }: { chips: string[]; onPick: (c: string) => void }): JSX.Element {
  return (
    <div className="teaching-chips">
      {chips.map((c) => (
        <button className="teaching-chip" key={c} onClick={() => onPick(c)} type="button">
          {c}
        </button>
      ))}
    </div>
  );
}

function TrialProcessStrip({
  trace,
  summary,
}: {
  trace: { text: string; detail?: string }[];
  summary: string;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <div className="teaching-trial-strip">
      <button className="teaching-trial-strip-header" onClick={() => setOpen((v) => !v)} type="button">
        <div className="teaching-trial-strip-check">
          <Check size={13} strokeWidth={2.6} />
        </div>
        <span style={{ fontWeight: 500, color: "var(--text)" }}>已完成</span>
        <span style={{ color: "var(--text-muted)" }}>· {summary}</span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {open ? "收起" : "查看过程"}
          <CollapsibleChevron open={open} />
        </span>
      </button>
      {open ? (
        <div className="teaching-trial-strip-body">
          {trace.map((step, i) => (
            <div className="teaching-trial-strip-step" key={i}>
              <span className="teaching-trial-strip-step-num me-mono">
                {String(i + 1).padStart(2, "0")}
              </span>
              <div>
                <div className="teaching-trial-strip-step-text">
                  {step.text}
                  {step.detail ? (
                    <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>{step.detail}</div>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function TrialStage({
  disabled: disabledOverride,
  onStart,
  preview: previewOverride,
  onPreviewDecision,
}: TrialStageProps = {}): JSX.Element {
  const messages = useTeachingStore((s) => s.messages);
  const busy = useTeachingStore((s) => s.busy);
  const stage = useTeachingStore((s) => s.stage);
  const startTrial = useTeachingStore((s) => s.startTrial);
  const closeSkillTrial = useTeachingStore((s) => s.closeSkillTrial);
  const isSkillTrial = useTeachingStore((s) => !!s.skillTrialToolId);
  const trialSuccessCount = useTeachingStore((s) => s.trialSuccessCount);
  const storePreview = useTeachingStore((s) => s.trialPreview);
  const decideTrialPreview = useTeachingStore((s) => s.decideTrialPreview);

  const [draft, setDraft] = useState("");
  const [waitingForAi, setWaitingForAi] = useState(false);
  const [countdown, setCountdown] = useState(3);
  const scrollRef = useRef<HTMLDivElement>(null);

  const trialMessages = useMemo(() => filterAgentMessages(messages, "trial"), [messages]);
  const preview = previewOverride !== undefined ? previewOverride : storePreview;
  const expired = usePreviewExpired(preview);
  const done = trialSuccessCount >= TRIAL_NEED || stage === "published";
  const composerDisabled = disabledOverride || busy || waitingForAi;

  useScrollToBottom(scrollRef, [trialMessages.length, busy]);

  useEffect(() => {
    if (waitingForAi && (done || stage === "failed")) {
      setWaitingForAi(false);
    }
  }, [stage, waitingForAi, done]);

  useEffect(() => {
    if (!done) return;
    let remaining = DONE_COUNTDOWN_SECS;
    setCountdown(remaining);
    const tick = () => {
      remaining--;
      if (remaining <= 0) {
        setCountdown(0);
        closeSkillTrial();
        useShellStore.getState().setRoute("skills");
        useSkillsStore.getState().setCategory("published");
        return;
      }
      setCountdown(remaining);
      timer = setTimeout(tick, 1000);
    };
    let timer = setTimeout(tick, 1000);
    return () => clearTimeout(timer);
  }, [done, closeSkillTrial]);

  useEffect(() => {
    const last = trialMessages[trialMessages.length - 1];
    if (last?.from === "ai" && waitingForAi) {
      setWaitingForAi(false);
    }
  }, [trialMessages.length, waitingForAi]);

  const handleSend = (text: string) => {
    if (!text.trim() || composerDisabled) return;
    setWaitingForAi(true);
    const submittedText = text;
    let submission: Promise<boolean>;
    if (onStart && trialMessages.length === 0) {
      try {
        submission = Promise.resolve(onStart(submittedText)).then(() => true);
      } catch {
        submission = Promise.resolve(false);
      }
    } else {
      submission = startTrial(submittedText);
    }
    void submission.then((accepted) => {
      if (accepted) {
        setDraft((current) => current === text ? "" : current);
      } else {
        setWaitingForAi(false);
      }
    }).catch(() => setWaitingForAi(false));
  };

  const handleVerdict = (ok: boolean) => {
    setWaitingForAi(true);
    startTrial(ok ? "结果正确" : "不太对，再看看").catch(() => setWaitingForAi(false));
  };

  const handlePreviewDecision = (requestId: string, decision: "approve" | "deny") => {
    if (onPreviewDecision) {
      onPreviewDecision(requestId, decision);
      return;
    }
    void decideTrialPreview(requestId, decision);
  };

  return (
    <div className="teaching-chat-stage">
      <div className="teaching-trial-chat-header">
        <div className="teaching-trial-chat-icon" data-done={done ? "true" : undefined}>
          {done ? <Check size={17} strokeWidth={2.4} /> : <Zap size={17} />}
        </div>
        <div className="teaching-trial-chat-title">
          <h4>试用验证</h4>
          <small>{done ? "已通过考核，技能已发布" : `连续 ${TRIAL_NEED} 次成功后自动发布到「已掌握」`}</small>
        </div>
        <div className="teaching-trial-progress-bar">
          {Array.from({ length: TRIAL_NEED }).map((_, i) => (
            <div
              className="teaching-trial-progress-segment"
              data-filled={i < trialSuccessCount ? "true" : undefined}
              key={i}
            />
          ))}
          <span className="teaching-trial-progress-count me-mono" data-done={done ? "true" : undefined}>
            {trialSuccessCount}/{TRIAL_NEED}
          </span>
        </div>
      </div>

      <div className="teaching-chat-scroll me-scroll" ref={scrollRef}>
        <div className="teaching-chat-thread">
          {trialMessages.length === 0 && !busy && !isSkillTrial ? (
            <AgentBubble icon={<Zap size={16} />} label="试用助手">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div>你好，我是试用助手。给我一个真实任务，我用这个技能跑一遍给你看，验证它能不能正常工作。</div>
                <TrialChips
                  chips={["整理上周的客户反馈邮件", "抓取昨天的反馈邮件", "只看 P0 投诉类邮件"]}
                  onPick={handleSend}
                />
              </div>
            </AgentBubble>
          ) : null}

          {trialMessages.map((m, i) => {
            if (m.from === "user") return <UserBubble key={`u-${i}`} text={m.text} />;
            const isLatest = i === trialMessages.length - 1;
            const showVerdict = isLatest && !m.error && !waitingForAi;
            return (
              <AgentBubble key={`a-${i}`} icon={<Zap size={16} />} label="试用助手">
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <AiMessageContent headline={m.headline} detail={m.detail} />
                  {m.detail && !m.error ? (
                    <TrialProcessStrip
                      summary={m.headline}
                      trace={[{ text: m.detail }]}
                    />
                  ) : null}
                  {showVerdict ? (
                    <div className="teaching-trial-verdict">
                      <Button onClick={() => handleVerdict(true)}>
                        <Check size={14} />
                        <span>结果正确</span>
                      </Button>
                      <Button kind="secondary" onClick={() => handleVerdict(false)}>
                        <X size={14} />
                        <span>不太对</span>
                      </Button>
                    </div>
                  ) : null}
                </div>
              </AgentBubble>
            );
          })}

          {busy ? <ThinkingIndicator icon={<Zap size={16} />} /> : null}
        </div>
      </div>

      {preview ? (
        <div className="teaching-trial-preview" role="alert" aria-live="assertive">
          <div className="teaching-trial-preview-title">
            <ShieldAlert size={16} />
            <span>桌面试用确认</span>
          </div>
          <p>{preview.summary}</p>
          <p>{preview.riskSummary}</p>
          <pre>{preview.codePreview}</pre>
          <div className="teaching-trial-preview-actions">
            <Button
              kind="secondary"
              disabled={expired}
              onClick={() => handlePreviewDecision(preview.requestId, "deny")}
            >
              拒绝
            </Button>
            <Button
              kind="primary"
              disabled={expired}
              onClick={() => handlePreviewDecision(preview.requestId, "approve")}
            >
              批准
            </Button>
          </div>
        </div>
      ) : null}

      <div className="teaching-composer-wrap">
        {done ? (
          <div className="teaching-chat-done">
            <div className="teaching-chat-done-hint">
              试用通过，技能 <strong style={{ color: "var(--ok)" }}>已发布</strong>。
              <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>{countdown}s 后自动返回工具列表</span>
            </div>
          </div>
        ) : (
          <ChatComposer
            draft={draft}
            disabled={composerDisabled}
            hint={
              composerDisabled ? (
                "等待技能执行完毕"
              ) : (
                <>
                  <kbd className="teaching-kbd">Enter</kbd> 发送
                </>
              )
            }
            onSend={() => handleSend(draft)}
            placeholder="给我一个真实任务..."
            setDraft={setDraft}
          />
        )}
      </div>
    </div>
  );
}

export default TrialStage;
