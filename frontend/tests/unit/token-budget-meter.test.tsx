import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { TokenBudgetMeter } from "../../src/components/TokenBudgetMeter";

describe("TokenBudgetMeter", () => {
  test("uses API-provided thresholds for tone and display", () => {
    const thresholds = { warn_threshold: 10, danger_threshold: 20 };
    const { container, rerender } = render(
      <TokenBudgetMeter itemCount={2} thresholds={thresholds} tokenEstimate={9} />,
    );

    expect(container.firstElementChild).toHaveAttribute("data-tone", "ok");
    expect(screen.getByText("9 tokens")).toBeInTheDocument();
    expect(screen.getByText("warn 10 / danger 20")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("4096");
    expect(document.body.textContent).not.toContain("8192");

    rerender(<TokenBudgetMeter itemCount={2} thresholds={thresholds} tokenEstimate={15} />);
    expect(container.firstElementChild).toHaveAttribute("data-tone", "warn");

    rerender(<TokenBudgetMeter itemCount={2} thresholds={thresholds} tokenEstimate={25} />);
    expect(container.firstElementChild).toHaveAttribute("data-tone", "danger");
  });
});
