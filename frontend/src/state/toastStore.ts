import { create } from "zustand";

export type ToastTone = "error" | "success" | "info" | "warning";

export type ToastItem = {
  id: string;
  tone: ToastTone;
  message: string;
};

type ToastState = {
  toasts: ToastItem[];
  notifyError: (message: string) => void;
  notifySuccess: (message: string) => void;
  notifyInfo: (message: string) => void;
  notifyWarning: (message: string) => void;
  dismiss: (id: string) => void;
  clear: () => void;
};

// 同屏最多并存的提示数：超过则丢最旧的，避免连环通知把界面堆满。
const MAX_TOASTS = 3;

let sequence = 0;

function makeNotifier(
  tone: ToastTone,
  set: (
    partial:
      | Partial<ToastState>
      | ((state: ToastState) => Partial<ToastState>),
  ) => void,
): (message: string) => void {
  return (message) =>
    set((state) => {
      const trimmed = message.trim();
      if (!trimmed) return state;
      // 紧邻的同一条提示不重复弹（同一动作连续触发时不刷屏）。
      const latest = state.toasts[state.toasts.length - 1];
      if (latest && latest.message === trimmed && latest.tone === tone) return state;
      sequence += 1;
      const next: ToastItem = {
        id: `toast_${Date.now()}_${sequence}`,
        tone,
        message: trimmed,
      };
      return { toasts: [...state.toasts, next].slice(-MAX_TOASTS) };
    });
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  notifyError: makeNotifier("error", set),
  notifySuccess: makeNotifier("success", set),
  notifyInfo: makeNotifier("info", set),
  notifyWarning: makeNotifier("warning", set),
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
  clear: () => set({ toasts: [] }),
}));
