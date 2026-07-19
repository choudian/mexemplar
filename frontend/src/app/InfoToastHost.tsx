import { useEffect } from "react";
import { Info, X } from "lucide-react";

import { useToastStore } from "../state/toastStore";
import type { ToastTone } from "../state/toastStore";

const INFO_TOAST_TTL_MS = 6000;

// 与 error tone 的 ErrorToastHost 分离：success/info/warning 是「状态告知」语义，
// role=status，落屏位置和视觉不同；error 仍走 role=alert。
const RENDERED_TONES: ToastTone[] = ["success", "info", "warning"];

export function InfoToastHost(): JSX.Element | null {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);

  const infoToasts = toasts.filter((toast) => RENDERED_TONES.includes(toast.tone));

  if (infoToasts.length === 0) return null;

  return (
    <div className="info-toast-stack" role="region" aria-label="状态提示">
      {infoToasts.map((toast) => (
        <InfoToastItem
          key={toast.id}
          id={toast.id}
          tone={toast.tone}
          message={toast.message}
          onDismiss={dismiss}
        />
      ))}
    </div>
  );
}

function InfoToastItem({
  id,
  tone,
  message,
  onDismiss,
}: {
  id: string;
  tone: ToastTone;
  message: string;
  onDismiss: (id: string) => void;
}): JSX.Element {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(id), INFO_TOAST_TTL_MS);
    return () => window.clearTimeout(timer);
  }, [id, onDismiss]);

  return (
    <div className={`info-toast info-toast-${tone}`} role="status">
      <Info className="info-toast-icon" size={16} aria-hidden="true" />
      <span className="info-toast-message">{message}</span>
      <button
        className="info-toast-close"
        type="button"
        aria-label="关闭提示"
        onClick={() => onDismiss(id)}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
