import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { BackendGate } from "../../src/app/BackendGate";
import type { BackendConnectionState } from "../../src/api/client";

function connection(status: BackendConnectionState["status"]): BackendConnectionState {
  return {
    status,
    message: `status=${status}`,
    checks: [],
    serverTime: "2026-05-10T00:00:00Z",
  };
}

function Child(): JSX.Element {
  return <div data-testid="screen-content">屏幕内容</div>;
}

describe("BackendGate", () => {
  test("renders the screen content when backend is ready", () => {
    render(
      <BackendGate backend={connection("ready")} onRetry={() => {}}>
        <Child />
      </BackendGate>,
    );

    expect(screen.getByTestId("screen-content")).toBeInTheDocument();
    expect(screen.queryByText("连不上本地服务")).not.toBeInTheDocument();
  });

  test("blocks the screen with a recovery card when the backend connection failed", () => {
    render(
      <BackendGate backend={connection("failed")} onRetry={() => {}}>
        <Child />
      </BackendGate>,
    );

    expect(screen.getByText("连不上本地服务")).toBeInTheDocument();
    expect(screen.queryByTestId("screen-content")).not.toBeInTheDocument();
  });

  test("retry button re-triggers a backend connection", () => {
    const onRetry = vi.fn();
    render(
      <BackendGate backend={connection("failed")} onRetry={onRetry}>
        <Child />
      </BackendGate>,
    );

    fireEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  test("shows a connecting state instead of empty screens while starting", () => {
    render(
      <BackendGate backend={null} onRetry={() => {}}>
        <Child />
      </BackendGate>,
    );

    expect(screen.getByText("正在连接本地服务…")).toBeInTheDocument();
    expect(screen.queryByTestId("screen-content")).not.toBeInTheDocument();
  });

  test("keeps the screen visible but warns with a banner when degraded", () => {
    const onRetry = vi.fn();
    render(
      <BackendGate backend={connection("degraded")} onRetry={onRetry}>
        <Child />
      </BackendGate>,
    );

    expect(screen.getByTestId("screen-content")).toBeInTheDocument();
    expect(screen.getByText(/连接不太稳定/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
