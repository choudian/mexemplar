import { Bot, Loader2, PauseCircle, CheckCircle2, AlertTriangle, Play } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";

import type { Subagent } from "../../state/assistantStore";

const STATUS_META: Record<
  Subagent["status"],
  { label: string; tone: string; Icon: LucideIcon; spin?: boolean }
> = {
  running: { label: "运行中", tone: "running", Icon: Loader2, spin: true },
  done: { label: "已完成", tone: "done", Icon: Bot },
  suspended: { label: "已暂停", tone: "suspended", Icon: PauseCircle },
  failed: { label: "失败", tone: "failed", Icon: AlertTriangle },
};

/**
 * 子任务卡片（US4 + US5）：实时状态/动效，双击或回车/空格查看详情（键盘可达，P2-a11y）。
 * 已暂停卡片提供"继续任务"（US5），可填补充消息一并带入续跑。
 */
function SubagentCard({
  subagent,
  onOpen,
  onContinue,
}: {
  subagent: Subagent;
  onOpen: () => void;
  onContinue?: (supplemental: string) => void;
}): JSX.Element {
  const meta = STATUS_META[subagent.status];
  const [continuing, setContinuing] = useState(false);
  const [note, setNote] = useState("");

  const submitContinue = () => {
    onContinue?.(note.trim());
    setContinuing(false);
    setNote("");
  };

  return (
    <div
      className="assistant-subcard"
      data-status={subagent.status}
      role="button"
      tabIndex={0}
      aria-label={`子任务 ${subagent.label}，${meta.label}，双击或回车查看详情`}
      title="双击查看子助手在做什么"
      onDoubleClick={onOpen}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <div className="assistant-subcard-icon" aria-hidden="true">
        <meta.Icon size={16} className={meta.spin ? "assistant-spin" : undefined} />
      </div>
      <div className="assistant-subcard-body">
        <div className="assistant-subcard-head">
          <strong>{subagent.label}</strong>
          <span className={`assistant-subcard-status assistant-subcard-status-${meta.tone}`}>
            {subagent.status === "done" ? <CheckCircle2 size={12} /> : null}
            {meta.label}
          </span>
        </div>
        <p className="assistant-subcard-task">{subagent.task}</p>
        {subagent.lastOutput ? <p className="assistant-subcard-output">{subagent.lastOutput}</p> : null}
        <div className="assistant-subcard-foot">
          <button
            type="button"
            className="assistant-link"
            onClick={(event) => {
              event.stopPropagation();
              onOpen();
            }}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            双击 / 点这里看它在做什么
          </button>
          {subagent.status === "suspended" && onContinue ? (
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

export default SubagentCard;
