import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";

const DEFAULT_MINIMIZE_TIMEOUT_MS = 1500;
const DEFAULT_MINIMIZE_POLL_MS = 50;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export async function minimizeWindowForDesktopRecording(
  timeoutMs = DEFAULT_MINIMIZE_TIMEOUT_MS,
  pollMs = DEFAULT_MINIMIZE_POLL_MS,
): Promise<void> {
  await invoke("minimize");

  const appWindow = getCurrentWindow();
  const startedAt = Date.now();
  while (Date.now() - startedAt <= timeoutMs) {
    if (await appWindow.isMinimized()) {
      return;
    }
    await delay(pollMs);
  }

  throw new Error("窗口最小化未完成，已取消桌面录制启动。");
}
