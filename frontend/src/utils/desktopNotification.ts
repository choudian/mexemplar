// T044: 桌面通知桥接。仅 Tauri 环境可用；浏览器/单测环境降级为静默无操作。
// 动态 import @tauri-apps/plugin-notification，失败时不抛——非 Tauri 环境属正常降级。

export interface DesktopNotificationInput {
  title: string;
  body?: string;
}

let _tauriAvailable: boolean | null = null;

async function isTauriAvailable(): Promise<boolean> {
  if (_tauriAvailable !== null) return _tauriAvailable;
  // Tauri 注入 window.__TAURI_INTERNALS__；浏览器环境无此对象。
  const win = window as unknown as { __TAURI_INTERNALS__?: unknown };
  _tauriAvailable = Boolean(win.__TAURI_INTERNALS__);
  return _tauriAvailable;
}

export async function sendDesktopNotification(input: DesktopNotificationInput): Promise<void> {
  try {
    if (!(await isTauriAvailable())) return;
    const mod = await import("@tauri-apps/plugin-notification");
    // sendNotification 是同步 API，但 permission 检查异步；缺失权限时静默跳过。
    if (typeof mod.isPermissionGranted === "function") {
      let granted = await mod.isPermissionGranted();
      if (!granted && typeof mod.requestPermission === "function") {
        const permission = await mod.requestPermission();
        granted = permission === "granted";
      }
      if (!granted) return;
    }
    mod.sendNotification({ title: input.title, body: input.body });
  } catch {
    // 非致命：桌面通知失败不应影响 UI 流程。
  }
}
