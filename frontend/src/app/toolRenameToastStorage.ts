const TOOL_RENAME_TOAST_STORAGE_KEY = "mexemplar.toolRenameToast.dismissed";

export function isToolRenameToastDismissed(): boolean {
  try {
    return window.localStorage.getItem(TOOL_RENAME_TOAST_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function markToolRenameToastDismissed(): void {
  try {
    window.localStorage.setItem(TOOL_RENAME_TOAST_STORAGE_KEY, "1");
  } catch {
    // Storage can be disabled in hardened browser contexts; this toast is best-effort.
  }
}
