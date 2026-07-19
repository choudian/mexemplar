import { useEffect } from "react";
import { AlertCircle, X } from "lucide-react";

import { useAssistantStore } from "../state/assistantStore";
import { useBrainStore } from "../state/brainStore";
import { useCompositionsStore } from "../state/compositionsStore";
import { useSettingsStore } from "../state/settingsStore";
import { useSkillMethodologyStore } from "../state/skillMethodologyStore";
import { useSkillsStore } from "../state/skillsStore";
import { useSpecialistStore } from "../state/specialistStore";
import { useTeachingStore } from "../state/teachingStore";
import { useToastStore } from "../state/toastStore";

const ERROR_TOAST_TTL_MS = 7000;

// 各业务 store 都把"最近一次错误"收敛在 lastError 字段上。这里订阅它们的变化，
// 把新出现的错误统一弹成顶部 toast，替代过去散落在各屏底部的内联红字。
type LastErrorStore = {
  subscribe: (
    listener: (
      state: { lastError: string | null },
      prev: { lastError: string | null },
    ) => void,
  ) => () => void;
};

const LAST_ERROR_STORES: LastErrorStore[] = [
  useAssistantStore,
  useTeachingStore,
  useSkillsStore,
  useSkillMethodologyStore,
  useCompositionsStore,
  useSettingsStore,
  useBrainStore,
  useSpecialistStore,
];

export function ErrorToastHost(): JSX.Element | null {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);

  useEffect(() => {
    const notifyError = useToastStore.getState().notifyError;
    const unsubscribers = LAST_ERROR_STORES.map((store) =>
      store.subscribe((state, prev) => {
        if (state.lastError && state.lastError !== prev.lastError) {
          notifyError(state.lastError);
        }
      }),
    );
    return () => unsubscribers.forEach((unsubscribe) => unsubscribe());
  }, []);

  // 只渲染 error tone；success/info/warning 由 InfoToastHost 承载。
  const errorToasts = toasts.filter((toast) => toast.tone === "error");

  if (errorToasts.length === 0) return null;

  return (
    <div className="error-toast-stack" role="region" aria-label="错误提示">
      {errorToasts.map((toast) => (
        <ErrorToastItem key={toast.id} id={toast.id} message={toast.message} onDismiss={dismiss} />
      ))}
    </div>
  );
}

function ErrorToastItem({
  id,
  message,
  onDismiss,
}: {
  id: string;
  message: string;
  onDismiss: (id: string) => void;
}): JSX.Element {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(id), ERROR_TOAST_TTL_MS);
    return () => window.clearTimeout(timer);
  }, [id, onDismiss]);

  return (
    <div className="error-toast" role="alert">
      <AlertCircle className="error-toast-icon" size={16} aria-hidden="true" />
      <span className="error-toast-message">{message}</span>
      <button
        className="error-toast-close"
        type="button"
        aria-label="关闭提示"
        onClick={() => onDismiss(id)}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
