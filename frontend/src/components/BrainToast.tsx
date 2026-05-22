import { ExternalLink, X } from "lucide-react";

import { Button, IconButton } from "./primitives";

interface BrainToastProps {
  toast: {
    name: string;
    reason: string;
    managementUrl: string;
  } | null;
  onDismiss: () => void;
  onOpen: () => void;
}

export function BrainToast({ toast, onDismiss, onOpen }: BrainToastProps): JSX.Element | null {
  if (!toast) return null;
  return (
    <aside className="brain-toast" aria-live="polite" role="status">
      <div className="brain-toast-body">
        <strong>已自动招募：{toast.name}</strong>
        <span>{toast.reason || "检测到可复用的委托模式。"}</span>
      </div>
      <div className="brain-toast-actions">
        <Button kind="secondary" onClick={onOpen}>
          <ExternalLink size={14} />
          查看
        </Button>
        <IconButton label="关闭招募通知" onClick={onDismiss}>
          <X size={14} />
        </IconButton>
      </div>
    </aside>
  );
}

export default BrainToast;
