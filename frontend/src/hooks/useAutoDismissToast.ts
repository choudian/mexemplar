import { useEffect } from "react";

export function useAutoDismissToast(
  toast: unknown,
  dismiss: () => void,
  timeoutMs: number = 8000,
): void {
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(dismiss, timeoutMs);
    return () => clearTimeout(timer);
  }, [toast, dismiss, timeoutMs]);
}
