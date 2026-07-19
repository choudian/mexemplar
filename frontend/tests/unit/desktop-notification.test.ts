import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const notificationPlugin = vi.hoisted(() => ({
  isPermissionGranted: vi.fn<() => Promise<boolean>>(),
  requestPermission: vi.fn<() => Promise<"granted" | "denied">>(),
  sendNotification: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-notification", () => notificationPlugin);

type TauriWindow = Window & { __TAURI_INTERNALS__?: unknown };

function setTauriAvailable(available: boolean): void {
  const target = window as TauriWindow;
  if (!available) {
    delete target.__TAURI_INTERNALS__;
    return;
  }
  Object.defineProperty(target, "__TAURI_INTERNALS__", {
    value: {},
    configurable: true,
    writable: true,
  });
}

async function loadSender() {
  const module = await import("../../src/utils/desktopNotification");
  return module.sendDesktopNotification;
}

describe("sendDesktopNotification", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    setTauriAvailable(true);
  });

  afterEach(() => {
    setTauriAvailable(false);
  });

  test("sends immediately when permission is already granted", async () => {
    notificationPlugin.isPermissionGranted.mockResolvedValue(true);
    const sendDesktopNotification = await loadSender();

    await sendDesktopNotification({ title: "完成", body: "任务 A" });

    expect(notificationPlugin.requestPermission).not.toHaveBeenCalled();
    expect(notificationPlugin.sendNotification).toHaveBeenCalledWith({
      title: "完成",
      body: "任务 A",
    });
  });

  test("requests permission and sends after a granted decision", async () => {
    notificationPlugin.isPermissionGranted.mockResolvedValue(false);
    notificationPlugin.requestPermission.mockResolvedValue("granted");
    const sendDesktopNotification = await loadSender();

    await sendDesktopNotification({ title: "需要帮助", body: "任务 B" });

    expect(notificationPlugin.requestPermission).toHaveBeenCalledOnce();
    expect(notificationPlugin.sendNotification).toHaveBeenCalledOnce();
  });

  test("does not send after permission is denied", async () => {
    notificationPlugin.isPermissionGranted.mockResolvedValue(false);
    notificationPlugin.requestPermission.mockResolvedValue("denied");
    const sendDesktopNotification = await loadSender();

    await sendDesktopNotification({ title: "失败", body: "任务 C" });

    expect(notificationPlugin.sendNotification).not.toHaveBeenCalled();
  });

  test("swallows plugin failures without breaking the UI flow", async () => {
    notificationPlugin.isPermissionGranted.mockRejectedValue(
      new Error("plugin unavailable"),
    );
    const sendDesktopNotification = await loadSender();

    await expect(
      sendDesktopNotification({ title: "完成", body: "任务 D" }),
    ).resolves.toBeUndefined();
    expect(notificationPlugin.sendNotification).not.toHaveBeenCalled();
  });

  test("is a no-op outside a Tauri window", async () => {
    setTauriAvailable(false);
    const sendDesktopNotification = await loadSender();

    await sendDesktopNotification({ title: "完成", body: "浏览器" });

    expect(notificationPlugin.isPermissionGranted).not.toHaveBeenCalled();
    expect(notificationPlugin.sendNotification).not.toHaveBeenCalled();
  });
});
