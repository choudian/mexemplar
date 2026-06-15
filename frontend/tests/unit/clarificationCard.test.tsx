import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import type { ClarificationRequest } from "../../src/api/assistant";
import ClarificationCard, {
  allQuestionsAnswered,
  EMPTY_DRAFT,
  isQuestionAnswered,
} from "../../src/screens/assistant/ClarificationCard";
import type { ClarificationQuestionDraft } from "../../src/state/assistantStore";

function singleSelectRequest(): ClarificationRequest {
  return {
    requestId: "clr_1",
    sessionId: "s1",
    status: "pending",
    questions: [
      {
        questionId: "q1",
        question: "选择执行方式？",
        header: "执行方式",
        multiSelect: false,
        options: [
          { optionId: "q1o1", label: "按顺序", description: "稳", preview: "step1 -> step2" },
          { optionId: "q1o2", label: "并行" },
        ],
      },
    ],
  };
}

function multiSelectRequest(): ClarificationRequest {
  return {
    requestId: "clr_2",
    sessionId: "s1",
    status: "pending",
    questions: [
      {
        questionId: "q1",
        question: "选择范围？",
        header: "范围",
        multiSelect: true,
        options: [
          { optionId: "q1o1", label: "前端" },
          { optionId: "q1o2", label: "后端" },
        ],
      },
    ],
  };
}

/** 受控 wrapper：用真实组件交互驱动 draft 状态。 */
function Harness({
  clarification,
  onSubmit = vi.fn(),
  onCancel = vi.fn(),
  submitting = false,
}: {
  clarification: ClarificationRequest;
  onSubmit?: () => void;
  onCancel?: () => void;
  submitting?: boolean;
}) {
  const [drafts, setDrafts] = useState<Record<string, ClarificationQuestionDraft>>({});
  return (
    <ClarificationCard
      clarification={clarification}
      drafts={drafts}
      submitting={submitting}
      onDraftChange={(qid, d) => setDrafts((prev) => ({ ...prev, [qid]: d }))}
      onSubmit={onSubmit}
      onCancel={onCancel}
    />
  );
}

describe("ClarificationCard 选择规则纯函数", () => {
  test("单选：恰一个选项算已答", () => {
    const q = singleSelectRequest().questions[0];
    expect(isQuestionAnswered(q, { optionIds: ["q1o1"], otherSelected: false, otherText: "" })).toBe(true);
    expect(isQuestionAnswered(q, EMPTY_DRAFT)).toBe(false);
  });

  test("单选：选其他且填内容算已答；空其他不算", () => {
    const q = singleSelectRequest().questions[0];
    expect(isQuestionAnswered(q, { optionIds: [], otherSelected: true, otherText: "自定义" })).toBe(true);
    expect(isQuestionAnswered(q, { optionIds: [], otherSelected: true, otherText: "" })).toBe(false);
  });

  test("多选：选项或其他任一即已答", () => {
    const q = multiSelectRequest().questions[0];
    expect(isQuestionAnswered(q, { optionIds: ["q1o1", "q1o2"], otherSelected: false, otherText: "" })).toBe(true);
    expect(isQuestionAnswered(q, { optionIds: [], otherSelected: true, otherText: "x" })).toBe(true);
    expect(isQuestionAnswered(q, EMPTY_DRAFT)).toBe(false);
  });

  test("allQuestionsAnswered 聚合", () => {
    const req = singleSelectRequest();
    expect(allQuestionsAnswered(req, {})).toBe(false);
    expect(allQuestionsAnswered(req, { q1: { optionIds: ["q1o1"], otherSelected: false, otherText: "" } })).toBe(true);
  });
});

describe("ClarificationCard 渲染与交互", () => {
  test("渲染问题/选项/纯文本预览", () => {
    render(<Harness clarification={singleSelectRequest()} />);
    expect(screen.getByText("选择执行方式？")).toBeInTheDocument();
    expect(screen.getByText("按顺序")).toBeInTheDocument();
    // 预览按纯文本展示
    expect(screen.getByText("step1 -> step2")).toBeInTheDocument();
  });

  test("提交按钮在未作答前 disabled，作答后启用", () => {
    render(<Harness clarification={singleSelectRequest()} />);
    const submit = screen.getByRole("button", { name: "提交" });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByLabelText("按顺序", { exact: false }));
    expect(submit).not.toBeDisabled();
  });

  test("单选选'其他'取消普通选项并显示输入框", () => {
    render(<Harness clarification={singleSelectRequest()} />);
    fireEvent.click(screen.getByLabelText("按顺序", { exact: false }));
    // 选其他
    const radios = screen.getAllByRole("radio");
    fireEvent.click(radios[radios.length - 1]); // 最后一个是"其他"
    // 普通选项被取消
    expect((screen.getByLabelText("按顺序", { exact: false }) as HTMLInputElement).checked).toBe(false);
    // 其他输入框出现
    expect(screen.getByPlaceholderText("请输入你的回答")).toBeInTheDocument();
  });

  test("多选允许普通选项与其他并存", () => {
    render(<Harness clarification={multiSelectRequest()} />);
    fireEvent.click(screen.getByLabelText("前端", { exact: false }));
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[checkboxes.length - 1]); // "其他"
    expect((screen.getByLabelText("前端", { exact: false }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByPlaceholderText("请输入你的回答")).toBeInTheDocument();
  });

  test("点击提交/暂不回答触发回调", () => {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(<Harness clarification={singleSelectRequest()} onSubmit={onSubmit} onCancel={onCancel} />);
    fireEvent.click(screen.getByLabelText("并行", { exact: false }));
    fireEvent.click(screen.getByRole("button", { name: "提交" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "暂不回答" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  test("提交期间全部控件 disabled", () => {
    render(<Harness clarification={singleSelectRequest()} submitting />);
    expect(screen.getByRole("button", { name: "提交" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "暂不回答" })).toBeDisabled();
    expect(screen.getAllByRole("radio")[0]).toBeDisabled();
  });

  test("展示倒计时", () => {
    const req = singleSelectRequest();
    req.expiresAt = new Date(Date.now() + 120000).toISOString();
    render(<Harness clarification={req} />);
    expect(screen.getByText(/剩余 \d+:\d{2}/)).toBeInTheDocument();
  });
});
