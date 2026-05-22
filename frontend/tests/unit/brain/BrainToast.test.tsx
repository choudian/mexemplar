import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import BrainToast from "../../../src/components/BrainToast";

describe("BrainToast", () => {
  test("shows a non-modal recruitment notification with specialist link action", () => {
    const onDismiss = vi.fn();
    const onOpen = vi.fn();

    render(
      <BrainToast
        onDismiss={onDismiss}
        onOpen={onOpen}
        toast={{
          name: "报表专员",
          reason: "检测到持续报表委托",
          managementUrl: "/brain/specialists",
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("已自动招募：报表专员");
    expect(screen.getByText("检测到持续报表委托")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭招募通知" }));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  test("renders nothing when there is no toast", () => {
    const { container } = render(<BrainToast toast={null} onDismiss={vi.fn()} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
