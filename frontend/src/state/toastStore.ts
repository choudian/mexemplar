import { create } from "zustand";

export type ToastTone = "error";

export type ToastItem = {
  id: string;
  tone: ToastTone;
  message: string;
};

type ToastState = {
  toasts: ToastItem[];
  notifyError: (message: string) => void;
  dismiss: (id: string) => void;
  clear: () => void;
};

// 同屏最多并存的错误提示数：超过则丢最旧的，避免连环报错把界面堆满。
const MAX_TOASTS = 3;

let sequence = 0;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  notifyError: (message) =>
    set((state) => {
      const trimmed = message.trim();
      if (!trimmed) return state;
      // 紧邻的同一条错误不重复弹（同一动作连续失败时不刷屏）。
      const latest = state.toasts[state.toasts.length - 1];
      if (latest && latest.message === trimmed) return state;
      sequence += 1;
      const next: ToastItem = {
        id: `toast_${Date.now()}_${sequence}`,
        tone: "error",
        message: trimmed,
      };
      return { toasts: [...state.toasts, next].slice(-MAX_TOASTS) };
    }),
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
  clear: () => set({ toasts: [] }),
}));
