import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// React 18 在非 Jest runner 中需要显式声明 act 环境；否则异步组件测试即使
// 正确 await act() 也会产生误导性的 “environment is not configured” 警告。
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    isMinimized: vi.fn().mockResolvedValue(true),
  }),
}));
