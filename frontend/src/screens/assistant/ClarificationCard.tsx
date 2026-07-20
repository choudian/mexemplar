import { useEffect, useState } from "react";
import { HelpCircle } from "lucide-react";

import type { ClarificationQuestion, ClarificationRequest } from "../../api/assistant";
import type { ClarificationQuestionDraft } from "../../state/assistantStore";
import { Button } from "../../components/primitives";
import { parseApiDateTime } from "../../utils/dates";

const OTHER_TEXT_MAX = 1000;

export const EMPTY_DRAFT: ClarificationQuestionDraft = {
  optionIds: [],
  otherSelected: false,
  otherText: "",
};

/** 单题是否已作答（驱动提交按钮可用性）。导出供单测复用。 */
export function isQuestionAnswered(
  question: ClarificationQuestion,
  draft: ClarificationQuestionDraft,
): boolean {
  const hasOther = draft.otherSelected && draft.otherText.trim().length > 0;
  if (question.multiSelect) {
    return draft.optionIds.length > 0 || hasOther;
  }
  // 单选：恰好一个选项 或 选了"其他"且填了内容（二选一）
  const hasOption = draft.optionIds.length === 1 && !draft.otherSelected;
  return hasOption || (hasOther && draft.optionIds.length === 0);
}

export function allQuestionsAnswered(
  clarification: ClarificationRequest,
  drafts: Record<string, ClarificationQuestionDraft>,
): boolean {
  return clarification.questions.every((q) =>
    isQuestionAnswered(q, drafts[q.questionId] ?? EMPTY_DRAFT),
  );
}

function remainingLabel(expiresAt: string | null | undefined, nowMs: number): string | null {
  if (!expiresAt) {
    return null;
  }
  const remainingMs = (parseApiDateTime(expiresAt)?.getTime() ?? Number.NaN) - nowMs;
  if (Number.isNaN(remainingMs) || remainingMs <= 0) {
    return "即将超时";
  }
  const totalSeconds = Math.floor(remainingMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `剩余 ${minutes}:${String(seconds).padStart(2, "0")}`;
}

function ClarificationCard({
  clarification,
  drafts,
  submitting,
  onDraftChange,
  onSubmit,
  onCancel,
}: {
  clarification: ClarificationRequest;
  drafts: Record<string, ClarificationQuestionDraft>;
  submitting: boolean;
  onDraftChange: (questionId: string, draft: ClarificationQuestionDraft) => void;
  onSubmit: () => void;
  onCancel: () => void;
}): JSX.Element {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const countdown = remainingLabel(clarification.expiresAt, nowMs);
  const expired = Boolean(clarification.expiresAt) && countdown === "即将超时";
  const controlsDisabled = submitting || expired;
  const canSubmit = !controlsDisabled && allQuestionsAnswered(clarification, drafts);

  const getDraft = (questionId: string): ClarificationQuestionDraft =>
    drafts[questionId] ?? EMPTY_DRAFT;

  const selectSingle = (questionId: string, optionId: string) => {
    onDraftChange(questionId, { optionIds: [optionId], otherSelected: false, otherText: "" });
  };

  const toggleMulti = (questionId: string, optionId: string) => {
    const draft = getDraft(questionId);
    const next = draft.optionIds.includes(optionId)
      ? draft.optionIds.filter((id) => id !== optionId)
      : [...draft.optionIds, optionId];
    onDraftChange(questionId, { ...draft, optionIds: next });
  };

  const selectOther = (questionId: string, multiSelect: boolean) => {
    const draft = getDraft(questionId);
    if (multiSelect) {
      // 多选：切换"其他"，普通选项保留
      onDraftChange(questionId, { ...draft, otherSelected: !draft.otherSelected });
    } else {
      // 单选：选"其他"取消普通选项
      onDraftChange(questionId, { optionIds: [], otherSelected: true, otherText: draft.otherText });
    }
  };

  const setOtherText = (questionId: string, text: string) => {
    const draft = getDraft(questionId);
    onDraftChange(questionId, {
      ...draft,
      otherText: text.slice(0, OTHER_TEXT_MAX),
      otherSelected: true,
    });
  };

  return (
    <div className="assistant-clarification" role="group" aria-label="助手需要你确认几个问题">
      <div className="assistant-clarification-title">
        <HelpCircle size={16} />
        <span>需要你的确认</span>
        {countdown ? (
          <span className="assistant-clarification-countdown" aria-live="polite">
            {countdown}
          </span>
        ) : null}
      </div>

      {clarification.questions.map((question) => {
        const draft = getDraft(question.questionId);
        const inputName = `clarification-${clarification.requestId}-${question.questionId}`;
        return (
          <fieldset
            key={question.questionId}
            className="assistant-clarification-question"
            disabled={controlsDisabled}
          >
            <legend>{question.question}</legend>
            {question.options.map((option) => {
              const checked = question.multiSelect
                ? draft.optionIds.includes(option.optionId)
                : draft.optionIds[0] === option.optionId && !draft.otherSelected;
              return (
                <label key={option.optionId} className="assistant-clarification-option">
                  <input
                    type={question.multiSelect ? "checkbox" : "radio"}
                    name={inputName}
                    checked={checked}
                    disabled={controlsDisabled}
                    onChange={() =>
                      question.multiSelect
                        ? toggleMulti(question.questionId, option.optionId)
                        : selectSingle(question.questionId, option.optionId)
                    }
                  />
                  <span className="assistant-clarification-option-label">{option.label}</span>
                  {option.description ? (
                    <span className="assistant-clarification-option-desc">{option.description}</span>
                  ) : null}
                  {option.preview ? (
                    // 纯文本预览：不渲染 HTML/Markdown
                    <span className="assistant-clarification-option-preview">{option.preview}</span>
                  ) : null}
                </label>
              );
            })}

            <label className="assistant-clarification-option assistant-clarification-other">
              <input
                type={question.multiSelect ? "checkbox" : "radio"}
                name={inputName}
                checked={draft.otherSelected}
                disabled={controlsDisabled}
                onChange={() => selectOther(question.questionId, question.multiSelect)}
              />
              <span className="assistant-clarification-option-label">其他</span>
            </label>
            {draft.otherSelected ? (
              <input
                type="text"
                className="assistant-clarification-other-input"
                aria-label={`${question.header} - 其他`}
                value={draft.otherText}
                maxLength={OTHER_TEXT_MAX}
                disabled={controlsDisabled}
                placeholder="请输入你的回答"
                onChange={(event) => setOtherText(question.questionId, event.target.value)}
              />
            ) : null}
          </fieldset>
        );
      })}

      <div className="assistant-clarification-actions">
        <Button kind="secondary" disabled={controlsDisabled} onClick={onCancel}>
          暂不回答
        </Button>
        <Button kind="primary" disabled={!canSubmit} onClick={onSubmit}>
          提交
        </Button>
      </div>
    </div>
  );
}

export default ClarificationCard;
