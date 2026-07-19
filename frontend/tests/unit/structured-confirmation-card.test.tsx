import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { StructuredConfirmationCard } from "../../src/components/StructuredConfirmationCard";

const draft = {
  title: "查竞品价格",
  scheduleDescription: "每天 09:00",
  instruction: "查询竞品 X 的最新价格",
  scheduleKind: "recurring",
  sourceType: "direct",
} as any;

const futureExpiresAt = "2099-01-01T00:00:00Z";

function renderCard(overrides: Record<string, unknown> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const props = {
    requestId: "scf_1",
    draft,
    expiresAt: futureExpiresAt,
    unattendedAutoApprove: false,
    submitting: false,
    onSubmit,
    onCancel,
    ...overrides,
  } as any;
  const result = render(<StructuredConfirmationCard {...props} />);
  return { ...result, onSubmit, onCancel, props };
}

describe("StructuredConfirmationCard", () => {
  let dateNowSpy: ReturnType<typeof vi.spyOn> | null = null;

  afterEach(() => {
    if (dateNowSpy) {
      dateNowSpy.mockRestore();
      dateNowSpy = null;
    }
  });

  test("renders draft title / schedule description / instruction", () => {
    renderCard();
    expect(screen.getByDisplayValue("查竞品价格")).toBeInTheDocument();
    expect(screen.getByLabelText("任务标题")).toHaveAttribute("maxlength", "120");
    expect(screen.getByText("每天 09:00")).toBeInTheDocument();
    expect(screen.getByDisplayValue("查询竞品 X 的最新价格")).toBeInTheDocument();
  });

  test("confirm submits edited draft + unattended flag", () => {
    const { onSubmit } = renderCard();
    // 勾选免确认
    fireEvent.click(screen.getByRole("checkbox"));
    // 确认创建
    fireEvent.click(screen.getByRole("button", { name: /确认创建/ }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [editedDraft, unattended] = onSubmit.mock.calls[0];
    expect(unattended).toBe(true);
    expect(editedDraft.title).toBe("查竞品价格");
    expect(editedDraft.instruction).toBe("查询竞品 X 的最新价格");
  });

  test("cancel invokes onCancel", () => {
    const { onCancel } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /暂不创建/ }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  test("expired disables submit (fail-closed)", () => {
    // Mock Date.now so the expiry is in the past
    dateNowSpy = vi.spyOn(Date, "now").mockReturnValue(new Date("2100-01-01T00:00:00Z").getTime());
    renderCard({ expiresAt: "2000-01-01T00:00:00Z" });
    expect(screen.getByText("已超时")).toBeInTheDocument();
    const submitBtn = screen.getByRole("button", { name: /确认创建/ });
    expect(submitBtn).toBeDisabled();
  });

  test("empty instruction disables submit (validation)", () => {
    renderCard();
    const textarea = screen.getByLabelText("任务指令");
    fireEvent.change(textarea, { target: { value: "   " } });
    const submitBtn = screen.getByRole("button", { name: /确认创建/ });
    expect(submitBtn).toBeDisabled();
  });
});
